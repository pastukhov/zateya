"""Strict, secret-free schema for the device's numeric diagnostic snapshot."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


Counter = StrictInt


class RecordingDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_id: Counter = Field(ge=0, le=2**32 - 1)
    captured_bytes: Counter = Field(ge=0, le=2**32 - 1)
    queued_bytes: Counter = Field(ge=0, le=2**32 - 1)
    sent_bytes: Counter = Field(ge=0, le=2**32 - 1)
    ring_high_water_bytes: Counter = Field(ge=0, le=2**32 - 1)
    upload_high_water_bytes: Counter = Field(ge=0, le=2**32 - 1)
    write_max_ms: Counter = Field(ge=0, le=2**32 - 1)
    last_error_code: Counter = Field(ge=0, le=9)
    events: list[tuple[Counter, Counter, Counter, Counter]] = Field(max_length=64)

    @field_validator("events")
    @classmethod
    def validate_event_codes(cls, events):
        if any(code < 1 or code > 9 or min(uptime, arg0, arg1) < 0
               for uptime, code, arg0, arg1 in events):
            raise ValueError("invalid event")
        return events


class DeviceDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boot_id: Counter = Field(ge=0, le=2**32 - 1)
    sequence: Counter = Field(ge=1, le=2**32 - 1)
    uptime_ms: Counter = Field(ge=0)
    reset_reason: Counter = Field(ge=0, le=255)
    firmware_revision: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9 :._-]+$")
    wifi_connected: StrictBool
    wg_status: Literal[
        "disabled", "waiting_wifi", "waiting_time", "connecting", "connected", "error",
        "subnet_conflict", "paused_setup",
    ]
    backend_status: Counter = Field(ge=-1, le=599)
    free_heap_bytes: Counter = Field(ge=0, le=2**32 - 1)
    recording: RecordingDiagnostics
