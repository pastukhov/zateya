"""Tests for the per-request metrics middleware (ТЗ §34).

Covers the acceptance criteria for the middleware card:

* ``voice_request_count_total{client_id,route,status}``` increments once
  per request with the right labels (device id from ``X-Device-Id`` with
  the default fallback, route *template* — never the raw path);
* ``voice_request_latency_seconds{endpoint,status}``` observes the
  request duration;
* ``voice_active_requests`` increments on request start and is back to 0
  after completion — including the streaming ``voice_turn`` endpoint, the
  502 failure path, and 404s;
* ``voice_request_count_by_route_total{route}``` increments per route;
* ``GET /metrics`` still serves Prometheus exposition with the new
  series present.

Same harness as ``test_app_stream.py``: in-process ASGI app through
``httpx.ASGITransport`` on a fresh event loop per test, isolated metric
namespace per app instance (``init_metrics`` per ``create_app``).
"""
import asyncio
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI

from backend.src.voice_gateway.app import DEFAULT_DEVICE_ID, create_app
from backend.src.voice_gateway.hermes.base import HermesClient
from backend.src.voice_gateway.hermes.fake import FakeHermes
from backend.src.voice_gateway.models import Transcript
from backend.src.voice_gateway.stt.fake import FakeSTT

_VALID_HERMES_RAW = (
    '{"reply": "Готово.", "note": {"create": false, "title": "", '
    '"content": "", "tags": []}}'
)


def _make_app(tmp_path: Path,
              hermes: HermesClient | None = None) -> FastAPI:
    return create_app(
        archive_root=tmp_path / "archive",
        stt=FakeSTT(Transcript(text="тестовая расшифровка", language="ru")),
        hermes=hermes if hermes is not None else FakeHermes(_VALID_HERMES_RAW),
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://test")


def _run(loop: asyncio.AbstractEventLoop, coro):
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _gauge_value(metrics, name: str) -> float:
    """Read a (label-less) gauge's current value from its registry."""
    for metric in metrics.registry.collect():
        for sample in metric.samples:
            if sample.name == name and not sample.labels:
                return sample.value
    raise AssertionError(f"metric {name} not found in registry")


def _series_value(metrics, name: str, labels: dict) -> float:
    """Read one labelled counter/histogram sample by its FULL sample name
    (e.g. ``voice_request_count_total`` or
    ``voice_request_latency_seconds_count``).

    ``name`` is the exposition sample name, not the bare metric name — the
    ``_total``/``_count``/``_sum`` suffix belongs to the sample. A label
    combination that was never incremented is absent from the registry and
    reads as ``0.0`` (Prometheus: an unobserved counter is zero).
    """
    for metric in metrics.registry.collect():
        for sample in metric.samples:
            if sample.name == name and all(
                    sample.labels.get(k) == v for k, v in labels.items()):
                return sample.value
    return 0.0


def _pcm(seconds: float = 0.25, rate: int = 16000, channels: int = 1) -> bytes:
    return b"\x00" * int(seconds * rate * channels * 2)


def test_request_count_labels_on_health(tmp_path: Path) -> None:
    """REQUEST_COUNT increments once per request with client_id/route/status."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics

    async def run() -> int:
        async with _client(app) as client:
            resp = await client.get("/health")
            return resp.status_code

    status = _run(asyncio.new_event_loop(), run())
    assert status == 200
    assert _series_value(
        metrics, "voice_request_count_total",
        {"client_id": DEFAULT_DEVICE_ID, "route": "/health",
         "status": "200"}) == 1.0
    # no other label combination was created for /health
    assert _series_value(
        metrics, "voice_request_count_total",
        {"client_id": "other", "route": "/health", "status": "200"}) == 0.0


def test_request_count_client_id_from_header(tmp_path: Path) -> None:
    """client_id label comes from X-Device-Id when present."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics

    async def run() -> int:
        async with _client(app) as client:
            resp = await client.get("/health",
                                    headers={"X-Device-Id": "atom-x-77"})
            return resp.status_code

    status = _run(asyncio.new_event_loop(), run())
    assert status == 200
    assert _series_value(
        metrics, "voice_request_count_total",
        {"client_id": "atom-x-77", "route": "/health",
         "status": "200"}) == 1.0


def test_request_count_by_route(tmp_path: Path) -> None:
    """REQUEST_COUNT_BY_ROUTE increments per route template."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics

    async def run() -> None:
        async with _client(app) as client:
            await client.get("/health")
            await client.get("/health")
            await client.get("/metrics")

    _run(asyncio.new_event_loop(), run())
    assert _series_value(metrics, "voice_request_count_by_route_total",
                         {"route": "/health"}) == 2.0
    assert _series_value(metrics, "voice_request_count_by_route_total",
                         {"route": "/metrics"}) == 1.0


def test_request_latency_observed(tmp_path: Path) -> None:
    """REQUEST_LATENCY histogram observes the request duration."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics

    async def run() -> None:
        async with _client(app) as client:
            await client.get("/health")

    _run(asyncio.new_event_loop(), run())
    count = _series_value(
        metrics, "voice_request_latency_seconds_count",
        {"endpoint": "/health", "status": "200"})
    assert count == 1.0
    total = _series_value(
        metrics, "voice_request_latency_seconds_sum",
        {"endpoint": "/health", "status": "200"})
    assert total > 0.0


def test_active_requests_gauge_returns_to_zero(tmp_path: Path) -> None:
    """ACTIVE_REQUESTS increments on start, decrements on end — no leak."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics

    async def run() -> int:
        async with _client(app) as client:
            await client.get("/health")
            await client.get("/metrics")
            await client.post("/api/v1/voice/turn", content=_pcm(),
                              headers={"X-Device-Id": "dev-g"})
            return 0

    _run(asyncio.new_event_loop(), run())
    assert _gauge_value(metrics, "voice_active_requests") == 0.0


def test_active_requests_gauge_during_request(tmp_path: Path) -> None:
    """The gauge is 1 while a request is in flight (streaming turn)."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics
    seen: dict[str, float] = {}

    async def run() -> None:
        async def slow_body():
            # Keep the turn request in flight long enough for the probe
            # to read the gauge while the request is still active.
            for _ in range(0, 2000, 128):
                yield b"\x00" * 128
            await asyncio.sleep(0.3)

        async with _client(app) as client:
            probe = asyncio.create_task(client.get("/health"))
            await asyncio.sleep(0.15)  # let the probe's request start
            turn = asyncio.create_task(client.post(
                "/api/v1/voice/turn", content=slow_body(),
                headers={"X-Device-Id": "dev-g",
                         "X-Sample-Rate": "16000",
                         "X-Channels": "1"}))
            await asyncio.sleep(0.2)
            seen["during"] = _gauge_value(metrics, "voice_active_requests")
            await asyncio.sleep(0.6)
            await probe
            await turn
        seen["after"] = _gauge_value(metrics, "voice_active_requests")

    _run(asyncio.new_event_loop(), run())
    assert seen["during"] >= 1.0, "gauge must be >= 1 while in flight"
    assert seen["after"] == 0.0


def test_voice_turn_success_records_all_series(tmp_path: Path) -> None:
    """The streaming endpoint (voice_turn) is fully metered on success."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics
    pcm = _pcm(0.5)

    async def run() -> int:
        async with _client(app) as client:
            resp = await client.post(
                "/api/v1/voice/turn", content=pcm,
                headers={"X-Device-Id": "test-device",
                         "X-Sample-Rate": "16000", "X-Channels": "1"})
            return resp.status_code

    status = _run(asyncio.new_event_loop(), run())
    assert status == 200
    route = "/api/v1/voice/turn"
    assert _series_value(
        metrics, "voice_request_count_total",
        {"client_id": "test-device", "route": route, "status": "200"}) == 1.0
    assert _series_value(metrics, "voice_request_count_by_route_total",
                         {"route": route}) == 1.0
    assert _series_value(
        metrics, "voice_request_latency_seconds_count",
        {"endpoint": route, "status": "200"}) == 1.0
    assert _gauge_value(metrics, "voice_active_requests") == 0.0


def test_voice_turn_failure_path_records_502(tmp_path: Path) -> None:
    """A failed turn (empty body → 502 audio_invalid) is metered too,
    with the failure status — and the gauge still returns to zero."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics
    route = "/api/v1/voice/turn"

    async def run() -> int:
        async with _client(app) as client:
            resp = await client.post(route, content=b"",
                                     headers={"X-Device-Id": "test-device"})
            return resp.status_code

    status = _run(asyncio.new_event_loop(), run())
    assert status == 502
    assert _series_value(
        metrics, "voice_request_count_total",
        {"client_id": "test-device", "route": route,
         "status": "502"}) == 1.0
    assert _series_value(metrics, "voice_request_count_by_route_total",
                         {"route": route}) == 1.0
    assert _series_value(
        metrics, "voice_request_latency_seconds_count",
        {"endpoint": route, "status": "502"}) == 1.0
    assert _gauge_value(metrics, "voice_active_requests") == 0.0


def test_404_is_metered_with_unknown_route(tmp_path: Path) -> None:
    """Unmatched paths are metered with the bounded ``unknown`` route
    label (ТЗ §34: labels stay bounded, never raw paths)."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics

    async def run() -> int:
        async with _client(app) as client:
            resp = await client.get("/no-such-path")
            return resp.status_code

    status = _run(asyncio.new_event_loop(), run())
    assert status == 404
    assert _series_value(
        metrics, "voice_request_count_total",
        {"client_id": DEFAULT_DEVICE_ID, "route": "unknown",
         "status": "404"}) == 1.0
    assert _series_value(metrics, "voice_request_count_by_route_total",
                         {"route": "unknown"}) == 1.0
    assert _gauge_value(metrics, "voice_active_requests") == 0.0


def test_metrics_endpoint_serves_new_series(tmp_path: Path) -> None:
    """/metrics still serves Prometheus exposition — and the new
    per-request series are present in it after some traffic."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics

    async def run() -> str:
        async with _client(app) as client:
            await client.get("/health")
            resp = await client.get("/metrics")
            assert resp.status_code == 200
            assert "text/plain" in resp.headers.get("content-type", "")
            return resp.text

    body = _run(asyncio.new_event_loop(), run())
    assert "# HELP voice_request_count_total" in body
    assert "# HELP voice_request_latency_seconds" in body
    assert "# HELP voice_request_count_by_route_total" in body
    assert "# HELP voice_active_requests" in body
    # The /health request issued above is already in the exposition.
    assert 'voice_request_count_total{client_id="atom-echo-01",' in body
    assert 'route="/health",' in body
    # And the pre-existing MVP series are still there (nothing broke).
    assert "# HELP voice_turns_total" in body
    assert "# HELP voice_active_turns" in body


def test_concurrent_requests_gauge_tracks(tmp_path: Path) -> None:
    """Concurrent requests: the gauge reflects the number in flight and
    lands back at zero; each request is counted exactly once."""
    app = _make_app(tmp_path)
    metrics = app.state.metrics

    async def run() -> None:
        async with _client(app) as client:
            async def hit(i: int) -> None:
                await client.get("/health")
            await asyncio.gather(*(hit(i) for i in range(5)))

    _run(asyncio.new_event_loop(), run())
    assert _series_value(metrics, "voice_request_count_by_route_total",
                         {"route": "/health"}) == 5.0
    assert _gauge_value(metrics, "voice_active_requests") == 0.0


def test_metrics_are_per_app_instance(tmp_path: Path) -> None:
    """Two apps = two isolated namespaces (ТЗ §34: per-instance registry):
    traffic on one app never pollutes the other's metrics."""
    app_a = _make_app(tmp_path / "a")
    app_b = _make_app(tmp_path / "b")
    assert app_a.state.metrics is not app_b.state.metrics

    async def run() -> None:
        async with _client(app_a) as client:
            await client.get("/health")

    _run(asyncio.new_event_loop(), run())
    assert _series_value(
        app_a.state.metrics, "voice_request_count_by_route_total",
        {"route": "/health"}) == 1.0
    assert _series_value(
        app_b.state.metrics, "voice_request_count_by_route_total",
        {"route": "/health"}) == 0.0
