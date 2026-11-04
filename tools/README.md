# Thought organization replay

Run mechanics tests without any provider:

```sh
pytest -q backend/src/voice_gateway/knowledge/test_store.py backend/src/voice_gateway/knowledge/test_organization_sequence.py
sh tools/tests/thought-organization_smoke.sh
```

Opt in to real model requests using the existing provider environment (never print keys):

```sh
python tools/replay-thought-organization.py --real
```

Requires `LLM_BASE_URL`, `LLM_MODEL`; optionally `LLM_API_KEY` and the normal
LLM configuration variables. No fallback provider is selected. Requests may incur cost.
The tool creates a new `/tmp/zateya-thought-replay-*` vault, state DB and session DB.
It has no production vault argument and never runs Git, deployment or TTS.
Every turn starts a new KnowledgeStore to exercise restart. The final report path
contains proposals, source IDs, receipts, membership metadata and a review checklist.
Artifacts remain available for inspection; remove that specific temporary directory
when finished. Treat generated text as private user data.

Exit 0 means the replay completed without publication rejection, **not** semantic
success; exit 2 means at least one publication needs review. The report deliberately
labels semantics `requires_human_review`. Inspect both alternatives sharing a topic,
firmware isolation, uncertain names, provenance and the initial garbled dictation.
Record semantic pass/fail separately from deterministic test results. Fake-model or
scripted tests validate storage mechanics only. Physical microphone/STT/TTS behavior
requires separate device testing.
