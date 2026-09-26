# Develop and run the project

Run commands from the repository root. The project contains a Python 3.12 gateway and ESP-IDF firmware. The server gateway calls a configured OpenAI-compatible Chat Completions API directly; there is no separate Codex Agent service.

## Requirements and configuration

- Python 3.12 and `pytest` for local checks.
- Docker Engine with Compose for containerized runs.
- PlatformIO Core and the ESP-IDF environment configured by `firmware/platformio.ini` to build firmware.
- Reachable OpenAI-compatible STT, LLM, and TTS endpoints.

Copy `.env.example` to `.env` and configure `LLM_BASE_URL`, `LLM_MODEL`, and the STT/TTS URLs and models. `LLM_BASE_URL` includes the API prefix, such as `/v1` or `/api/v1`; the gateway only appends `/chat/completions`. The API key may be empty for an unauthenticated local service. Readiness checks do not contact a paid API or verify a provider’s key.

`LLM_RESPONSE_FORMAT` accepts `text` or `json_object`. In text mode the gateway omits JSON-mode parameters. It does not choose a model, switch endpoints, or use tool/function calling. LLM usage is billed separately from STT/TTS.

## Start with Docker Compose

For a local run without existing data, create the data directories. For a server with an existing vault and Git SSH, follow the [runbook](../../deploy/server-migration.ru.md).

```sh
docker compose config --quiet
docker compose build backend
./deploy/prepare-data.sh
docker compose up -d --wait
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
curl --fail http://127.0.0.1:8080/metrics
```

The gateway uses Compose's default bridge network and publishes `VOICE_BIND_PORT` on the host for the recorder. The port is reachable on the host interfaces, so restrict inbound access with a firewall. For local STT/LLM/TTS services, use a service address on the shared Compose network or the host's special gateway address; `localhost` inside the container points back to the gateway itself. Stop it with `docker compose down`.

## Run locally

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt
uvicorn backend.src.voice_gateway.app:app --host 127.0.0.1 --port 8080
```

Set local `LLM_*`, `STT_*`, `TTS_*`, and `ARCHIVE_ROOT`. If the Obsidian writer is enabled, also set `OBSIDIAN_VAULT_PATH` and `VOICE_KNOWLEDGE_ENABLED=true`.

## Checks

```sh
pytest -q backend/src deploy/test_prepare_data.py
bash -n deploy/prepare-data.sh
docker compose config --quiet
docker compose build backend
systemd-analyze verify deploy/zateya.service
```

Unit tests use fake APIs and temporary Git repositories. They do not prove the real endpoint is reachable, the selected model produces good notes, the recorder works, or the production server is configured.

Native firmware tests:

```sh
cd firmware
pio test -e native
```

Build the target board:

```sh
cd firmware
export ZATEYA_WIFI_SSID='your-network'
export ZATEYA_WIFI_PASSWORD='your-password'
export ZATEYA_GATEWAY_URL='http://192.168.1.10:8080'
pio run -e sticks3
```

The firmware build reads Wi-Fi and gateway values from environment variables. Do not put real values in shell history, Git, or documentation; use a protected local environment file for repeatable builds. See the [StickS3 guide](../flash-sticks3.md) for flashing.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `/health/live` works but `/health/ready` returns 503 | The `checks` body, required `LLM_BASE_URL`, `LLM_MODEL`, `STT_BASE_URL`, and archive write access |
| LLM returns HTTP 401/403 | `LLM_API_KEY` with the provider; readiness does not reveal key validity |
| LLM returns HTTP 429 or 5xx | Provider limits/availability; no automatic provider switch is attempted |
| Obsidian commits are not pushed | `GET /api/voice/knowledge/git`, vault remote, `data/ssh`, permissions, and Git conflicts |
| Recording was accepted but there is no reply | `GET /api/voice/turns/{turn_id}`, archive metadata, and gateway logs |

The archive contains audio, transcripts, and replies; restrict access and define a retention period. Do not use real recordings or keys in tests. `/health/ready` checks configuration and local writes but makes no STT/LLM/TTS network requests.
