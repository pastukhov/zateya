"""Configuration for the Alice adapter (plan task 4).

Only Alice-specific settings live here; LLM/STT/TTS config is reused from
the existing gateway. Database paths are derived from ``ARCHIVE_ROOT`` so
all persistent data stays next to the Compose file in ``data/`` (plan
global constraint).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class AliceConfigError(Exception):
    """Raised when ALICE_ENABLED=true but required settings are missing."""


@dataclass(frozen=True, slots=True)
class AliceConfig:
    enabled: bool
    skill_id: str
    allowed_yandex_id: str
    context_device_id: str
    database: Path
    archive_root: Path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AliceConfig":
        values = os.environ if env is None else env
        enabled = values.get("ALICE_ENABLED", "false").strip().lower() == "true"
        if not enabled:
            return cls(enabled=False, skill_id="", allowed_yandex_id="", context_device_id="",
                       database=Path("data/archive/alice.sqlite3"),
                       archive_root=Path("data/archive"))
        skill_id = values.get("ALICE_SKILL_ID", "").strip()
        allowed = values.get("ALICE_ALLOWED_YANDEX_ID", "").strip()
        context_device_id = values.get("ALICE_CONTEXT_DEVICE_ID", "").strip()
        missing = [name for name, value in (
            ("ALICE_SKILL_ID", skill_id),
            ("ALICE_ALLOWED_YANDEX_ID", allowed),
            ("ALICE_CONTEXT_DEVICE_ID", context_device_id),
        ) if not value]
        if missing:
            raise AliceConfigError("missing required settings: " + ", ".join(missing))
        archive_root = Path(values.get("ARCHIVE_ROOT", "archive"))
        return cls(
            enabled=True,
            skill_id=skill_id,
            allowed_yandex_id=allowed,
            context_device_id=context_device_id,
            database=archive_root / "alice.sqlite3",
            archive_root=archive_root,
        )
