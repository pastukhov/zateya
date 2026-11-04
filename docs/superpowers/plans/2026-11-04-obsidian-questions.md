# Questions over Obsidian implementation plan

**Goal:** Answer natural spoken questions using existing Obsidian notes, support
follow-up questions, and retain inspectable sources without creating question pages.

**Architecture:** Keep the existing speech pipeline and model-based operation
selection. Add a separate bounded read-only retrieval context over the configured
vault; preserve managed-write context and its restrictions. Validate structured
answer citations against actual retrieved text, archive them alongside the answer,
and expose them in the authenticated ready result. Store original speech before
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
- Note contents are untrusted evidence. Instructions inside retrieved notes must
  not override the task, trigger writes or change authentication behavior.
- Bound scan/files/characters/results and expose truncation/coverage honestly.
  A limited search cannot prove information is absent from the entire vault.
- Persist retrieved context/decision for idempotent retries. Keep dialogue/history
  per context/device, survive restart, and clear follow-up retrieval on reset.

## Task 1 — Retrieval independent of writer context

- [ ] Add `knowledge/retrieval.py` and focused tests for manual notes outside
  `Затея/`, Unicode/Russian forms, aliases, long-note passages, topic comparison,
  unrelated active topic, no match, explicit topic switch and follow-up references.
- [ ] Enforce safe traversal, size/count/time/context bounds; tests cover symlink
  escape, hidden paths, malformed text, stale/deleted files and truncated results.
- [ ] Integrate `retrieved_pages`/search metadata separately from writable `pages`.
  Select relevant adjacent/topic-linked notes when budget allows; preserve stable
  vault-relative identities and hashes for citation verification.

## Task 2 — Grounded answer contract and history

- [ ] Add a backward-compatible optional answer contract to HermesResponse and
  AgentReply; propagate through direct LLM result caching and TextTurnResult.
- [ ] Extend prompts with found/not-found/ambiguous/conflicting behavior and concise
  voice replies; current retrieved evidence outranks remembered assistant claims.
- [ ] Validate structured citations and exact quotes before returning an answer;
  persist `answer.json` and answer metadata without having pipeline overwrite it.
- [ ] Expose bounded answer citations through authenticated job results/history;
  verify another device cannot access them and old clients remain compatible.
- [ ] Keep scoped follow-up context durable and resettable. Re-read referenced
  notes for new questions; retries reuse their original captured context.

## Task 3 — Questions do not publish Obsidian pages

- [ ] Add deferred source materialization to KnowledgeStore/TextTurnProcessor.
  Persist raw evidence first with conflict detection and original metadata intact.
- [ ] Query publication validates intent and returns a receipt without Markdown
  writes. Mutating operations materialize current/referenced sources safely,
  including a clarification question later answered as a new note.
- [ ] Test query/no-result/clarification/retry/restart leave all vault Markdown
  hashes unchanged; capture/amend/organization and raw-evidence recovery still pass.
- [ ] Preserve graceful handling of failed model/TTS and Git refresh without
  inventing a saved-note claim or discarding the recording.

## Task 4 — Independent verification and rollout

- [ ] Parent reviews retrieval boundaries, writer separation, citation validation,
  context isolation and retry behavior. Run full backend/deploy tests; run native
  protocol tests if an additive status payload affects firmware parsing.
- [ ] Real configured-model replay in a temporary vault: January trip alternatives,
  Yunnan decision, Raja Ampat uncertainties, follow-up diving comparison, absent
  facts, conflicting notes, malicious note instructions, then a new dictated note.
  Assert correct operation, real citations and no query-created Markdown.
- [ ] Document API/operations, search limits and verification evidence. Commit/push
  scoped changes and deploy backend with a rollback image retained.
- [ ] Verify health plus authenticated result metadata; distinguish server/model
  verification from actual microphone/playback verification on the recorder.
