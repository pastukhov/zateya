# Device HTTP protocol

The device uses one voice-job API. Setup requires only the gateway base URL and the device token.

```http
POST /api/voice/turns HTTP/1.1
Content-Type: audio/L16
X-Request-Id: 9b69da5b-bd5d-44a3-9391-15e8dac36733
X-Device-Id: a1b2c3d4e5f6
X-Sample-Rate: 16000
X-Channels: 1
Authorization: Bearer <device-token>
```

The device creates one UUID per recording. The body is streamed mono 16 kHz PCM S16LE, up to 3,840,000 bytes. Once the full upload is stored and queued, the gateway responds `202`:

```json
{"turn_id":"<uuid>","request_id":"<uuid>","status":"queued"}
```

If the response is lost, check `GET /api/voice/requests/{request_id}` instead of uploading again with a new ID. For an accepted turn, poll `GET /api/voice/turns/{turn_id}` about once per second. Status progresses through `queued → transcribing → thinking → synthesizing → ready`. When ready, download `GET /api/voice/turns/{turn_id}/audio`; only a `200` response with `Content-Type: audio/wav` may be played. The WAV is mono 24 kHz PCM S16LE.

`POST /api/voice/turns/{turn_id}/cancel` cancels current work. `POST /api/voice/sessions/reset` starts a new device conversation. Every request requires a bearer token mapped to `X-Device-Id`; an inaccessible or unknown turn returns `404`.

Repeating the same device ID, request ID, and audio SHA-256 returns the existing turn. Reusing an ID for different audio returns `409 idempotency_conflict`; a parallel upload returns `409 upload_in_progress`; a full queue returns `429 agent_busy`. After a restart, queued jobs resume, while interrupted work is not automatically replayed.

## Errors

```json
{"error":"stt_failed","turn_id":"..."}
```

`error` is a machine-readable code. The response contains no secrets or binary audio. Firmware keeps an error on screen until the button is pressed.

| Code | HTTP or status | Meaning |
| --- | --- | --- |
| `unauthorized` | 401 | Token does not match `X-Device-Id` |
| `invalid_request_id` | 400 | Request ID is not a UUID |
| `audio_too_large` | 413 | Upload exceeds 3,840,000 bytes |
| `audio_invalid` | 400 | PCM upload is empty or has an odd byte count |
| `idempotency_conflict` | 409 | Same request ID with different audio |
| `upload_in_progress` | 409 | Another upload with this request ID is running |
| `agent_busy` | 429 | Job queue is full |
| `audio_not_ready` | 409 | Audio requested before processing finished |
| `stt_failed`, `agent_unavailable`, `tts_failed` | terminal status | Processing failed; see `error` in the status payload |

## Operational endpoints

`GET /health/live` checks process liveness. `GET /health/ready` checks configuration and archive writability. `GET /metrics` returns Prometheus metrics without transcript or note text in labels.

The LLM API returns a short `reply` and, when needed, a structured knowledge proposal. The gateway validates the proposal, writes the Obsidian files, and confirms success only after those writes complete. This JSON is internal to the server, not the device request format.
