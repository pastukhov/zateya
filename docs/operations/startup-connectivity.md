# Delayed recorder connectivity, 2026-11-05

The user reported “Server: no connection”, then confirmed that it recovered.
The external readiness endpoint returned HTTP 200 in 0.659 seconds; both
backend and proxy were running, and the backend was healthy. The latest device
report had backend status 200, uptime 132562 ms, and the older build timestamp
`Nov 4 2026 22:15:10`. Two recent voice jobs completed successfully. The stale
last-error code 9 was restored from storage and had no current recording events;
it is not evidence of a current network failure.

The exact cause of this boot's delay remains unconfirmed without device phase
telemetry. Source inspection did identify two related defects:

- Firmware configured two SNTP hosts but compiled only one server slot, so the
  fallback was silently ignored. Time synchronization also started before DHCP.
- OTA stopped permanently after a 120-second startup readiness window. A later
  successful connection could therefore leave the recorder on old firmware.

The fix enables two SNTP slots with a compile-time guard, starts synchronization
from the health task after DHCP, preserves normal resynchronization when RTC
already has valid time, and bounds failed synchronization retries to one minute.
While awaiting time, the screen uses the existing pending state rather than
reporting an HTTP failure. Certificate and hostname verification remain enabled.

OTA now keeps checking: one minute after a transient failure, five minutes after
a successful check or no-update response. USB power, idle, storage ownership,
signature verification and rollback requirements remain unchanged.

Optional `wifi_ready_ms`, `tls_ready_ms` and `backend_ready_ms` report the first
readiness time observed since boot. Zero means not observed; absent fields mean
older firmware. `tls_ready_ms` means the clock is valid for TLS certificate
checks, not that a TLS handshake completed. These timestamps survive per-turn
diagnostic resets and contain no network credentials or note contents.

Validation: 141 native tests and 6 backend/diagnostic tests passed. Device
installation and actual startup latency remain separate physical checks.
