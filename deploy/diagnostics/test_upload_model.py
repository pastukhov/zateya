import pytest

from deploy.diagnostics.upload_model import Window, simulate


def test_sustained_10_kilobytes_per_second_fills_finite_buffers():
    result = simulate([Window(10, 10000)])
    assert result.overflow_at_seconds is not None
    assert 1.8 < result.overflow_at_seconds < 2.5
    assert 15000 < result.transmitted_bytes < 30000


def test_short_stall_recovers_when_average_rate_exceeds_capture():
    result = simulate([Window(1, 0), Window(5, 40000), Window(3, 40000, capture=False)])
    assert result.overflow_at_seconds is None
    assert result.transmitted_bytes == result.captured_bytes


def test_fast_uplink_does_not_overflow_with_nominal_pcm():
    result = simulate([Window(30, 128000)])
    assert result.overflow_at_seconds is None
    assert result.captured_bytes == pytest.approx(960000)
