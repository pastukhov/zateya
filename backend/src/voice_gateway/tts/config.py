"""TTS stage configuration (ТЗ sections 28, 29, 31, 33).

Deliberately separate from :mod:`voice_gateway.config` (no shared Settings
module — ТЗ section 51: keep each stage's config self-contained so
concurrent work on sibling stages does not collide).

Environment variables (secrets stay out of the repo — ТЗ section 33):

    LLM_BASE_URL   required, shared OpenAI-compatible endpoint root
    TTS_MODEL      required, model name
    TTS_VOICE      voice name
    TTS_INSTRUCTIONS  optional speaking style for models that support it
    TTS_RESPONSE_FORMAT  wav or pcm (PCM16 little-endian, 24 kHz mono)
    TTS_TIMEOUT    seconds; default 60 (ТЗ section 31)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

#: Default TTS timeout, seconds (ТЗ section 31: recommended TTS: 60 s).
DEFAULT_TTS_TIMEOUT = 60.0


@dataclass(frozen=True)
class TTSConfig:
    """Immutable OpenAI-compatible TTS endpoint settings (ТЗ section 33).

    ``base_url`` is the full TTS endpoint URL derived from ``LLM_BASE_URL``.
    """

    base_url: str
    model: str
    voice: str = ""
    instructions: str = ""
    api_key: str = ""
    timeout: float = DEFAULT_TTS_TIMEOUT
    response_format: str = "wav"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "TTSConfig":
        """Build config from an explicit environment mapping.

        Unlike the other stage configs, this does NOT fall back to
        ``os.environ`` implicitly — callers (production wiring or tests)
        must pass the mapping explicitly (ТЗ section 33: no hidden env
        access in production code paths for this stage).
        """
        source: Mapping[str, str] = env if env is not None else {}
        llm_base_url = source.get("LLM_BASE_URL", "").strip()
        if not llm_base_url:
            raise ValueError("LLM_BASE_URL is required")
        base_url = llm_base_url.rstrip("/") + "/audio/speech"
        model = source.get("TTS_MODEL", "").strip()
        if not model:
            raise ValueError("TTS_MODEL is required")
        response_format = source.get("TTS_RESPONSE_FORMAT", "wav").strip().lower()
        if response_format not in {"wav", "pcm"}:
            raise ValueError("TTS_RESPONSE_FORMAT must be wav or pcm")
        voice = source.get("TTS_VOICE", "")
        instructions = source.get("TTS_INSTRUCTIONS", "")
        api_key = source.get("LLM_API_KEY", "").strip()
        raw_timeout = source.get("TTS_TIMEOUT") or DEFAULT_TTS_TIMEOUT
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("TTS_TIMEOUT must be a number") from exc
        if timeout <= 0:
            raise ValueError("TTS_TIMEOUT must be positive")
        return cls(
            base_url=base_url,
            model=model,
            voice=voice,
            instructions=instructions,
            api_key=api_key,
            timeout=timeout,
            response_format=response_format,
        )
