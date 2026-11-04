# Startup connectivity and missed OTA recovery

Evidence: external HTTPS returns 200 and the backend is healthy. The latest
recorder diagnostic reports backend status 200 at uptime 132562 ms, with an
earlier November 4 build. Two recent voice jobs completed successfully. The
user confirmed that connectivity returned. No serial port is attached, so the
exact Wi-Fi, DNS, time synchronization or TLS delay for this boot is unknown.

Two defects are confirmed in source: `voice_tls.c` configures two SNTP servers,
but the compiled `CONFIG_LWIP_SNTP_MAX_SERVERS=1` silently ignores the fallback.
SNTP starts before DHCP. The OTA task exits after 120 seconds without
connectivity and never retries during that boot.

Implementation is delegated to Sol; the parent reviews, tests and releases.

1. Enable two SNTP servers in reproducible defaults. Start synchronization after
   actual network acquisition, with bounded retries. Preserve certificate
   verification; do not set time from unauthenticated HTTP.
2. Distinguish waiting for time from failed HTTP health checks. Probe promptly
   when network and time become ready, retaining bounded request timeouts.
3. Retry OTA checks after late connectivity and transient manifest failures.
   Preserve idle, USB power, rollback and storage ownership gates; bound polling
   and download retries.
4. Add optional first-readiness timestamps for Wi-Fi, TLS and backend to numeric
   diagnostics, compatible with older firmware. This makes the next delay
   attributable instead of inferring its cause from one final snapshot.
5. Test startup before network, late readiness, reconnect and retry cadence.
   Validate compiled SNTP configuration, native tests and the target build.
6. Commit and push, publish signed OTA 29, and verify its signature and image
   through external HTTPS. Installation, startup latency and sound acceptance
   remain separate physical checks.
