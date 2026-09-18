"""Tests for the ACTIVE_REQUESTS gauge (ТЗ §34).

Two layers:

1. Unit level — the gauge lives on ``VoiceMetrics``, supports
   ``inc()``/``dec()``, and its value round-trips through a fresh
   ``CollectorRegistry`` exactly like the sibling ``voice_active_turns``
   gauge.

2. Integration level — a real ASGI request against the gateway app is
   driven in-process through httpx's ``ASGITransport`` (same style as
   ``test_app_stream.py``): the app's registry serves the gauge family on
   ``GET /metrics`` and the endpoint keeps answering 200. The per-request
   middleware that actually drives the gauge is a separate card, so these
   tests pin the *metric definition* contract, not the wrapping logic.
"""
from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from backend.src.voice_gateway.metrics import VoiceMetrics, init_metrics

# The integration tests below drive the real app. ``app`` pulls in modules
# (health, hermes/stage) that are not yet committed to this branch's base,
# so the app import can fail on a bare worktree of this task; skip the
# integration layer there rather than fail collection. Unit tests above are
# unaffected and pin the gauge contract either way.
try:
    from backend.src.voice_gateway.app import create_app
except ImportError:  # pragma: no cover - environment-dependent
    create_app = None


def _scrape(registry: CollectorRegistry) -> dict:
    """Prometheus text exposition → {metric_name: {label-frozenset: value}}."""
    out: dict = {}
    for fam in text_string_to_metric_families(
            generate_latest(registry).decode("utf-8")):
        for s in fam.samples:
            out.setdefault(s.name, {})[frozenset(s.labels.items())] = s.value
    return out


# ---------------------------------------------------------------------------
# 1. Unit: gauge definition + inc/dec on an isolated registry
# ---------------------------------------------------------------------------

def test_active_requests_gauge_defined_with_active_turns_pattern():
    """The gauge is a first-class member of VoiceMetrics, registered on the
    instance registry alongside the existing voice_active_turns gauge."""
    registry = CollectorRegistry()
    m = VoiceMetrics(registry)
    assert m.active_requests is not None
    # Same family name the /metrics endpoint will expose.
    samples = _scrape(registry)
    assert "ACTIVE_REQUESTS" in samples, sorted(samples)
    # Both gauges coexist in one registry without a collision error.
    assert "voice_active_turns" in samples


def test_active_requests_gauge_inc_dec():
    """inc() moves the gauge up, dec() brings it back — the inc/dec
    lifecycle the per-request middleware will rely on."""
    m = init_metrics(CollectorRegistry())
    m.active_requests.inc()
    m.active_requests.inc()
    assert _scrape(m.registry)["ACTIVE_REQUESTS"][frozenset()] == 2.0
    m.active_requests.dec()
    assert _scrape(m.registry)["ACTIVE_REQUESTS"][frozenset()] == 1.0
    m.active_requests.dec()
    assert _scrape(m.registry)["ACTIVE_REQUESTS"][frozenset()] == 0.0


def test_active_requests_gauge_independent_per_instance():
    """One inc/dec cycle on a fresh instance never leaks into a sibling
    instance's registry (same isolation guarantee as every other metric)."""
    a = init_metrics(CollectorRegistry())
    b = init_metrics(CollectorRegistry())
    a.active_requests.inc()
    assert _scrape(a.registry)["ACTIVE_REQUESTS"][frozenset()] == 1.0
    assert _scrape(b.registry)["ACTIVE_REQUESTS"][frozenset()] == 0.0
    a.active_requests.dec()
    assert _scrape(a.registry)["ACTIVE_REQUESTS"][frozenset()] == 0.0


# ---------------------------------------------------------------------------
# 2. Integration: gauge family is served by the app's /metrics endpoint
# ---------------------------------------------------------------------------

needs_app = pytest.mark.skipif(
    create_app is None,
    reason="app module not importable in this environment "
    "(untracked deps absent from branch base) — unit tests above still pin "
    "the gauge contract",
)


def _run(coro):
    return asyncio.run(coro)


@needs_app
def test_metrics_endpoint_serves_active_requests_family(tmp_path):
    """GET /metrics on the real app exposes the ACTIVE_REQUESTS gauge
    family in Prometheus text format, without breaking the endpoint."""
    app = create_app(archive_root=tmp_path / "archive")

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get("/metrics")

    resp = _run(run())
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")

    names = {
        s.name
        for fam in text_string_to_metric_families(resp.text)
        for s in fam.samples
    }
    assert "ACTIVE_REQUESTS" in names, sorted(names)


@needs_app
def test_turn_endpoint_still_works_with_gauge_present(tmp_path):
    """Regression guard: defining the new gauge must not break the
    streaming ingest endpoint (200 + X-Turn-Id, no STT wired)."""
    app = create_app(archive_root=tmp_path / "archive")
    pcm = b"\x00" * 4000

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/v1/voice/turn",
                content=pcm,
                headers={"X-Device-Id": "gauge-dev",
                         "X-Sample-Rate": "16000",
                         "X-Channels": "1"},
            )

    resp = _run(run())
    assert resp.status_code == 200
    turn_id = resp.headers.get("X-Turn-Id")
    assert turn_id and uuid.UUID(turn_id)
