# Recorder state feedback implementation plan

**Goal:** Make the recorder usable without watching its screen: every user-visible
state change has a short audible acknowledgement, including errors with working
network. Preserve server-delivered speech and local offline fallback.

**Incident:** Latest stored failed turn 39d862cf-c4fa-48e9-8f18-e94a163fb8a8
(2026-11-04 17:49 UTC) failed with agent_timeout. Diagnostics sent/captured/queued
all 730880 bytes, network healthy, error 09. This is model timeout, not upload
loss. Existing ERROR branch only speaks when offline. Diagnostic firmware date
is a translation-unit compile date, potentially stale in incremental builds; it
does not establish the installed OTA version. Publication also does not prove
installation. Audio (730880-byte PCM and WAV) and transcript are present in archive.

**Design:** Extend existing authenticated server cue catalog and bounded PSRAM
cache. Do not embed speech in firmware. Drive a small testable feedback policy
from actual state/stage changes; repeated polls do not repeat cues. All playback
runs on the main audio owner. Error preempts pending routine cues and waits for
safe speaker ownership. No speech during microphone capture, no overlapping
answer/cues, no network fetch in the transition path. Distinct local fallback
patterns distinguish error, ready/completion, and progress before cache loads.

State coverage: boot/ready, pre-record listening (existing shared button/wake/
follow-up path), recording acknowledgement without microphone contamination,
upload/processing, backend transcribing/thinking/synthesizing when observed,
answer playback start, successful completion/idle, cancellation, error/recovery.
Use concise Russian phrases; completion says "Готово", never "Сохранено" unless
backend actually confirmed save. Errors should differentiate known timeout,
recognition, synthesis and connection failures if protocol supplies evidence;
unknown errors always get a generic failure cue. Do not claim recording was saved
locally. Preserve the server error code in bounded parsing for classification.
Rapid intermediate stages may coalesce to the newest stage, never drop terminal
error. A completion cue must not delay/obscure automatic follow-up listening.

## Implementation (Sol)

- [x] Add focused failing tests for state-to-cue coverage, duplicate suppression,
  error priority, fallback distinction and cancellation/follow-up interaction.
- [x] Extend `backend/src/voice_gateway/cues/cache.py` catalog and its tests;
  extend firmware cue names/cache and fixed nginx routes if required.
- [x] Add pure feedback policy and integrate `firmware/src/main.c`, stage/error
  transport in voice_turn client/HTTP code as needed. Preserve existing button
  modes, cancellation, OTA gate, microphone settle and audio leases.
- [x] Test invalid/unknown server error fields, cold-cache/offline failure,
  repeated stage polls, fast transitions and resource release. Native tests must
  test policy; explicitly identify ESP-only integration not exercised by native.
- [x] Document phrases/state coverage, observed incident and verification limits.

## Parent verification and release

- [x] Independently review speaker/microphone ownership, error queue, OTA lease,
  cancellation and all transition paths. Run backend/deploy suite, native tests
  and StickS3 build. Verify raw audio/transcript from incident remain archived.
- [ ] Commit/push scoped changes. Deploy backend/catalog first; verify every cue
  manifest/PCM over HTTPS with auth, correct format/hash and cold fallback.
- [ ] Build/sign/publish next OTA using existing key and rollback policy. Preserve
  old backend image. Never conflate publication with device installation.
- [ ] Inspect accessible device diagnostics/version; physical listening and real
  error acknowledgement remain explicit acceptance if no device access exists.

User confirmed the device is currently unavailable for USB/physical testing.

## Independent verification

Parent full backend/deploy suite: 594 passed; full native firmware suite:
113 passed; StickS3 target build successful (35.98 seconds). A separate native
harness fed the incident failed/agent_timeout JSON through metadata parser,
voice-turn client and feedback policy; it produced the queued timeout cue.

Review required and verified corrections for ready-cue lease transfer, local
cancellation after a READY worker ended, initial boot lease adoption (including
resumed turn), and clearing prior error classification before VAD/capture.
Final read-only review found no further confirmed integration defects. These
checks do not execute physical I2S playback or prove installed firmware.
