# Codex Voice Agent

This service gives each StickS3 device a durable Codex conversation. Docker Compose runs it beside the Voice Gateway; only the agent container mounts Codex credentials from `./data/codex`. The firmware and gateway receive no account credentials.

## Runtime

- Python 3.12 in the local `.venv` with dependencies pinned in `requirements.txt`.
- `openai-codex` and its bundled Codex runtime are pinned to `0.156.1`.
- The service listens on `127.0.0.1:8765`; do not bind it to a LAN address.
- Runtime SQLite state is bind-mounted from `./data/agent` in Compose.
- Codex account credentials persist in `./data/codex` and are mounted only into the agent container. Never bake them into an image or send them to the device.

## Configuration

Compose reads a mode-0600 `.env` next to `docker-compose.yml`. The old systemd unit remains available for local development. Set `CODEX_AGENT_TOKEN` to a separately generated bearer secret. Optional settings are `CODEX_VOICE_CWD`, `CODEX_VOICE_MODEL`, and `CODEX_VOICE_TURN_TIMEOUT` (maximum 120 seconds). The gateway receives its own matching adapter token through its local environment; do not reuse the device token.

For the current voice and Obsidian workflow, set `CODEX_VOICE_MODEL=gpt-6-luna` in `.env`. The service retries a malformed JSON reply once in the same conversation before returning `agent_invalid_response`.

The adapter keeps one active conversation thread per `device_id`. Request IDs are idempotent; a repeated request with different transcript text is rejected. Reset creates a new active thread while retaining old SQLite history. An interrupted request is not replayed automatically after restart.

## Local checks

Run the fake-runtime tests without account requests:

```sh
.venv/bin/python -m pytest -q tests
```

The one-request SDK smoke makes a real, billable/quota-consuming Codex request and writes only non-secret diagnostics to the ignored `smoke-result.json`:

```sh
.venv/bin/python -m codex_voice.smoke
```

Check `GET /health/live` for process liveness and `GET /health/ready` for SDK/model readiness. Readiness checks account/runtime availability, not STT/TTS or device audio. The current deployment uses `VOICE_AGENT_PROVIDER=codex`; after changing the service, verify a spoken reply on the device.
