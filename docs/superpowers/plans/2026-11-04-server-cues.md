# Server-delivered recorder cues implementation plan

**Goal:** Restore the agreed independent server delivery of spoken recorder cues;
do not embed speech audio in firmware.

**Architecture:** Extend the existing authenticated CueCache and PSRAM loader to
`listening`, `processing`, and `offline`. Server TTS configuration determines the
voice. The server persistently caches generated PCM; the recorder downloads and
validates it in idle time and plays an acquired local buffer without a request at
activation. A small generated tone remains available when a cue is unavailable.

**Specification:** User request of 4 November and the existing agreement in
`2026-10-15-zateya-wake-word.md` (independent cue updates, PSRAM cache).
Implementation is delegated to Sol; the parent independently reviews, tests,
commits/pushes and deploys backend before compatible firmware.

## Constraints and review focus

- Preserve existing `/api/device/cues/listening` and audio URLs for old firmware.
- Speech PCM must not be embedded by CMake/PlatformIO or generated into C arrays.
- Keep current button modes, clarification auto-listen, cue/drain/150 ms settle,
  recording and OTA ownership behavior.
- PCM16 LE mono 24 kHz, at most 240000 bytes per cue; validate size and SHA256.
- Never send bearer credentials to a redirect or arbitrary manifest URL.
- Retain a good cached cue after refresh failure; do not free an acquired buffer.
- A missing or failing cue must not starve the other two or block button capture.
- Restore existing bounded idle/background refresh. Allow initial download on
  battery as well as USB so button feedback is available on mobile use; rate-limit
  retries and stop downloads when a voice turn or OTA starts.
- PSRAM cache survives network loss but not power-off. No partition changes or
  large NVS blobs; document fallback tone before first download after reboot.
- Generation must not run in request handlers. Keep secret-free config identity
  and persistent cache reuse. Do not claim “saved” through a static cue.

## Task 1 — Server cue catalog

- [x] Add failing tests in `backend/src/voice_gateway/cues/test_cache.py` for three
  independent cues, legacy URL, unknown name, auth, persistent reuse, config voice
  change, corrupt PCM, and one provider failure not blocking remaining cues.
- [x] Extend `cues/cache.py` with the fixed allowlist/text catalog and per-cue
  manifests; share the existing bounded synthesis/validation implementation.
- [x] Keep startup/shutdown safe around the shared TTS provider in `app.py`.
  Use sequential synthesis if provider concurrency is not guaranteed.
- [x] Run targeted backend tests and verify requests never trigger synthesis.

## Task 2 — Recorder cache and playback ownership

- [x] Add failing native tests for independent slots, invalid indexes/metadata,
  acquired-buffer publication rejection, missing cue fallback and cancellation.
- [x] Extend `voice_cue_cache.{h,c}` and `voice_cue_cache_esp.c` to three bounded
  slots with per-cue acquisition/release and independent refresh state.
- [x] Wire `main.c` startup, idle gating, listening and feedback paths to acquire
  downloaded PCM, releasing on completion, cancellation, start failure and error.
  Account for worker/playback races; no I2S access from downloader.
- [x] Retain a small tone for unavailable speech. Remove static speech lookups,
  embedded assets, generated CRC manifest and their build/import-only machinery.
  Keep or replace meaningful tests; do not leave a second unused delivery path.
- [x] Run native tests and build StickS3; inspect ELF symbols/image to ensure no
  embedded speech payload remains. Compare final signed image with release 22.

## Task 3 — Verification and rollout

- [x] Update `docs/operations/listening-cue.md`, `recorder-dialogue.md`, protocol
  and wake-word docs where their current behavior would otherwise be misleading.
- [x] Parent independently reviews backend compatibility and every acquire/release
  path; run full relevant backend, native, UI and release tests and target build.
- [x] Commit/push only task changes. Deploy backend with previous image retained.
- [x] Verify all three manifests/audio on the actual authenticated server,
  including hashes, no-token rejection and existing listening URL compatibility.
- [x] Build/sign the next OTA from isolated committed sources; verify signature,
  hash, slot size and reduced image size, then publish public artifacts only.
- [ ] Complete physical verification (publication is confirmed; installation is not): cold boot download,
  subsequent offline playback, tone before initial download, abort while fetching,
  voice change without firmware rebuild, button modes and clarification response.
