"""Prometheus metrics for the voice gateway (ТЗ section 34).

The MVP exposes the minimal metric set from ТЗ §34 on ``GET /metrics``:

    voice_turns_total{status}
    voice_turn_duration_seconds
    voice_audio_duration_seconds
    voice_stt_duration_seconds
    voice_hermes_duration_seconds
    voice_tts_duration_seconds
    voice_notes_total{status}
    voice_active_turns

plus the per-request middleware series (ТЗ §34):

    voice_request_count_total{client_id,route,status}
    voice_request_latency_seconds{endpoint,status}
    voice_request_count_by_route_total{route}
    voice_active_requests

Label discipline (ТЗ §34): never put transcript, title, turn_id, error
messages or arbitrary text in labels — labels are bounded enums:
``status`` (HTTP status codes), ``route``/``endpoint`` (route templates),
and ``client_id`` (device id, bounded by the device fleet).

Every metric set is created per app instance (``init_metrics``) so tests can
use isolated registries and concurrent app instances never share counters.
"""
from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

SERVICE = "voice-gateway"

#: Histogram buckets for per-stage durations (seconds): 50 ms … 60 s.
_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


class VoiceMetrics:
    """One metric namespace for a single app instance."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry
        self.turns_total = Counter(
            "voice_turns_total",
            "Voice turns by terminal status.",
            ("status",),
            registry=registry,
        )
        self.notes_total = Counter(
            "voice_notes_total",
            "Notes written to the note storage by terminal status.",
            ("status",),
            registry=registry,
        )
        self.turn_duration = Histogram(
            "voice_turn_duration_seconds",
            "End-to-end voice turn duration.",
            registry=registry,
            buckets=_BUCKETS,
        )
        self.audio_duration = Histogram(
            "voice_audio_duration_seconds",
            "Duration of the recorded audio per turn.",
            registry=registry,
            buckets=_BUCKETS,
        )
        self.stt_duration = Histogram(
            "voice_stt_duration_seconds",
            "STT stage duration.",
            registry=registry,
            buckets=_BUCKETS,
        )
        self.hermes_duration = Histogram(
            "voice_hermes_duration_seconds",
            "Hermes (LLM) stage duration.",
            registry=registry,
            buckets=_BUCKETS,
        )
        self.tts_duration = Histogram(
            "voice_tts_duration_seconds",
            "TTS stage duration.",
            registry=registry,
            buckets=_BUCKETS,
        )
        self.active_turns = Gauge(
            "voice_active_turns",
            "Voice turns currently being processed.",
            registry=registry,
        )

        # ------------------------------------------------------------------
        # Per-request metrics (ТЗ §34): one namespace per app instance,
        # fed by the pure-ASGI metrics middleware (app.py).
        # ------------------------------------------------------------------
        self.request_count = Counter(
            "voice_request_count_total",
            "Total number of requests by client, route, and status.",
            ("client_id", "route", "status"),
            registry=registry,
        )
        self.request_count_by_route = Counter(
            "voice_request_count_by_route_total",
            "Total requests per route.",
            ("route",),
            registry=registry,
        )
        self.request_latency = Histogram(
            "voice_request_latency_seconds",
            "Request latency in seconds by endpoint and status.",
            ("endpoint", "status"),
            registry=registry,
            buckets=_BUCKETS,
        )
        self.active_requests = Gauge(
            "voice_active_requests",
            "Number of requests currently being processed.",
            registry=registry,
        )


#: Process-wide namespace used by the module-level ``app`` (production).
_DEFAULT: VoiceMetrics | None = None


def get_metrics() -> VoiceMetrics:
    """Return the process-wide metric namespace (created on first use)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = VoiceMetrics(CollectorRegistry())
    return _DEFAULT


def init_metrics(registry: CollectorRegistry | None = None) -> VoiceMetrics:
    """Create a fresh namespace on ``registry`` (or the default one)."""
    return VoiceMetrics(registry if registry is not None else CollectorRegistry())
