# Powered wake-word dictation implementation plan

> **For agentic workers:** Use superpowers:executing-plans task-by-task. Track checks below.

**Goal:** Local «Затея» activation on external power, local «Слушаю», silence endpoint.
**Architecture:** One I2S reader feeds either detector or recording/VAD; pure policy owns timers; local cue is downloaded from a persistent server cache into device PSRAM. Existing button and backend remain compatible.
**Tech Stack:** ESP-IDF, C/C++, microWakeWord/TFLite Micro, WebRTC VAD, Python asset tooling.
**Spec:** ../specs/2026-10-15-zateya-wake-word-design.md

## Global constraints
- External power only for new wake activations; backend health 200 required.
- Pause default 3000 ms, configurable 1000–10000; no speech timeout 8000 ms.
- Cue «Слушаю» uses configured TTS voice, local PCM16 mono 24000 Hz; 150 ms echo discard.
- Playback/processing/setup/OTA inhibit detection; existing button behavior unchanged.
- Existing maximum recording limit applies independently of button duration.
- Model is part of signed image, maximum OTA slot 0x300000 bytes; cue updates independently.
- No idle microphone audio transmission or persistence; no secrets in assets or logs.

## Review focus
- Power loss during cue cancels safely; ongoing recording can finish (task 1).
- Timer wrap and changing VAD activity cannot cause premature endpoint (task 1).
- Invalid WAV, wrong rate and oversized cue are rejected (task 2).
- Missing or incompatible model leaves button operational (task 3).
- Playback echo, repeated activation and button-release events do not create new notes (task 4).

### Task 1: Pure wake session policy
Files: firmware/include/voice_wake_policy.h, firmware/src/voice_wake_policy.c,
firmware/test/test_voice_wake_policy/test_voice_wake_policy.c.
Interface: voice_wake_init, voice_wake_activate, voice_wake_cue_done,
voice_wake_tick; explicit OFF/ARMED/CUE/SETTLE/WAIT_SPEECH/RECORDING/DONE states.
Inputs: eligibility, monotonic uint32 milliseconds, speech flag, button finish,
maximum recording duration. Outputs: start cue, start record, finish, cancel.
- [x] Add failing tests for eligibility, cue/echo isolation, 3 s silence,
  8 s no-speech, manual finish, max duration, timer wrap and power loss.
- [x] Run `pio test -e native -f test_voice_wake_policy`: expect failure.
- [x] Implement policy without ESP dependencies; timers start after cue settling.
- [x] Run targeted and full native tests, commit and push.

### Task 2: Server-generated cue, device cache and playback
Files: backend/src/voice_gateway/tts and authenticated device API/tests,
deploy/firmware/prepare-listening-cue.py, deploy/firmware/test_listening_cue.py,
firmware/include/voice_listening_cue.h, firmware/src/voice_listening_cue.c,
new device cue cache module and tests, Compose persistent data configuration.
Interface: authenticated version manifest and PCM resource; firmware
voice_listening_cue_start/tick/cancel consumes a caller-owned PCM buffer.
- [x] Test PCM format, duration limit 5 s, truncation, empty input and hash.
- [x] Generate «Слушаю» using current server TTS configuration; cache persistently
  by text/model/voice/synthesis settings/format. Never expose secrets in metadata.
- [x] Generate once per version in background with single-flight; test restart
  reuse, config changes, concurrent requests and provider failures.
- [x] Serve manifest and bounded audio with existing device authentication;
  test unauthorized requests, missing cue and version consistency.
- [x] Download to PSRAM after connection; check versions at most once per minute
  while idle, verify complete content before atomic replacement. Retain prior
  valid cache on failure. Never free or replace a buffer while playback owns it.
- [ ] Gate wake activation on cue availability; keep button usable during cache
  loading/failure. No partition changes or persistent device cache in this version.
- [x] Pump bounded chunks and wait for speaker drain; no network at activation.
- [x] Test backend, cache and playback, build target, commit and push.

### Task 3: Model and VAD adapters
Files: firmware/src/voice_wake_detector.cpp, firmware/include/voice_wake_detector.h,
firmware/src/idf_component.yml, firmware/src/CMakeLists.txt,
firmware/assets/wake-model metadata and model, firmware/src/voice_vad.c.
Interface: detector_init/reset/feed16k/deinit, vad_feed16k/reset.
- [ ] Obtain exported TFLite and manifest for user job 1279; inspect license,
  operators, shapes and state contract; record SHA-256 and dependency versions.
- [ ] Validate incompatible/missing models fail closed without disabling button.
- [ ] Integrate compatible frontend, streaming inference and WebRTC VAD.
- [ ] Run positive/negative fixtures; measure RAM, inference time, image size.
- [ ] Commit and push only verified adapter; no fabricated model parameters.

### Task 4: Audio ownership, setup and application integration
Files: firmware/src/main.c, board_sticks3.c, audio_sticks3.c,
voice_settings*, voice_config_httpd.c, screen_ui*, diagnostics schema/tests.
- [ ] Test one-reader ownership and button/wake arbitration, max-duration,
  cue failure/echo, repeated events and power changes.
- [ ] Route idle frames to detector, cue frames to discard, recording frames
  to upload/VAD; defer upload until speech, using bounded pre-roll.
- [ ] Add persisted enable/pause controls, reset defaults, screen indication
  and non-sensitive diagnostics; update strict backend schema first.
- [ ] Run native, backend, UI and target build checks; commit and push.

### Task 5: Physical acceptance and OTA
- [ ] 18/20 detections at approximately 1 m; 30 minutes ambient with no false start.
- [ ] Verify «Слушаю», no echo in note, first words after cue, silence endpoint,
  button recording, unplug/sleep, voice reply, no idle clicks, busy inhibition.
- [ ] Publish signed candidate only after model/resources validation, verify OTA
  and rollback; update operations report with exact evidence and limitations.

## Execution record
User explicitly requested implementation in the current session. Proceed inline
with independent policy and cue tasks; model-dependent integration waits for
actual export. Task 1279 requires authentication; model not yet available here.

2026-10-15: User requested independent cue delivery because TTS voice is configured
on the server. Embedded cue packaging was dropped before deployment. Generated
sample and generic playback tests are preparation only; download/cache integration
is still pending. «Слушаю» remains the activation cue; this does not add a new
spoken «Готова» notification.

Implementation checkpoint (2026-10-15): server cache/API `2f65cd8`, device
PSRAM download/player `92d4a12`. Backend deployed, OTA 8 installed/confirmed,
real device cached 53760 bytes. 516 backend + 97 native + 3 converter tests pass.
Fresh reviewer found no critical/important issues. Worker hardware cancellation
and voice-change matrix remain to verify. Model job 1279 is 10% per user; tasks
3–5 requiring actual recognition remain pending. See operations/listening-cue.md.
Ruling: do not ship a fake detector or add new inference dependencies before
obtaining the actual model operator/state contract. Button behavior stays active.
