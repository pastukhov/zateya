# Zateya project context

Zateya is a voice interface to a personal Obsidian knowledge base. The M5Stack StickS3 records speech on button press and plays the reply. Voice Gateway stores the recording as a job, transcribes it, and calls the local Codex Agent. The agent proposes a formatted idea, amendment, wiki page, plan, or draft build task; the gateway validates and writes the files. A synthesized spoken reply returns to the device. Obsidian changes are then committed and pushed to `origin` automatically.

Current references: [architecture](architecture.md), [HTTP protocol](protocol.md), [knowledge workflow](../voice-knowledge.md), and [device setup](flash-sticks3.md). Early plans, specifications, and handoff files document project history and may no longer describe the deployed system.

Codex credentials remain in the local host service. The recorder uses a separate device token. The Obsidian folder for voice recordings is currently named `Hermes/`.
