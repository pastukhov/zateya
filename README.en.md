# Zateya · Затея

Zateya is a pocket voice assistant for the M5Stack StickS3. It turns free-form speech into Obsidian notes and a linked LLM Wiki, then helps develop ideas into plans and draft build tasks following “Ramble your idea, then build.”

Documentation: [English](docs/en/index.md) · [Русский](docs/ru/index.md).

The project contains device firmware and a single server-side Voice Gateway. The gateway transcribes speech, calls a configured OpenAI-compatible Chat Completions endpoint, validates and writes Markdown to Obsidian, synthesizes a spoken reply, and publishes changes through Git in the background. It does not require Codex CLI or a Codex account. Persistent directories live in `data/` next to Compose.

![System components and security boundaries](docs/assets/system-overview.svg)

## Quick start

```sh
cp .env.example .env
# Configure LLM_*, STT_*, TTS_*, and device tokens in the local .env.
chmod 600 .env
```

For a server deployment, place the existing Obsidian vault in `data/obsidian`, configure Git SSH in `data/ssh`, and follow the [Linux server guide](deploy/server-migration.ru.md). See the [development guide](docs/en/development.md) for configuration checks and tests.

Compose uses host networking; restrict the gateway port to a trusted LAN or WireGuard network. `LLM_API_KEY`, speech-service keys, and device tokens are passed only to the gateway process and are never exposed by the recorder’s web UI.

## Connect the StickS3

Without saved Wi-Fi settings, the device creates the open `Zateya-Setup-XX` network, where `XX` is the final two hexadecimal characters of the Wi-Fi MAC. Your phone may open the setup portal automatically; otherwise browse to `http://192.168.4.1/`.

Choose Wi-Fi and enter the gateway address and device token. Full setup remains available after the device joins a local network, using its IP address or mDNS name. The page includes a confirmed settings reset.

## Voice request

The device follows a half-duplex cycle: `READY → LISTENING → THINKING → SPEAKING → READY`. The gateway stores each recording as a job, processes it, and returns WAV audio. Each device uses a distinct bearer token.

For a substantive dictation, Zateya replies briefly, saves the source transcript and formatted idea in Obsidian, then commits and pushes the changes to `origin`. See the [LLM Wiki guide](docs/voice-knowledge.md).

## Repository layout

| Path | Purpose |
| --- | --- |
| `firmware/` | ESP-IDF/PlatformIO firmware for M5Stack StickS3 |
| `backend/` | FastAPI gateway, LLM/STT/TTS clients, archive, Obsidian writer, and Git publisher |
| `deploy/` | data preparation and systemd unit |
| `docs/` | architecture, protocol, development, device setup, and diagrams |
| `docker-compose.yml` | single backend container |
| `.env.example` | environment template without real secrets |

Never commit `.env`, Wi-Fi passwords, device tokens, API keys, or SSH keys. The setup AP is open and intended for nearby provisioning only.

### mDNS

The device advertises `zateya-<MAC>.local`, for example `zateya-7ce8b1e4b780.local`. Full setup is available through this name on the local network or at `http://192.168.4.1/` while connected to the setup AP.
