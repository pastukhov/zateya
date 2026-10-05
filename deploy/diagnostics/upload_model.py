"""A small fluid model of the recorder's three upload buffers.

This bounds *buffering time*, not actual ESP32/TCP throughput. In particular,
the lwIP send buffer may become unavailable well before all nominal bytes can
be queued when RTT, segment limits, or WireGuard costs dominate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    seconds: float
    uplink_bytes_per_second: float
    capture: bool = True


@dataclass(frozen=True)
class Result:
    overflow_at_seconds: float | None
    captured_bytes: float
    transmitted_bytes: float
    ring_peak_bytes: float
    queue_peak_bytes: float
    socket_peak_bytes: float


def simulate(
    windows: list[Window], *, capture_bytes_per_second: float = 32000,
    ring_capacity: int = 32768, queue_capacity: int = 8192,
    socket_capacity: int = 5760, step_seconds: float = 0.01,
) -> Result:
    if min(capture_bytes_per_second, ring_capacity, queue_capacity,
           socket_capacity, step_seconds) <= 0:
        raise ValueError("all capacities and step size must be positive")
    if any(window.seconds < 0 or window.uplink_bytes_per_second < 0 for window in windows):
        raise ValueError("window duration and throughput cannot be negative")

    ring = queue = socket = captured = transmitted = elapsed = 0.0
    ring_peak = queue_peak = socket_peak = 0.0
    for window in windows:
        remaining = window.seconds
        while remaining > 1e-9:
            dt = min(step_seconds, remaining)
            # Acknowledged bytes free the modeled TCP send buffer first.
            delivered = min(socket, window.uplink_bytes_per_second * dt)
            socket -= delivered
            transmitted += delivered
            to_socket = min(queue, socket_capacity - socket)
            queue -= to_socket
            socket += to_socket
            to_queue = min(ring, queue_capacity - queue)
            ring -= to_queue
            queue += to_queue
            if window.capture:
                produced = capture_bytes_per_second * dt
                captured += produced
                if produced > ring_capacity - ring + 1e-9:
                    return Result(elapsed + dt, captured, transmitted,
                                  max(ring_peak, ring), max(queue_peak, queue),
                                  max(socket_peak, socket))
                ring += produced
            ring_peak = max(ring_peak, ring)
            queue_peak = max(queue_peak, queue)
            socket_peak = max(socket_peak, socket)
            elapsed += dt
            remaining -= dt
    return Result(None, captured, transmitted, ring_peak, queue_peak, socket_peak)


if __name__ == "__main__":
    for rate in (10000, 40000, 128000):
        result = simulate([Window(30, rate)])
        print(f"uplink={rate / 1000:.0f} KB/s overflow={result.overflow_at_seconds} "
              f"ring_peak={result.ring_peak_bytes:.0f} B sent={result.transmitted_bytes:.0f} B")
