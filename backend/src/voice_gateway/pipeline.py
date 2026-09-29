"""Shared file-based STT → agent → WAV pipeline for v2 worker jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import json
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from backend.src.voice_gateway.agents.base import AgentClient
from backend.src.voice_gateway.archive import atomic_write_bytes, atomic_write_json
from backend.src.voice_gateway.hermes.stage import HermesStage
from backend.src.voice_gateway.knowledge.store import KnowledgeStore
from backend.src.voice_gateway.knowledge.git_sync import GitSync
from backend.src.voice_gateway.stt.base import STTClientError, STTProvider
from backend.src.voice_gateway.models import Transcript
from backend.src.voice_gateway.stt.client import OpenAICompatibleSTT
from backend.src.voice_gateway.text_turns import TextTurnProcessor, TextTurnRequest, TextTurnError
from backend.src.voice_gateway.tts.base import TTSProvider, TTSProviderError
from backend.src.voice_gateway.tts.openai_compatible import OpenAICompatibleTTS
from backend.src.voice_gateway.usage.models import CallContext

logger = logging.getLogger(__name__)


class VoicePipelineError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class VoicePipeline:
    def __init__(
        self,
        stt: STTProvider | None,
        agent: AgentClient | None,
        hermes: HermesStage | None,
        tts: TTSProvider | None,
        *,
        deadline_seconds: float = 180.0,
        knowledge: KnowledgeStore | None = None,
        git_sync: GitSync | None = None,
        text_processor: TextTurnProcessor | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.git_sync = git_sync
        self.stt = stt
        self.agent = agent
        self.hermes = hermes
        self.tts = tts
        self.deadline_seconds = deadline_seconds
        # One shared text service behind STT: the recorder keeps its audio
        # stages (PCM → STT → TTS), the text segment delegates to the
        # processor that the Alice channel reuses (plan task 2).
        self.text_processor = text_processor or TextTurnProcessor(
            agent,
            hermes,
            knowledge=knowledge,
            git_sync=git_sync,
            deadline_seconds=deadline_seconds,
        )

    async def run(
        self,
        job: dict[str, Any],
        report_progress: Callable[[str], None] | None = None,
    ) -> Path:
        if self.stt is None:
            raise VoicePipelineError("stt_failed")
        if self.agent is None and self.hermes is None:
            raise VoicePipelineError("agent_unavailable")
        turn_dir = Path(job["audio_path"]).parent
        input_wav = turn_dir / "input.wav"
        output_part = turn_dir / "reply.wav.part"
        output_wav = turn_dir / "reply.wav"
        try:
            async with asyncio.timeout(self.deadline_seconds):
                await asyncio.to_thread(self._pcm_to_wav, Path(job["audio_path"]), input_wav)
                if report_progress:
                    report_progress("transcribing")
                if (turn_dir / "transcript.txt").exists():
                    transcript = Transcript(text=(turn_dir / "transcript.txt").read_text(), language="ru")
                elif isinstance(self.stt, OpenAICompatibleSTT):
                    transcript = await self.stt.transcribe_async(
                        input_wav,
                        context=CallContext(job["turn_id"], "recorder", "stt",
                                            self.stt._config.model),
                    )
                else:
                    transcript = await asyncio.to_thread(self.stt.transcribe, input_wav)
                if not transcript.text.strip():
                    raise VoicePipelineError("stt_failed")
                atomic_write_bytes(turn_dir / "transcript.txt", transcript.text.encode("utf-8"))
                if report_progress:
                    report_progress("thinking")
                result = await self.text_processor.process(TextTurnRequest(
                    request_id=job["request_id"],
                    turn_id=job["turn_id"],
                    context_id=job["device_id"],
                    client_id=job["device_id"],
                    channel="recorder",
                    transcript=transcript.text,
                    created_at=job["created_at"],
                    archive_dir=turn_dir,
                ))
                response_reply = result.reply
                receipt = result.receipt
                metadata = {"provider": result.provider, "model": result.model}
                response_note_dump = result.note.model_dump()
                atomic_write_bytes(turn_dir / "reply.txt", response_reply.encode("utf-8"))
                if self.tts is None:
                    raise VoicePipelineError("tts_failed")
                if report_progress:
                    report_progress("synthesizing")
                synthesis_started = time.monotonic()
                logger.info("starting speech synthesis for turn %s", job["turn_id"])
                synthesis_kwargs = {}
                if isinstance(self.tts, OpenAICompatibleTTS):
                    synthesis_kwargs["context"] = CallContext(
                        job["turn_id"], "recorder", "tts", self.tts._config.model
                    )
                synthesis = asyncio.create_task(asyncio.to_thread(
                    self.tts.synthesize, response_reply, output_part, **synthesis_kwargs
                ))
                try:
                    await asyncio.shield(synthesis)
                except asyncio.CancelledError:
                    synthesis.add_done_callback(lambda _: output_part.unlink(missing_ok=True))
                    raise
                logger.info(
                    "finished speech synthesis for turn %s in %.2fs",
                    job["turn_id"],
                    time.monotonic() - synthesis_started,
                )
                self._validate_reply_wav(output_part)
                os.replace(output_part, output_wav)
                atomic_write_bytes(turn_dir / "transcript.txt", transcript.text.encode("utf-8"))
                atomic_write_bytes(turn_dir / "reply.txt", response_reply.encode("utf-8"))
                response_filename = (
                    "hermes-response.json" if metadata["provider"] == "hermes"
                    else "agent-response.json"
                )
                atomic_write_json(
                    turn_dir / response_filename,
                    {**metadata, "reply": response_reply, "note": response_note_dump},
                )
                atomic_write_json(
                    turn_dir / "metadata.json",
                    {
                        "turn_id": job["turn_id"],
                        "device_id": job["device_id"],
                        "started_at": job["created_at"],
                        "finished_at": datetime.now(UTC).isoformat(),
                        "input_bytes": job["audio_bytes"],
                        "status": "success",
                        "transcript": transcript.text,
                        "reply": response_reply,
                        **metadata,
                    },
                )
                return output_wav
        except TimeoutError:
            output_part.unlink(missing_ok=True)
            raise VoicePipelineError("agent_timeout") from None
        except VoicePipelineError:
            output_part.unlink(missing_ok=True)
            raise
        except TextTurnError as exc:
            output_part.unlink(missing_ok=True)
            raise VoicePipelineError(exc.code) from None
        except STTClientError as exc:
            logger.warning(
                "speech recognition failed for turn %s: %s",
                job.get("turn_id", "unknown"),
                exc,
            )
            output_part.unlink(missing_ok=True)
            raise VoicePipelineError("stt_failed") from None
        except TTSProviderError:
            output_part.unlink(missing_ok=True)
            raise VoicePipelineError("tts_failed") from None
        except Exception as exc:
            output_part.unlink(missing_ok=True)
            if hasattr(exc, "status") and getattr(exc, "status") in {
                "hermes_failed", "hermes_invalid_response"
            }:
                raise VoicePipelineError(getattr(exc, "status")) from None
            code = getattr(exc, "code", None)
            if code in {
                "agent_auth_required", "agent_rate_limited", "agent_timeout",
                "agent_invalid_response", "permission_required", "interrupted",
                "agent_unavailable", "agent_config_error", "idempotency_conflict",
            }:
                raise VoicePipelineError(code) from None
            raise VoicePipelineError("agent_unavailable") from None

    @staticmethod
    def _pcm_to_wav(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            with source.open("rb") as pcm:
                while chunk := pcm.read(64 * 1024):
                    wav.writeframesraw(chunk)

    @staticmethod
    def _validate_reply_wav(path: Path) -> None:
        try:
            with wave.open(str(path), "rb") as wav:
                if (
                    wav.getnchannels() != 1
                    or wav.getsampwidth() != 2
                    or wav.getframerate() != 24000
                ):
                    raise VoicePipelineError("tts_failed")
                expected = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
                actual = wav.getnframes() and path.stat().st_size - 44
                if expected <= 0 or actual != expected:
                    raise VoicePipelineError("tts_failed")
        except (OSError, wave.Error, EOFError):
            raise VoicePipelineError("tts_failed") from None
