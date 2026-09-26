"""Configuration for a generic OpenAI-compatible Chat Completions endpoint."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit


class LLMConfigError(ValueError):
    """Invalid or incomplete LLM configuration."""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str = ""
    response_format: str = "text"
    timeout_seconds: float = 120.0
    max_tokens: int = 8192
    history_turns: int = 6
    history_max_chars: int = 12000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LLMConfig":
        source = os.environ if env is None else env
        raw_url = source.get("LLM_BASE_URL", "").strip()
        if not raw_url:
            raise LLMConfigError("LLM_BASE_URL is required")
        parts = urlsplit(raw_url)
        try:
            port = parts.port
        except ValueError:
            raise LLMConfigError("LLM_BASE_URL is invalid") from None
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or (":" in parts.netloc.rsplit("@", 1)[-1] and port is None)
        ):
            raise LLMConfigError("LLM_BASE_URL must be an http(s) URL without credentials, query, or fragment")
        model = source.get("LLM_MODEL", "").strip()
        if not model:
            raise LLMConfigError("LLM_MODEL is required")

        response_format = source.get("LLM_RESPONSE_FORMAT", "text").strip().lower()
        if response_format not in {"text", "json_object"}:
            raise LLMConfigError("LLM_RESPONSE_FORMAT must be text or json_object")
        try:
            timeout = float(source.get("LLM_TIMEOUT_SECONDS", "120"))
        except (TypeError, ValueError):
            raise LLMConfigError("LLM_TIMEOUT_SECONDS must be a number") from None
        if not 0 < timeout <= 120:
            raise LLMConfigError("LLM_TIMEOUT_SECONDS must be greater than 0 and at most 120")

        def positive_int(name: str, default: int, *, allow_zero: bool = False) -> int:
            raw = source.get(name, str(default)).strip()
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise LLMConfigError(f"{name} must be an integer") from None
            if value < (0 if allow_zero else 1):
                bound = "non-negative" if allow_zero else "positive"
                raise LLMConfigError(f"{name} must be {bound}")
            return value

        return cls(
            base_url=raw_url.rstrip("/"),
            model=model,
            api_key=source.get("LLM_API_KEY", "").strip(),
            response_format=response_format,
            timeout_seconds=timeout,
            max_tokens=positive_int("LLM_MAX_TOKENS", 8192),
            history_turns=positive_int("LLM_HISTORY_TURNS", 6, allow_zero=True),
            history_max_chars=positive_int("LLM_HISTORY_MAX_CHARS", 12000),
        )
