"""Data models for the Alice adapter (plan task 3).

``AliceEvent`` is one webhook utterance reduced to what the gateway needs:
verified owner/context (filled by the auth layer, never trusted from JSON),
an idempotency key, a payload hash and the dialogue action. ``AliceJob``
wraps a :class:`~backend.src.voice_gateway.text_turns.TextTurnRequest` with
a durable status. ``AliceReply`` is the protocol answer frozen at accept
time so a webhook replay returns byte-identical content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Job statuses (plan task 3): queued → running → done/failed/needs_review.
JOB_STATUSES = ("queued", "running", "done", "failed", "needs_review")

#: Dialogue actions the router can produce (plan task 5 contracts them).
ACTION_START_DRAFT = "start_draft"
ACTION_APPEND_DRAFT = "append_draft"
ACTION_FINISH_DRAFT = "finish_draft"
ACTION_CANCEL_DRAFT = "cancel_draft"
ACTION_NEW_IDEA = "new_idea"
ACTION_STATUS = "status"
ACTION_HELP = "help"
ACTION_PING = "ping"
ACTION_LINKING = "linking"
ACTION_VERBATIM = "verbatim"
KNOWN_ACTIONS = frozenset({
    ACTION_START_DRAFT, ACTION_APPEND_DRAFT, ACTION_FINISH_DRAFT,
    ACTION_CANCEL_DRAFT, ACTION_NEW_IDEA, ACTION_STATUS, ACTION_HELP,
    ACTION_PING, ACTION_LINKING, ACTION_VERBATIM,
})

#: Draft text limit (plan task 3): overflow is refused, never truncated.
DRAFT_MAX_CHARS = 12_000

#: Bounded number of queued jobs per owner (plan task 3).
MAX_QUEUED_JOBS = 8


@dataclass(frozen=True, slots=True)
class AliceIdentity:
    """Verified owner identity from the auth layer (never from JSON)."""

    yandex_user_id: str
    context_id: str


@dataclass(frozen=True, slots=True)
class AliceEvent:
    """One verified webhook utterance.

    ``key`` is the idempotency key ``(skill_id, session_id, message_id)``;
    ``payload_hash`` detects the same key arriving with different content;
    ``action`` drives the store's dialogue transition. ``archive_dir`` is
    where finished job artifacts are written (root, per-job subdir added
    by the store).
    """

    owner: str
    context_id: str
    skill_id: str
    session_id: str
    message_id: str
    payload_hash: str
    action: str
    text: str
    has_screen: bool = False
    archive_dir: str | None = None

    def key(self) -> str:
        """Idempotency key: (skill_id, session_id, message_id)."""
        return f"{self.skill_id}:{self.session_id}:{self.message_id}"


@dataclass(frozen=True, slots=True)
class AliceJob:
    """One durable text-processing task."""

    job_id: str
    status: str
    request: Any  # TextTurnRequest
    reply: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class AliceReply:
    """Protocol answer frozen at accept time for idempotent replays."""

    text: str
    tts: str | None = None
    end_session: bool = False
    extra: dict = field(default_factory=dict)

    def as_protocol(self) -> dict:
        payload: dict[str, Any] = {"text": self.text}
        if self.tts is not None:
            payload["tts"] = self.tts
        if self.end_session:
            payload["end_session"] = True
        response: dict[str, Any] = {"response": payload}
        response.update(self.extra)
        return response
