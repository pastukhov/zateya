# Протокол диктофона: асинхронный голосовой запрос

Диктофон использует один API голосовых заданий. В настройках указывают только базовый адрес шлюза и токен устройства.

```http
POST /api/voice/turns HTTP/1.1
Content-Type: audio/L16
X-Request-Id: 9b69da5b-bd5d-44a3-9391-15e8dac36733
X-Device-Id: a1b2c3d4e5f6
X-Sample-Rate: 16000
X-Channels: 1
Authorization: Bearer <device-token>
```

Устройство создаёт UUID один раз на запись. Body — потоковый PCM S16LE mono, 16 kHz; максимум 3 840 000 байт. Успешная загрузка полностью сохраняется и ставится в ограниченную очередь до ответа `202`:

```json
{"turn_id":"<uuid>","request_id":"<uuid>","status":"queued"}
```

После потери `202` клиент не загружает аудио с новым ID: он проверяет `GET /api/voice/requests/{request_id}`. Для принятого turn клиент опрашивает `GET /api/voice/turns/{turn_id}` примерно раз в секунду. Status проходит `queued → transcribing → thinking → synthesizing → ready`; этапы `transcribing`, `thinking` и `synthesizing` отражаются на экране устройства. Terminal status `ready` позволяет скачать `GET /api/voice/turns/{turn_id}/audio`; файл — корректный WAV PCM S16LE, mono, 24 kHz. Только `200` с `Content-Type: audio/wav` можно передавать в аудиовыход.

`POST /api/voice/turns/{turn_id}/cancel` отменяет текущую работу. `POST /api/voice/sessions/reset` создаёт новый разговор устройства. Каждый запрос требует bearer-токен, сопоставленный этому `X-Device-Id`; чужой turn и неизвестный turn одинаково отвечают `404`.

Повторная загрузка с теми же device ID, request ID и SHA-256 возвращает существующий turn без повторного запуска агента. Другой audio body с тем же ID — `409 idempotency_conflict`; параллельная загрузка — `409 upload_in_progress`; переполненная очередь — `429 agent_busy`. При рестарте незавершённая job (`running`, `transcribing`, `thinking` или `synthesizing`) становится `interrupted` и не запускается повторно автоматически.

`X-Turn-Id` связывает ответ с каталогом archive.

## Ошибочный ответ

```http
HTTP/1.1 <4xx или 5xx>
Content-Type: application/json
X-Turn-Id: <uuid>
```

```json
{"error":"stt_failed","turn_id":"..."}
```

JSON поля: `error` — машинный код; `turn_id` — UUID turn, если он уже создан. Технические секреты и binary audio не возвращаются. Firmware показывает ошибку на экране до нажатия кнопки.

## Ошибки и рекомендуемые статусы

| Код | HTTP | Где возникает |
|---|---:|---|
| `unauthorized` | 401 | token не соответствует `X-Device-Id` |
| `invalid_request_id` | 400 | request ID не является UUID |
| `audio_too_large` | 413 | upload превысил лимит 3 840 000 байт |
| `audio_invalid` | 400 | пустой/нечётный по размеру PCM upload |
| `idempotency_conflict` | 409 | повторный request ID с другим audio body |
| `upload_in_progress` | 409 | повторный upload этого request ID ещё идёт |
| `agent_busy` | 429 | очередь запросов переполнена |
| `audio_not_ready` | 409 | WAV запрошен до завершения обработки |
| `stt_failed`, `agent_unavailable`, `tts_failed` | terminal status | обработка запроса не завершилась; код находится в `error` status payload |


## Служебные endpoints

```http
GET /health/live
GET /health/ready
GET /metrics
```

`/health/live` возвращает `200`, когда процесс жив. `/health/ready` возвращает `200`, если config загружен и обязательный archive writable; иначе `503`. `/metrics` возвращает Prometheus exposition format (`text/plain` или совместимый content type) и не использует transcript/title/turn_id/error text как labels.

## Ответ агента и запись в Obsidian

LLM API возвращает короткий `reply` и при необходимости структурированное предложение изменений базы знаний. Gateway проверяет предложение, записывает Markdown-файлы в Obsidian и подтверждает успех только после записи. Этот JSON — внутренний контракт сервера, а не формат запроса устройства.
