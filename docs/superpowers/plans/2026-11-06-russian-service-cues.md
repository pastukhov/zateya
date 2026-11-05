# Russian service cue language implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan. Parent reviews, tests, commits/pushes and releases per AGENTS.md; do not ask for already granted authorization.

**Goal:** Eliminate audible English accent in Russian service cues while retaining a female voice; assess pronunciation by listening.

**Architecture:** Add an optional language code to the existing TTS profile. For ElevenLabs send it through RouterAI provider options. The language becomes part of cached generation identity; preserve old identities when unset and retain old profiles for devices during migration. No firmware or codec change.

**Tech Stack:** Python, httpx, pytest, Docker Compose, existing MP3 generation/firmware cache.

**Spec:** User reports English accent specifically in service cues; existing female voice requirement and docs/superpowers/plans/2026-11-04-end-to-end-mp3.md remain in force.

## Evidence and constraints

- User confirmed production31 service cues and answer audible, then reported accent in service cues.
- Production MP3 model elevenlabs/eleven-flash-v2.5, voice OZ0L6eISlOejga3XjDFt (Talia), no language parameter.
- RouterAI docs ignore top-level instructions/prompt. On 2026-11-06 controlled request with provider.options.elevenlabs.language_code=not-a-language returned400 language_code unsupported; same request with ru returned200 audio/mpeg,17597bytes SHA e3cc1cffa6fad4e3a1a96415748fcbc9e0f75569691c578528dcf830478c677d. Thus the option is effective, but pronunciation is not yet accepted.
- Talia+ru retained the accent; user singled out «Готово». Marina+Flash+ru removed accent but user rejected unclear phrases and wrong stress in «не дождалась». User suggested changing generation mode. Marina+Multilingual v2, without language override, was accepted on four separately generated cues («Готово», «Не дождалась ответа», «Готова к записи», «Обрабатываю»): «Да, так хорошо». This explicitly supersedes original Talia/Flash selection; female voice, cue text, provider MP3 bytes and device24kHz playback remain. Both service cues and replies use the same selected profile, as communicated before selection. No server transcoding in delivery, no generic arbitrary provider JSON config.
- Do not overwrite old generation or activate incomplete audio sets. No firmware flash, reset or storage erase needed.

## Review focus

1. Empty new setting must leave old request and cache identity unchanged.
2. Historical profile JSON without new field must still resolve.
3. MP3 language must not inherit legacy language or alter legacy routing.
4. Invalid configuration must fail clearly; no silently ignored language for unsupported provider models.
5. Failed generation must preserve previous active set; acceptance of language is distinct from human accent assessment.

## Task 1: Language profile and transport (Sol)

Files: backend/src/voice_gateway/tts/config.py, openai_compatible.py, their tests; backend/src/voice_gateway/cues/cache.py, generation.py and tests; docker-compose.yml, .env.example; docs/operations/mp3-replies.md.

- [x] Write and run failing tests for optional TTSConfig.language_code default empty; env TTS_LANGUAGE_CODE and isolated MP3_TTS_LANGUAGE_CODE; strip/lower valid two-letter ISO syntax; reject malformed nonempty values and non-ElevenLabs model with language set.
- [x] Add language_code at end of dataclass to retain positional compatibility. Request emits provider.options.elevenlabs.language_code only when nonempty; existing instructions behavior remains for compatibility. Unset leaves payload exactly unchanged.
- [x] Add regression tests: existing no-language generation identity unchanged; ru identity differs; load/resolve historical profile lacking language; ru retained profile reconstructs language; legacy cache hash changes only when language nonempty. Keep api_key excluded.
- [x] Wire both environment settings in compose/example docs, empty defaults. Document RouterAI-specific mapping and Russian MP3 setting; no secrets.
- [x] Run focused TTS, cue and deploy tests. Report exact changes/results, do not commit or deploy (parent owns them per AGENTS).

## Task 2: Parent review, verification and release

- [x] Review changes independently, run affected tests and broader backend/deploy checks with ffmpeg available.
- [x] Prepare isolated ru samples for listening, compare to currently cached cues. Same-voice Talia trial was rejected; include «Готово» in the Russian female voice trial. Do not assert accent fixed from decoding/transcription.
- [x] Commit/push verified code. Apply exact patch on server's divergent history, build unique image from verified current immutable base with changed runtime modules; no background latest-tag race.
- [x] Set MP3_TTS_MODEL=elevenlabs/eleven-multilingual-v2 and MP3_TTS_VOICE=ymDCYd8puC7gYjxIamPt; leave MP3_TTS_LANGUAGE_CODE empty to preserve the accepted request exactly; recreate backend with explicit image, verify actual image, healthy status and complete new generation. Old profiles retained, no pending jobs interrupted.
- [x] Verify device activation/download from server logs or diagnostics; ask for physical service-cue listening. Separate code/tests/deployment/device acceptance in report.
- [x] Update handoff with production31 audibility acceptance and accent status, commit/push docs.

## Verification checkpoint

Sol implemented optional language support, parent reviewed all changed runtime and test files. Twenty new cases failed first; focused111 passed. Parent full backend/deploy run:901 passed, one unrelated nginx proxy integration check failed502. Re-running the same proxy checks with explicit mock-backend readiness passed; original test waits for proxy404 but not backend readiness. No proxy production/test changes made. Code575ac10 committed/pushed; server patch applied as98481b9, isolated runtime image b1618d7b80db0b26a40bcab50ef11555fd51815d5ecbc1857d0c64e1390b73bb built on77f0d642. Language support is optional and not the selected pronunciation remedy.

Prepared approved-profile generation667fadd41d6bcc9b1f53492c9b09bef723090eb64cdbe63a709c44c2ee6728cf contains14 MP3/336219bytes. It reuses the exact four accepted clips; remaining ten generated in the same mode. Isolated generation builder ran network-disabled with a provider that raises on synthesis, proving no regeneration of those bytes. Full-set physical acceptance remains separate from the four-clip listening test.

## Release and physical result

Selected-profile runtime passed341 TTS/cue tests in the isolated Python3.12 image.
Backend deployed healthy at b1618d7b80db0b26a40bcab50ef11555fd51815d5ecbc1857d0c64e1390b73bb.
External14 MP3 hashes/decode verified. Recorder downloaded14 and reported the
new generation on successful job5944555a-5d9c-4797-9e92-3625e0b30f73. No reset.
User accepted pronunciation on-device: «Реплики хорошие, без акцента», but reports
interference and will supply a recording. This is a separate unfinished playback
diagnosis; keep accepted voice/model fixed. See operations/russian-service-cues-2026-11-06.md.
