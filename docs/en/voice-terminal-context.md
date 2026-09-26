# Zateya project context

Zateya is a voice interface to a personal Obsidian knowledge base, inspired by LLM Wiki and “Ramble your idea, then build.” The StickS3 records speech and plays the reply. A single Voice Gateway stores the job, calls STT and a configured OpenAI-compatible LLM, validates and writes the note, synthesizes the reply, then publishes changes to `origin` in the background.

Current references: [architecture](architecture.md), [HTTP protocol](protocol.md), [LLM Wiki](../voice-knowledge.md), [device setup](flash-sticks3.md), and the [server runbook](../../deploy/server-migration.ru.md).

External LLM/STT/TTS keys stay in the server-side `.env`. The device uses a separate bearer token. The Obsidian writer and Git publisher run inside the same gateway; the SSH key is mounted read-only and is never sent to the model.

The vault folder is `Затея/`. A `build` request saves a draft task but does not yet launch an automated coding agent.
