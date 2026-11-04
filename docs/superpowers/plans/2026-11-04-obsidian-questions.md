# Questions over Obsidian implementation plan

**Goal:** Answer natural spoken questions using existing Obsidian notes, support
follow-up questions, and retain inspectable sources without creating question pages.

**Architecture:** Keep the existing speech pipeline and model-based operation
selection. Add a separate bounded read-only retrieval context over the configured
vault; preserve managed-write context and its restrictions. Validate structured
answer citations against actual retrieved text, archive them alongside the answer,
and expose them through an authenticated answer endpoint linked from ready status.
The existing firmware status buffer is only 768 bytes: never inline citations.
Store original speech before
model calls, but defer publishing source Markdown until a mutating note operation.

**User-approved scope:** Questions and follow-ups; concise spoken answers, source
links in history, clarification when ambiguous, explicit missing/conflicting data.
No deterministic spoken commands. Existing note organization continues working.
Sol implements; parent independently reviews and tests, then commits/pushes and
deploys the backend. No firmware change is expected.

## Boundaries and decisions

- Read Markdown throughout the configured vault, including ordinary manually
  written notes. Never follow symlinks or read outside it; exclude hidden paths,
  `.git`, `.obsidian`, `.trash`, `.sync`, attachments and binary/non-UTF8 files.
- Use a bounded local full-text retrieval implementation with Russian word-form
  normalization, title/alias/body weighting and useful passages from long notes.
  No new vector service or external embedding provider for this first release.
- Explicit current-question matches outrank an unrelated active topic. Include
  prior question/source context for “а какой из них…”; do not use a command list
  or deterministic question/statement classifier. The LLM selects the operation.
- Retrieval context is read-only: retrieved ordinary notes never become writer
  targets. Preserve the existing write allowlist, optimistic checks and journal.
- Input/transcripts remain durable in the archive/state DB before remote calls.
  Query must not create source, idea, wiki or plan pages in Obsidian. Later note
  creation may explicitly materialize its referenced original evidence safely.
- Answer fields carry bounded status and citations (vault-relative path, title,
  exact short quote; backend supplies canonical link/hash). Validate paths and
  quotes against text actually supplied, reject invented citations. No raw paths
  or source markup need be spoken. Found answers need valid supporting citations;
  unsupported answers fall back to an honest safe response, not invented facts.
- Real-model review found repeated spelling changes in copied quotes. Supply
  bounded exact quote candidates with opaque citation IDs; prefer model selection
  of these IDs and resolve text/path/hash on the backend. Unknown IDs are invalid;
  retain strict validation for the compatible raw path/quote form. A single shared
  format/semantic repair attempt is allowed before a safe unsupported response.
- Note contents are untrusted evidence. Instructions inside retrieved notes must
  not override the task, trigger writes or change authentication behavior.
- Bound scan/files/characters/results and expose truncation/coverage honestly.
  A limited search cannot prove information is absent from the entire vault.
- Persist retrieved context/decision for idempotent retries. Keep dialogue/history
  per context/device, survive restart, and clear follow-up retrieval on reset.

## Task 1 — Retrieval independent of writer context

- [x] Add `knowledge/retrieval.py` and focused tests for manual notes outside
  `Затея/`, Unicode/Russian forms, aliases, long-note passages, topic comparison,
  unrelated active topic, no match, explicit topic switch and follow-up references.
- [x] Enforce safe traversal, size/count/time/context bounds; tests cover symlink
  escape, hidden paths, malformed text, stale/deleted files and truncated results.
- [x] Integrate `retrieved_pages`/search metadata separately from writable `pages`.
  Select relevant adjacent/topic-linked notes when budget allows; preserve stable
  vault-relative identities and hashes for citation verification.

## Task 2 — Grounded answer contract and history

- [x] Add a backward-compatible optional answer contract to HermesResponse and
  AgentReply; propagate through direct LLM result caching and TextTurnResult.
- [x] Extend prompts with found/not-found/ambiguous/conflicting behavior and concise
  voice replies; current retrieved evidence outranks remembered assistant claims.
- [x] Validate structured citations and exact quotes before returning an answer;
  persist `answer.json` and answer metadata without having pipeline overwrite it.
- [x] Expose bounded answer citations at `/api/voice/turns/{id}/answer`, with a
  compact `answer_url` in ready status; extend the fixed nginx allowlist. Test
  maximum status payload including follow-up stays below 768 UTF-8 bytes.
  verify another device cannot access them and old clients remain compatible.
- [x] Keep scoped follow-up context durable and resettable. Re-read referenced
  notes for new questions; retries reuse their original captured context.

## Task 3 — Questions do not publish Obsidian pages

- [x] Add deferred source materialization to KnowledgeStore/TextTurnProcessor.
  Persist raw evidence first with conflict detection and original metadata intact.
- [x] Query publication validates intent and returns a receipt without Markdown
  writes. Mutating operations materialize current/referenced sources safely,
  including a clarification question later answered as a new note.
- [x] Test query/no-result/clarification/retry/restart leave all vault Markdown
  hashes unchanged; capture/amend/organization and raw-evidence recovery still pass.
- [x] Preserve graceful handling of failed model/TTS and Git refresh without
  inventing a saved-note claim or discarding the recording.

## Task 4 — Independent verification and rollout

- [x] Parent reviews retrieval boundaries, writer separation, citation validation,
  context isolation and retry behavior. Run full backend/deploy tests; run native
  protocol tests if an additive status payload affects firmware parsing.
- [x] Real configured-model replay in a temporary vault: January trip alternatives,
  Yunnan decision, Raja Ampat uncertainties, follow-up diving comparison, absent
  facts, conflicting notes, malicious note instructions, then a new dictated note.
  Assert correct operation, real citations and no query-created Markdown.
- [ ] Document API/operations, search limits and verification evidence. Commit/push
  scoped changes and deploy backend with a rollback image retained.
- [ ] Verify health plus authenticated result metadata; distinguish server/model
  verification from actual microphone/playback verification on the recorder.

## Verification before rollout (2026-11-04)

Sol implemented; parent reviewed and required fixes for immutable input retries,
768-byte firmware status compatibility, intent-preserving format repair, and
citation deduplication across ref/legacy forms. Full backend/deploy suite:
**594 passed** (97 existing framework warnings). Existing C status and follow-up
parsers compiled with warnings as errors and accepted the additive answer URL.

Configured-model replay used isolated fixtures: alternatives, reasons, open
questions, follow-up, missing fact, conflicting dates, topic switch, untrusted
instructions and subsequent capture. Questions left Markdown unchanged. The
conflict response correctly stated both dates and cited both notes, but selected
`found` instead of `conflicting`; the prompt was clarified, and model status
classification remains a quality limitation, not a deterministic guarantee.

A separate copy of the real vault (102 Markdown files) returned the January 2027
travel alternatives and an unresolved route question with two verified citations.
All copied Markdown hashes stayed unchanged. First attempt hit the configured
model timeout; a fresh attempt succeeded. Retrieval reported truncation honestly.
No live vault mutation or physical microphone/playback test was performed.
