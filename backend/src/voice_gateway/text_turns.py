"""Shared text-turn processor: one service behind STT (recorder) and Alice.

Extracted from :mod:`voice_gateway.pipeline`: the segment after speech is
recognized and before audio is synthesized. Both channels submit a
:class:`TextTurnRequest` and receive a :class:`TextTurnResult`; the recorder
pipeline then synthesizes speech from the reply, while Alice returns the
reply text through her own protocol. The model, prompts, Git outbox and
history behavior are unchanged (plan task 2).

Per-channel origin (``channel``, ``client_id``) is recorded in the source
frontmatter, while the shared conversation context stays keyed by the
existing ``context_id`` (the recorder's ``device_id``), so no history
migration is needed (plan: "Использовать context_id как прежний device_id").
Alice request IDs always carry the ``alice:`` prefix so the LLM session
store and knowledge source IDs can never collide across channels.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.src.voice_gateway.agents.base import AgentClient, AgentRequest
from backend.src.voice_gateway.archive import atomic_write_bytes, atomic_write_json
from backend.src.voice_gateway.hermes.stage import HermesStage
from backend.src.voice_gateway.knowledge.git_sync import GitSync
from backend.src.voice_gateway.knowledge.store import KnowledgeConflict, KnowledgeStore
from backend.src.voice_gateway.models import Transcript
from backend.src.voice_gateway.models.hermes_response import HermesResponse
from backend.src.voice_gateway.dialogue import DialogueStore
from backend.src.voice_gateway.usage.recorder import UsageRecorder

logger = logging.getLogger(__name__)

#: Prefix for every request ID coming from the Alice channel. The recorder
#: keeps UUID request IDs; the prefix keeps LLM idempotency keys and vault
#: source IDs disjoint between channels.
ALICE_REQUEST_PREFIX = "alice:"

#: Whole-service deadline (plan task 2): one text turn — Git refresh, LLM,
#: publish and history — must fit into 180 s. Timeouts raise ``timeout``.
TEXT_TURN_DEADLINE_SECONDS = 180.0


class TextTurnError(Exception):
    """Bounded failure code for a shared text turn (mirrors pipeline codes)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class TextTurnRequest:
    """One completed user utterance, already reduced to text.

    ``context_id`` is the shared conversation key (the recorder's
    ``device_id``); ``client_id`` and ``channel`` only record origin.
    ``archive_dir`` is where the service stores its durable files; the
    audio pipeline passes its turn dir, Alice passes ``data/archive/alice/<job-id>/``.
    """

    request_id: str
    turn_id: str
    context_id: str
    client_id: str
    channel: str
    transcript: str
    created_at: str
    archive_dir: Path
    answer_to: str | None = None


@dataclass(frozen=True, slots=True)
class TextTurnResult:
    """Reply text plus optional note and receipt, as produced today."""

    reply: str
    note: Any  # HermesNote-shaped dict, same contract as HermesResponse.note
    receipt: dict | None
    provider: str
    model: str | None
    clarification: dict | None = None


class TextTurnProcessor:
    """Runs one text turn through Git refresh → context → LLM → publish → history.

    One instance is shared by both channels. Calls for a single ``context_id``
    are serialized with a per-context lock (plan: "Последовательно обрабатывать
    один context_id"); different contexts may run concurrently. The lock is
    held only around processing, never around a file lock wait for LLM —
    the knowledge store's own file lock is acquired and released inside each
    knowledge call, so the LLM network call happens outside it.
    """

    def __init__(
        self,
        agent: AgentClient | None,
        hermes: HermesStage | None = None,
        *,
        knowledge: KnowledgeStore | None = None,
        git_sync: GitSync | None = None,
        usage_recorder: UsageRecorder | None = None,
        metrics=None,
        deadline_seconds: float = TEXT_TURN_DEADLINE_SECONDS,
    ) -> None:
        if agent is None and hermes is None:
            # Match the pipeline's construction-time leniency: the gateway app
            # must boot without an LLM (ingest-only contract); processing
            # raises the bounded code instead.
            self.agent = None
            self.hermes = None
        else:
            self.agent = agent
            self.hermes = hermes
        self.dialogue = DialogueStore(knowledge.state / "dialogue.sqlite3") if knowledge else None
        self.knowledge = knowledge
        self.git_sync = git_sync
        self.usage_recorder = usage_recorder
        self.metrics = metrics
        self.deadline_seconds = deadline_seconds
        self._context_locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, context_id: str) -> asyncio.Lock:
        lock = self._context_locks.get(context_id)
        if lock is None:
            lock = asyncio.Lock()
            self._context_locks[context_id] = lock
        return lock

    async def process(self, request: TextTurnRequest) -> TextTurnResult:
        """Process one text turn under the per-context lock and deadline."""
        if not request.transcript.strip():
            raise TextTurnError("empty_transcript")
        if self.agent is None and self.hermes is None:
            raise TextTurnError("agent_unavailable")
        async with self._lock_for(request.context_id):
            try:
                async with asyncio.timeout(self.deadline_seconds):
                    result = await self._process(request)
                    await self._finish_usage(request, result=result, outcome="pending")
                    return result
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                raise TextTurnError("agent_timeout") from None
            except TextTurnError:
                raise
            except KnowledgeConflict:
                raise TextTurnError("knowledge_conflict") from None
            except Exception as exc:
                code = getattr(exc, "code", None)
                if code in {
                    "agent_auth_required", "agent_rate_limited", "agent_timeout",
                    "agent_invalid_response", "permission_required", "interrupted",
                    "agent_unavailable", "agent_config_error", "idempotency_conflict",
                    "hermes_failed", "hermes_invalid_response",
                }:
                    raise TextTurnError(code) from None
                if hasattr(exc, "status") and getattr(exc, "status") in {
                    "hermes_failed", "hermes_invalid_response"
                }:
                    raise TextTurnError(getattr(exc, "status")) from None
                logger.exception("text turn %s failed", request.turn_id)
                raise TextTurnError("agent_unavailable") from None

    async def _finish_usage(self, request: TextTurnRequest, *,
                            result: TextTurnResult | None = None, outcome: str) -> None:
        if self.usage_recorder is None:
            return
        receipt = result.receipt if result is not None else None
        operation = receipt.get("operation", "none") if receipt else "none"
        saved = bool(
            receipt
            and receipt.get("status") != "needs_review"
            and operation in {"capture", "amend"}
        )
        await self.usage_recorder.finish_turn_async(
            request.turn_id, channel=request.channel, outcome=outcome,
            operation=operation, note_saved=saved,
        )

    async def _process(self, request: TextTurnRequest) -> TextTurnResult:
        archive_dir = Path(request.archive_dir)
        # Alice's service calls must never be mistaken for recorder audio
        # metadata; the audio pipeline keeps its own metadata writing.
        context_path = archive_dir / "knowledge-context.json"
        source_id: str | None = None
        context: dict | None = None
        receipt: dict | None = None
        if self.knowledge is not None:
            # Capture evidence before network refresh: a Git outage cannot erase dictation.
            job = {"device_id": request.context_id, "request_id": request.request_id,
                   "turn_id": request.turn_id, "created_at": request.created_at,
                   "channel": request.channel, "client_id": request.client_id}
            source_id = await asyncio.to_thread(self.knowledge.capture, job, request.transcript)
            if self.git_sync is not None:
                sync_started = time.monotonic()
                sync_result = await asyncio.to_thread(self.git_sync.run_once)
                lock_was_busy = sync_result["status"] == "busy"
                if sync_result["status"] == "busy":
                    logger.info("Waiting for Obsidian Git lock for text turn %s", request.turn_id)
                while sync_result["status"] == "busy":
                    # The background publisher uses the same lock. Contention
                    # is transient; the enclosing turn deadline bounds waiting.
                    await asyncio.sleep(0.25)
                    final_attempt_started = time.monotonic()
                    sync_result = await asyncio.to_thread(self.git_sync.run_once)
                if lock_was_busy and self.metrics is not None:
                    self.metrics.git_lock_wait.observe(final_attempt_started - sync_started)
                if sync_result["status"] not in ("idle", "updated", "synced"):
                    await self._record_stage(request, "git_refresh", "error", sync_started)
                    logger.warning(
                        "Obsidian refresh blocked before text turn %s: %s",
                        request.turn_id, sync_result,
                    )
                    raise TextTurnError("knowledge_sync_failed")
                await self._record_stage(request, "git_refresh", "success", sync_started)
            receipt = await asyncio.to_thread(self.knowledge.receipt, source_id)
            if context_path.exists():
                context = json.loads(context_path.read_text())
            else:
                context = await asyncio.to_thread(
                    self.knowledge.context, request.context_id, source_id, request.transcript
                )
                atomic_write_json(context_path, context)

        pending = self.dialogue.pending(request.context_id) if self.dialogue else None
        if context is not None:
            # Persist the exact model input for retries, including pending evidence.
            if "pending_clarification" not in context:
                context["pending_clarification"] = pending
                if pending:
                    with self.knowledge._locked() as db:
                        pending["sources"] = [dict(source_id=row[0], transcript=row[1])
                            for sid in pending["source_ids"] for row in db.execute(
                                "SELECT id, transcript FROM evidence WHERE id=? AND device=?", (sid, request.context_id))]
                context["answer_to"] = (request.answer_to if pending and
                    request.answer_to == pending["question_id"] else None)
                atomic_write_json(context_path, context)
            pending = context["pending_clarification"]

        if receipt is not None:
            # A crash may have happened after the writer committed but before
            # history did; reuse the durable LLM result without regenerating.
            proposal_path = archive_dir / "knowledge-proposal.json"
            response = (HermesResponse.model_validate_json(proposal_path.read_text())
                        if proposal_path.exists() else HermesResponse(reply=receipt["reply"]))
            response.reply = receipt["reply"]
            metadata = {"provider": "knowledge", "model": None}
            if self.agent is not None and hasattr(self.agent, "record_turn"):
                await self.agent.complete(
                    AgentRequest(request.request_id, request.context_id, request.transcript, context,
                                 channel=request.channel, turn_id=request.turn_id)
                )
        elif self.knowledge is not None and (archive_dir / "knowledge-proposal.json").exists():
            # Query/clarification has no writer commit, but its decision must be
            # just as stable on retry as a published note.
            response = HermesResponse.model_validate_json((archive_dir / "knowledge-proposal.json").read_text())
            metadata = {"provider": "knowledge", "model": None}
        elif self.agent is not None:
            reply = await self.agent.complete(
                AgentRequest(request.request_id, request.context_id, request.transcript, context,
                             channel=request.channel, turn_id=request.turn_id)
            )
            response = HermesResponse.model_validate(
                {
                    "reply": reply.reply,
                    "clarification": reply.clarification,
                    "dialogue_resolution": reply.dialogue_resolution,
                    "note": reply.note or {"create": False, "title": "", "content": "", "tags": []},
                }
            )
            metadata = {"provider": reply.provider, "model": reply.model}
        else:
            response = await self.hermes.run(request.transcript)
            metadata = {"provider": "hermes", "model": None}

        if response.clarification or response.dialogue_resolution:
            if not self.dialogue or context is None:
                raise TextTurnError("agent_invalid_response")
            visible = {item["source_id"] for item in context.get("recent_sources", [])}
            visible.add(source_id)
            if pending:
                visible.update(pending["source_ids"])
            if response.clarification:
                if (not response.clarification.question.strip() or
                    not set(response.clarification.source_ids) <= visible):
                    raise TextTurnError("agent_invalid_response")
                with self.knowledge._locked() as db:
                    for sid in response.clarification.source_ids:
                        if not db.execute("SELECT 1 FROM evidence WHERE id=? AND device=?", (sid, request.context_id)).fetchone():
                            raise TextTurnError("agent_invalid_response")
            if response.dialogue_resolution and (not pending or
                response.dialogue_resolution.question_id != pending["question_id"]):
                raise TextTurnError("agent_invalid_response")

        if self.knowledge is not None and receipt is None:
            atomic_write_json(archive_dir / "knowledge-proposal.json", response.model_dump())
            try:
                publish_started = time.monotonic()
                logger.info("publishing Obsidian update for text turn %s", request.turn_id)
                receipt = await asyncio.to_thread(
                    self.knowledge.publish, source_id, request.context_id,
                    response.note, context, response.reply,
                )
                logger.info(
                    "published Obsidian update for text turn %s in %.2fs",
                    request.turn_id, time.monotonic() - publish_started,
                )
                response.reply = receipt["reply"]
                await self._record_stage(request, "publish", "success", publish_started)
            except KnowledgeConflict as exc:
                await asyncio.to_thread(self.knowledge.mark_review, source_id)
                await self._record_stage(request, "publish", "error", publish_started)
                receipt = {"source_id": source_id, "status": "needs_review", "reason": str(exc)}
                logger.warning("knowledge publication rejected for turn %s: %s", request.turn_id, exc)
                if str(exc) in {"broken wiki link", "links must use Затея paths"}:
                    response.reply = ("Исходная запись сохранена. Заметка не опубликована: "
                                      "в подготовленном тексте неверная ссылка.")
                else:
                    response.reply = ("Исходная запись сохранена. Обновление заметок требует проверки; "
                                      "существующие правки не перезаписаны.")
            atomic_write_json(archive_dir / "knowledge-result.json", receipt)

        clarification = None
        if self.dialogue and receipt and receipt.get("status") != "needs_review":
            clarification = self.dialogue.apply(request.context_id, source_id,
                response.clarification, response.dialogue_resolution, pending)
            if clarification:
                response.reply = clarification["question"]

        if self.agent is not None and hasattr(self.agent, "record_turn"):
            if receipt is None or receipt.get("status") != "needs_review":
                history_started = time.monotonic()
                logger.info("saving agent history for text turn %s", request.turn_id)
                await self.agent.record_turn(
                    request.context_id, request.request_id, request.transcript, response.reply
                )
                logger.info(
                    "saved agent history for text turn %s in %.2fs",
                    request.turn_id, time.monotonic() - history_started,
                )

        atomic_write_bytes(archive_dir / "reply.txt", response.reply.encode("utf-8"))
        atomic_write_bytes(archive_dir / "transcript.txt", request.transcript.encode("utf-8"))
        response_filename = (
            "hermes-response.json" if metadata["provider"] == "hermes" else "agent-response.json"
        )
        atomic_write_json(
            archive_dir / response_filename,
            {**metadata, "reply": response.reply, "note": response.note.model_dump()},
        )
        return TextTurnResult(
            reply=response.reply,
            note=response.note,
            receipt=receipt,
            provider=metadata["provider"],
            model=metadata["model"],
            clarification=clarification,
        )

    async def _record_stage(self, request: TextTurnRequest, stage: str, outcome: str,
                            started: float) -> None:
        if self.usage_recorder is not None:
            await self.usage_recorder.record_stage_async(
                channel=request.channel, stage=stage, outcome=outcome,
                elapsed_seconds=time.monotonic() - started,
            )
