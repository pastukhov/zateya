# Startup memory diagnosis and recovery plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Implementation is delegated to Sol; the parent independently reviews and tests, then commits/pushes and performs the agreed release.

**Goal:** Explain and eliminate the reproducible startup connectivity stall without losing settings or disabling OTA recovery.

**Architecture:** Establish the installed baseline, measure internal memory during startup, and run a single-variable comparison. Choose a production change only after the comparison identifies the cause.

**Tech Stack:** ESP32-S3, ESP-IDF/FreeRTOS, PlatformIO, USB serial, existing native tests.

**Spec/context:** `docs/operations/recorder-handoff-2026-11-05.md`, `docs/operations/startup-connectivity.md`, and the user's request to diagnose the two-minute startup delay. This is a staged investigation plan; the production implementation remains conditional on measured evidence.

## Evidence from the local USB restart

- IP obtained at 3075 ms.
- DNS failures at 10415, 54415, 76415, 98415 and 120415 ms; repeated `wifi:m f null` warnings.
- Local HTTP requests and ping failed while the router answered ping.
- A local HTTP receive error appeared at 123235 ms; this is evidence of activity, not a precise first-readiness measurement.
- TLS certificate validated at 136005 ms; gateway readiness HTTP 200 at 136415 ms.
- Diagnostics at uptime 136813 ms: backend 200, free heap 7692748 bytes, old build timestamp, no new readiness fields.
- Old source ends the OTA task after a 120-second readiness deadline; its requested stack is 16384 bytes. Termination was NOT explicitly logged on this device.
- Independent laptop HTTPS requests also timed out during this run. External connectivity may be a separate confounder and must be measured independently.
- LittleFS failed to mount; nonblank data was retained. Keep this as a separate finding rather than silently formatting it.

Primary hypothesis: startup internal-memory pressure prevents Wi-Fi traffic until a task releases memory. OTA stack lifetime is a candidate, not a proven allocation culprit. Total free heap including PSRAM cannot establish internal headroom. The exact installed release is still unidentified.

## Constraints and approach

- Preserve NVS, device token, Wi-Fi profiles, LittleFS, flash mode/frequency/size, partition layout and rollback capability.
- Keep TLS certificate verification, current voice/profile architecture, USB/idle OTA gates and late-connectivity retries.
- Do not install OTA30 merely to see whether it works: its persistent OTA task changes the suspected resource lifetime.
- Prefer measurement and a controlled comparison over an unmeasured stack reduction or simultaneous Wi-Fi/DNS changes.
- Raw logs and flash backups stay local with restrictive permissions; no secrets or user content in Git.

## Task 1: Baseline and recovery preparation

- [ ] Preserve the passive/startup logs and numeric diagnostic snapshot locally.
- [ ] Identify running image, OTA slot and partition table; save a full-flash backup before any diagnostic flash, verify size and SHA256. Read-only flash access may require a controlled bootloader entry after log capture.
- [ ] Match the image to release artifacts or recorded ELF/application hashes. Do not infer a release from a compile timestamp alone.
- [ ] Reproduce once more on the original image, recording local HTTP reachability, DNS and external HTTPS from the laptop separately from device serial events. Avoid a reset loop.

## Task 2: Diagnostic experiment (Sol implementation, parent verification)

Relevant files: `firmware/src/main.c`, `firmware/src/voice_ota_esp.c`, `firmware/src/voice_cue_cache_esp.c`, `firmware/src/voice_gateway_health.c`. Use an isolated diagnostic checkout matching the baseline; do not mix in unrelated main changes.

- [ ] Add bounded numeric serial sampling in an existing task, without a new large stack: free/minimum/largest internal 8-bit heap block, DMA-capable free heap, task creation results, and stack high-water marks. Sample startup stages and once per second through 150 seconds.
- [ ] Log OTA task creation and exit with uptime and internal heap; account for deferred stack reclamation by the idle task.
- [ ] Build the instrumented baseline and verify that the original stall remains reproducible. If instrumentation changes it, record that limitation and reduce overhead.
- [ ] Compare against the same build with only OTA task creation suppressed as a diagnostic switch. Preserve identical Wi-Fi/time/cue settings; no production release with OTA disabled.
- [ ] Confirm whether internal headroom and local connectivity recover when the allocation is removed. If not, inspect other startup allocations, including the 24576-byte cue worker stack, and repeat with only one variable changed.

## Task 3: Evidence-based correction and acceptance

- [ ] Record the confirmed allocation/lifetime cause, or the alternative cause if memory is disproven. Refine this plan with exact production changes and regression tests before implementation.
- [ ] If confirmed, reduce unnecessary simultaneous internal allocations or separate lightweight OTA scheduling from its heavy worker. Determine stack sizes from worst-path measurements, including TLS, signature checks, download/write and errors; do not blindly halve stacks or move flash-writing task stacks to PSRAM.
- [ ] Parent independently reviews the diff, runs relevant native tests and the StickS3 target build, and checks generated configuration.
- [ ] Hardware checks: at least five normal starts without the 120-second stall; local HTTP remains responsive; offline start followed by network recovery; idle OTA retry; recording/reply during background activity. Record actual readiness times and minimum internal heap, separately from host tests.
- [ ] Confirm adequate stack margin on exercised worst paths and no rollback/crash. Keep audio storage repair outside this change unless evidence makes it necessary.
- [ ] Commit/push verified task changes. Publish a signed production OTA only after physical acceptance, retaining rollback artifacts; independently verify signature/hash and installed release. Document code checks, deployment and device results separately.

## Review focus

The hardware matrix above must cover delayed network recovery, repeated OTA checks, concurrent voice activity, OTA download/write resource peaks, and persistent cue-store failure. Host tests alone cannot prove any of these memory or radio properties.
