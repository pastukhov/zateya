from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CallContext:
    turn_id: str
    channel: str
    stage: str
    model: str


@dataclass(frozen=True, slots=True)
class UsageObservation:
    input_tokens: int | None = None
    output_tokens: int | None = None
    audio_seconds: Decimal | None = None
    text_characters: int | None = None
    reported_amount: Decimal | None = None
    reported_currency: str | None = None


@dataclass(frozen=True, slots=True)
class Cost:
    amount: Decimal | None
    currency: str | None
    kind: str
