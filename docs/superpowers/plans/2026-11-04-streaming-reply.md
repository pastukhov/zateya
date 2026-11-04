# Early WAV Reply Implementation Plan

**Goal:** Start recorder playback from validated TTS bytes before upstream EOF.
**Architecture:** Incrementally normalize finite WAV into a growing canonical
file; advertise availability independently of terminal job status and serve it
without proxy buffering. Updated firmware downloads once and waits for final
status before follow-up listening. Raw/unknown-length inputs retain fallback.
**Tech Stack:** Python/httpx/FastAPI, nginx, ESP-IDF C.
**Spec:** docs/superpowers/specs/2026-11-04-streaming-reply.md

## Global constraints
- No dynamic Opus, no unrelated DMA changes, no provider/model change.
- Only validated 24 kHz mono PCM16 data may be published early; no metadata.
- Ready remains terminal validated success; old clients retain existing behavior.
- Authentication and device ownership apply to partial files too.
- No replay after partial playback failure, no follow-up on failed synthesis.
- Bounded resource use; cancellation/restart cannot publish stale partial audio.

## Review focus
- Chunk boundaries inside RIFF headers, metadata padding and odd PCM splits.
- Provider truncation/error after audible PCM and after declared data end.
- Cancellation, disconnect and restart while the file is growing.
- Terminal ready/follow-up races and old firmware compatibility.
- Actual early first bytes through HTTP/proxy rather than buffered test clients.

## Task 1: Incremental provider normalization and publication (Sol)
Files: tts/openai_compatible.py, tts/wav.py or focused new streaming helper,
pipeline.py and corresponding TTS/pipeline tests.
- [x] Add failing delayed-upstream tests proving first normalized PCM before EOF,
  plus finite metadata exclusion, fragmented headers, truncation, cancellation,
  bounded size, and unchanged raw/unknown-length fallback.
- [x] Implement streaming httpx reads, canonical finite WAV output with flushed
  PCM, and safe availability metadata. Preserve usage accounting and final
  archive validation; cleanup partial state on every terminal failure.
- [x] Run targeted tests; document the interface consumed by Task 2.

## Task 2: Early authenticated delivery and firmware consumption (Sol)
Files: jobs/api.py, jobs worker/store only as needed, app.py if needed,
firmware/include/voice_turn_client.h, firmware/src/voice_turn_client.c,
firmware/src/voice_turn_http.c, firmware protocol JSON parser, main.c only as
needed, deploy/alice.nginx.conf.template; corresponding API/native/proxy tests.
- [x] Add tests for separate audio availability, old clients, ownership,
  cancellation/error on growing streams, terminal confirmation and follow-up,
  no second download after early consumption, and no prefix replay on failure.
- [x] Serve authenticated growing canonical WAV using opt-in stream query with
  buffering disabled and bounded reads. Keep ready-only legacy behavior.
- [x] Firmware parses availability, downloads once, then polls terminal result;
  ensure HTTP completion and parser success do not mask backend failure.
- [ ] Run targeted backend and native tests; build StickS3 firmware. (Final parent rerun after review fixes.)

## Task 3: Independent review, verification and release (parent)
- [ ] Review full diff and have independent reviewer inspect completion,
  cancellation, partial-file authorization and PCM boundaries.
- [ ] Run full backend/deploy suite, native firmware suite and target build.
- [ ] Exercise real TCP streaming with delayed upstream, not only TestClient.
- [ ] Commit/push scoped changes. Preserve rollback backend image; deploy backend
  and proxy. Verify public authenticated streaming and existing clients.
- [ ] Publish signed firmware using established OTA process only after checks;
  verify manifest/image signatures and installed diagnostics if available.
- [ ] Record live timing and clearly distinguish device installation from user
  confirmation of audible playback and cancellation.

## Execution notes
User already authorized implementation and established Sol execution with parent
verification. Continue without repeated design permission. Source workspace is
shared with the established Sol agent; preserve unrelated untracked user files.

Implementation contract and limitations: [streaming reply operations](../../operations/streaming-reply.md). Parent initial checks: backend633/native122 passed; latest cancellation/MIME regressions and target build receive final parent verification before release.
