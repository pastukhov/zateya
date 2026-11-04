# Free-form thought organization implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task with regression tests.

**Goal:** Preserve meaning and thematic continuity across free-form dictations without requiring command vocabulary.

**Architecture:** The model proposes semantic organization, while the backend validates and journals durable topic membership and bounded contextual state. Immutable dictations are evidence; wiki pages are navigable views, not the only memory. Recent inputs survive publication failures. No keyword command router.

**Tech Stack:** Existing Python/FastAPI, Pydantic, SQLite, Markdown and Git publisher.

**Spec:** User-approved conversational direction in this task: model acts as editor, organizes and revises thoughts; executor is Sol, primary agent independently verifies. This document captures implementation decisions; user explicitly requested execution after planning.

## Constraints

- Preserve existing vault, source files, manual edits, request idempotency and crash recovery.
- No secret/session resets, silent provider fallback, destructive migrations or autonomous deployment by executor.
- Old proposals and existing notes remain compatible. Existing restored travel category is wiki/concepts/travel-january-2027.md; import its membership without rewriting unrelated content.
- Distinguish model inference from user-confirmed facts. Keep uncertain route names uncertain.
- Unknown category or ambiguous continuation must remain visible as unresolved, not silently misfiled.
- Only task changes committed/pushed after passing tests; production verification belongs to primary agent.

## Review focus

- Topic switches must not drag new thoughts into an old active topic.
- Pending/rejected publication and TTS failure must not erase conversational evidence.
- Restart, retries and concurrent dictations must not duplicate topics or memberships.
- Model corrections must not silently overwrite manual edits or sources.
- Fake-model tests prove mechanics only; real-model replay separately assesses semantics.

## Task 1: Durable organization contract and writer

Files: knowledge/models.py, knowledge/store.py, knowledge/test_store.py; extract focused organization module if needed.

- [ ] Add failing tests for optional model-proposed topic creation/selection, note membership and topic switching, old proposal compatibility, unknown references and duplicate retry.
- [ ] Introduce optional structured organization proposal: stable topic reference (existing wiki path), optional new topic title/path, and explicit membership. Model chooses semantics; backend must not classify by trigger phrases. Topic creation is possible without manufacturing an ordinary idea for the category declaration.
- [ ] Persist topic state separately from latest idea. Journal state changes together with note publication so recovery cannot advance state without committed content. Ensure rename/reclassification is limited to referenced context with expected hashes.
- [ ] Maintain category member links programmatically in a bounded managed section while preserving user prose; preserve page-specific tags instead of replacing wiki tags with incoming note tags. Supply deterministic receipt naming actual saved topic.
- [ ] Recognize existing category metadata and restored travel category without destructive migration.
- [ ] Verify focused tests, full relevant suite, commit and push.

## Task 2: Context that survives partial failure

Files: knowledge/store.py, text_turns.py, agents/sessions.py as needed, matching tests.

- [ ] Reproduce missing prior dictation after rejected publication; test isolation between context identities, bounded history, restart and retry.
- [ ] Store bounded recent source evidence independently of successful LLM/publication history, with source IDs and publication state. Do not masquerade uncommitted assistant replies as confirmed facts.
- [ ] Include a compact topic catalog, active topic, current member notes and recent raw dictations in model context. Enforce limits (e.g. 8 recent sources, 12000 chars raw evidence, existing overall context budget); expose truncation.
- [ ] Preserve state when unrelated query occurs; topic switch comes from model proposal, not forced sticky routing. Pending items remain observable/recoverable.
- [ ] Test, commit and push.

## Task 3: Editor prompting and correction safeguards

Files: agents/prompts.py, agents/test_openai_client.py, test_text_turns.py and knowledge tests.

- [ ] Update prompt for free-form topic discovery, continuation vs amendment vs alternative, later clarification of earlier uncertainty, and topic changes. No prescribed user commands.
- [ ] Require evidence references for retrospective corrections; preserve original text and explain inferred vs confirmed interpretation. Never invent Sichuan as an extra destination from a garbled place name.
- [ ] Avoid copying full frontmatter/sources into page bodies. Clarify material ambiguity briefly; otherwise organize without unnecessary questions.
- [ ] Voice receipt reflects committed membership or unresolved status; TTS failure never changes publication outcome.
- [ ] Test persistence and validation paths, not exact prompt wording. Commit and push after checks.

## Task 4: Sequence replay and handoff

Files: backend sequence tests and a documented opt-in replay tool in tools/ with README and smoke test if a new tool is added; docs/operations as appropriate.

- [ ] Synthetic regression sequence: travel topic January 2027, Raja Ampat variant, Yunnan/Hainan variant, restart, correction, unrelated firmware topic, return to travel. Assert both variants share topic, firmware untouched, source evidence retained and no invented destinations.
- [ ] Include initial garbled 'выпуск в январе' and subsequent clarification. A safe clarification/pending result is valid before enough evidence; invented release facts are not.
- [ ] Cover publication rejection, TTS failure, retries, manual edit conflict and cross-context isolation.
- [ ] Provide opt-in real-provider replay against an isolated temporary vault, never production notes. Report semantic pass/fail separately from deterministic test results. Do not expose credentials.
- [ ] Run pytest -q backend/src deploy/test_prepare_data.py and git diff --check. Report commit IDs, design choices, residual limitations and exact replay command.

## Primary-agent acceptance

Independently review diff and state/journal ordering; run tests; replay free-form scenarios with real configured model in isolated vault; inspect resulting links and provenance. Return failures to Sol. Only deploy reviewed changes, preserve previous image, verify health and existing travel data; distinguish server replay from physical dictation validation.
