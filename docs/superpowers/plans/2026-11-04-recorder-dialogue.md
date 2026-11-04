# Recorder dialogue and local voice cues implementation plan

> **For agentic workers:** Use superpowers:executing-plans and regression tests task-by-task.

**Goal:** Let users dictate freely, hear model clarifying questions, and answer hands-free, with single-click recording and immediate local spoken cues.

**Architecture:** Model supplies an explicit clarification object tied to preserved source evidence. Backend persists pending clarification and exposes opt-in follow-up metadata through the durable turn protocol. Firmware uses one tested capture policy for button, wake-word and follow-up: local cue completes, speaker drains and settles, microphone records, next press/silence/limit ends. Static cues persist on device independently of network; dynamic questions use existing TTS.

**Tech Stack:** Existing Python/FastAPI/Pydantic/SQLite and ESP-IDF C/PlatformIO native tests, StickS3 OTA layout unchanged.

**Spec:** User's accepted conversation in this task: single press starts; next press or 3-second speech pause stops; after clarification auto-listen; play local rendered voice before every dictation, preferably existing voice's “Слушаю”; static “Обрабатываю” and “Нет связи”; 10-second initial answer wait. User explicitly authorizes planning and delegation to Sol. No command vocabulary required.

## Constraints

- Never expose credentials or overwrite provisioning/NVS/partition layout. Preserve existing wake-word, OTA gates, cancellation, diagnostics, 512 KiB upload buffering and idle power behavior.
- Existing clients/proposals remain compatible: absent clarification/follow-up fields mean no automatic listening.
- “Сохранила” only after confirmed publication, never a speculative local cue.
- No microphone capture of speaker cue/question. Wake-word monitoring is not a new dictation and must not repeat cues continuously.
- Raw recordings remain saved even if user declines/ignores question or TTS/publication fails.
- Executor does not access production, flash hardware or publish OTA; primary agent reviews and handles deployment/release.
- Preserve unrelated untracked get_ya_id.py and image; commit/push only task changes after passing checks. If sandbox blocks approvals, report to primary immediately rather than waiting on escalation.

## Review focus

- First button release must not end new toggle recording; quick double tap, held button and stale edges must be deterministic.
- No replay-triggered auto-listen after reboot/retry; follow-up belongs to the actually played question and is consumed once.
- Silence before speech is cancellation/idle after 10s, not empty STT upload; speech pause is 3s after speech with pre-roll preserving first syllable.
- No recording during cue/question playback; drain + settle and failures release all audio/OTA resources.
- Durable unanswered question must not trap new-topic dictation or interpret every “да” as an unrelated note; expiry and supersession explicit.

## Task 1: Clarification semantics and durable state

Files: models/hermes_response.py, agents/prompts.py, text_turns.py, knowledge store/context or a focused dialogue module; matching tests.

- [ ] Add failing tests for free-form ambiguity → model question → answer “да” bound to original source, restart, decline, unrelated topic and expired pending question.
- [ ] Add optional typed clarification {question, source_ids}; source references must be visible to model and exist. Model can ask only one concise meaningful question, not infer follow-up from '?' in reply.
- [ ] Persist pending clarification keyed by context identity, stable question ID and originating turn/source; return it in context even if no idea was published. Keep user evidence and pending status separate from claimed publication.
- [ ] Model decides answer vs topic change; introduce explicit validated resolution/supersession referencing pending ID, no keyword command parser. Safe default keeps unresolved evidence.
- [ ] Explicit 15-minute conversational expiry (implementation choice, configurable/testable); expiry prevents automatic binding but never deletes source. Cap automatic consecutive clarification listens at 3; next question may be answered via button.
- [ ] Record question only with consistent user-visible result; expose no auto-listen until successful question TTS. Test TTS failure, retry idempotency and context isolation.

## Task 2: Compatible turn protocol

Files: pipeline.py, jobs/store.py, jobs/api.py, firmware voice_turn_client/http and headers, protocol documentation/tests.

- [ ] Extend durable ready response with optional follow_up {question_id, listen:true} and upload association for answer_to. Validate matching context/question and stale IDs safely; absent association still permits model contextual reasoning.
- [ ] Persist metadata so polling retries return same intent. Old clients ignore extras and old responses decode with false default. Bounded IDs, malformed JSON and duplicate poll tested.
- [ ] Firmware carries follow-up intent through playback, consumes once after successful drain, never on partial/error/cancelled playback or recovered old turn after boot. Include capability compatibility as needed.
- [ ] Verify source/job outcome vs TTS result separation and cancellation behavior.

## Task 3: Shared recording policy

Files: firmware/src/main.c, button_driver.c only if needed, voice_wake_policy.c or new focused voice_capture_policy.c/.h, native test files.

- [ ] Test state machine independent of ESP hardware: manual press, release ignored, next press finish, 3s silence after speech, 10s no-speech wait, maximum duration independent of holding button, timer wraparound, cancellation.
- [ ] Route manual start, wake activation and question-follow-up through common cue/drain/150ms-settle/wait-speech/record/finish lifecycle. Explicitly avoid wake-word detector remaining active during session.
- [ ] Reuse VAD/pre-roll to avoid missing speech onset; no empty upload if no speech. Show clear waiting/recording states. If VAD unavailable, report recoverable failure rather than recording indefinitely.
- [ ] Reset button edge handling at transitions so ending/cancelling a question or error does not accidentally restart.
- [ ] Integrate OTA/power/network/audio locks; manual/new follow-up cannot overlap upload, playback, cache replacement or update.

## Task 4: Persistent static spoken cues

Files: cues/cache.py, firmware voice_cue_cache*, voice_listening_cue*, asset/build tooling and tests.

- [ ] Inspect existing cache transport and extend to named listening/processing/offline assets. Choose embedded flash assets or atomic persistent filesystem slots compatible with existing partitions; no new partition layout. RAM cache alone is insufficient.
- [ ] Provide render/import tool for fixed phrases using configured TTS voice, strict PCM metadata (24kHz mono PCM16), SHA/length caps. Never commit keys. Parent can render real assets after source review if executor lacks provider access.
- [ ] Play “Слушаю” before EVERY dictation start. “Обрабатываю” after recording closes/processing starts. “Нет связи” on known transport unavailability, not generic model or TTS errors.
- [ ] Missing/corrupt asset must fail safely with defined built-in short signal/UI fallback; preserve prior valid asset on interrupted update. Offline cue must work with network disconnected after reboot.
- [ ] Native tests validate cue selection, repeated playback, audio ownership, bad assets and interruption; actual audio must be generated and inspected before release, not left as placeholder.

## Task 5: End-to-end validation and release handoff

- [ ] Backend sequence test: ambiguous dictation, spoken question, automatic answer, saved corrected note; unrelated reply, timeout, second clarification, max chain, retry, restart, old firmware compatibility.
- [ ] Firmware native suite + target StickS3 build. Parent runs escalation-required commands; do not block awaiting approval.
- [ ] Isolated real-model replay validates meaningful question and answer linkage; no production notes altered. Include structured report rather than trusting reply text.
- [ ] Document protocol and operations, changed button semantics, timings, unanswered-question behavior, cue provenance and remaining physical checks.
- [ ] Run pytest -q backend/src deploy/test_prepare_data.py; firmware pio test -e native; pio run -e sticks3; git diff --check. Scoped commit/push (primary handles if .git read-only).

## Primary-agent acceptance and deployment

Independently review/test implementation, real-provider isolated conversation and rendered cue audio properties. Deploy backend compatibly, build/publish firmware only after target success and correct release manifest. Preserve rollback/previous image. Installation success is not physical verification: require actual single press/release, silence, auto-answer, no self-recording, offline cue after reboot and recovery checks on StickS3. Report any unavailable physical validation explicitly; do not claim completion of hardware behavior from unit tests/build/OTA alone.
