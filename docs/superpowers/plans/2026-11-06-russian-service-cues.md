# Russian service cue language implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan. Parent reviews, tests, commits/pushes and releases per AGENTS.md; do not ask for already granted authorization.

**Goal:** Explicitly synthesize Russian service cues with the existing female Talia voice and assess accent by listening.

**Architecture:** Add an optional language code to the existing TTS profile. For ElevenLabs send it through RouterAI provider options. The language becomes part of cached generation identity; preserve old identities when unset and retain old profiles for devices during migration. No firmware or codec change.

**Tech Stack:** Python, httpx, pytest, Docker Compose, existing MP3 generation/firmware cache.

**Spec:** User reports English accent specifically in service cues; existing female voice requirement and docs/superpowers/plans/2026-11-04-end-to-end-mp3.md remain in force.

## Evidence and constraints

- User confirmed production31 service cues and answer audible, then reported accent in service cues.
- Production MP3 model elevenlabs/eleven-flash-v2.5, voice OZ0L6eISlOejga3XjDFt (Talia), no language parameter.
- RouterAI docs ignore top-level instructions/prompt. On 2026-11-06 controlled request with provider.options.elevenlabs.language_code=not-a-language returned400 language_code unsupported; same request with ru returned200 audio/mpeg,17597bytes SHA e3cc1cffa6fad4e3a1a96415748fcbc9e0f75569691c578528dcf830478c677d. Thus the option is effective, but pronunciation is not yet accepted.
- Keep female Talia, Eleven Flash2.5, cue text, provider MP3 bytes and device24kHz playback. No server transcoding in delivery, no generic arbitrary provider JSON config.
- Do not overwrite old generation or activate incomplete audio sets. No firmware flash, reset or storage erase needed.

## Review focus

1. Empty new setting must leave old request and cache identity unchanged.
2. Historical profile JSON without new field must still resolve.
3. MP3 language must not inherit legacy language or alter legacy routing.
4. Invalid configuration must fail clearly; no silently ignored language for unsupported provider models.
5. Failed generation must preserve previous active set; acceptance of language is distinct from human accent assessment.

## Task 1: Language profile and transport (Sol)

Files: backend/src/voice_gateway/tts/config.py, openai_compatible.py, their tests; backend/src/voice_gateway/cues/cache.py, generation.py and tests; docker-compose.yml, .env.example; docs/operations/mp3-replies.md.

- [ ] Write and run failing tests for optional TTSConfig.language_code default empty; env TTS_LANGUAGE_CODE and isolated MP3_TTS_LANGUAGE_CODE; strip/lower valid two-letter ISO syntax; reject malformed nonempty values and non-ElevenLabs model with language set.
- [ ] Add language_code at end of dataclass to retain positional compatibility. Request emits provider.options.elevenlabs.language_code only when nonempty; existing instructions behavior remains for compatibility. Unset leaves payload exactly unchanged.
- [ ] Add regression tests: existing no-language generation identity unchanged; ru identity differs; load/resolve historical profile lacking language; ru retained profile reconstructs language; legacy cache hash changes only when language nonempty. Keep api_key excluded.
- [ ] Wire both environment settings in compose/example docs, empty defaults. Document RouterAI-specific mapping and Russian MP3 setting; no secrets.
- [ ] Run focused TTS, cue and deploy tests. Report exact changes/results, do not commit or deploy (parent owns them per AGENTS).

## Task 2: Parent review, verification and release

- [ ] Review changes independently, run affected tests and broader backend/deploy checks with ffmpeg available.
- [ ] Prepare isolated same-voice ru samples for listening, compare to currently cached cues. Do not assert accent fixed from decoding/transcription.
- [ ] Commit/push verified code. Apply exact patch on server's divergent history, build unique image from verified current immutable base with changed runtime modules; no background latest-tag race.
- [ ] Set only MP3_TTS_LANGUAGE_CODE=ru once samples are accepted; recreate backend with explicit image, verify actual image, healthy status and complete new generation. Old profiles retained, no pending jobs interrupted.
- [ ] Verify device activation/download from server logs or diagnostics; ask for physical service-cue listening. Separate code/tests/deployment/device acceptance in report.
- [ ] Update handoff with production31 audibility acceptance and accent status, commit/push docs.
