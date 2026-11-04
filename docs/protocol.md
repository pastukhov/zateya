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

## Уточняющий диалог диктофона

Необязательное поле готового ответа:

```json
{"status":"ready","turn_id":"…","request_id":"…","follow_up":{"question_id":"12345678-1234-1234-1234-123456789abc","listen":true}}
```

`follow_up` появляется только после успешной генерации и проверки WAV с вопросом.
При ошибке TTS источник и ожидающий вопрос остаются сохранёнными, автоматическое
прослушивание не предлагается. Повторный poll возвращает тот же ID и намерение.
Старые клиенты игнорируют дополнительное поле; старые ответы без поля не включают
микрофон автоматически.

Firmware начинает ответ лишь после полного успешного воспроизведения вопроса и
дренирования динамика: локальное «Слушаю», дренирование, 150 мс на затухание,
ожидание речи. Намерение потребляется один раз; ошибка, отмена и восстановление
старого turn после перезагрузки не запускают микрофон. Загрузка ответа может
содержать `X-Answer-To: <question_id>` (UUID, до 36 символов). ID сохраняется вместе
с upload; повтор того же request с другой привязкой — `409 idempotency_conflict`.
Неверный UUID — `400 invalid_answer_to`. Чужой/просроченный ID не связывает речь с
вопросом: backend сверяет ID с ожидающим вопросом того же контекста. Отсутствие
заголовка не исключает смыслового продолжения, которое определяет модель.

Модель явно возвращает `clarification={question,source_ids}` и при ответе,
отказе либо смене темы — `dialogue_resolution={question_id,action}`, где `action`
равно `answered`, `declined` или `superseded`. Пунктуация ответа не включает этот
режим. Источники обязаны существовать в контексте того же устройства. Ожидающий
вопрос хранится отдельно от публикации заметки, переживает перезапуск backend и
истекает через 15 минут. Истечение/отказ не удаляет исходную диктовку. После трёх
последовательных уточнений автоматическое прослушивание прекращается; следующий
вопрос можно ответить кнопкой. Словарь команд от пользователя не требуется.

## Серверные реплики устройства

`GET /api/device/cues/{name}` принимает фиксированные имена `listening`,
`processing`, `offline`. Прежний listening URL и общий
`GET /api/device/cues/audio/{sha256}.pcm` сохранены. Все запросы требуют токен
устройства. Манифест содержит версию, SHA256, размер и формат: PCM16 LE mono
24 кГц, максимум 240000 байт. Пока конкретная фраза не готова — HTTP503 и
`Retry-After: 60`; неизвестное имя/digest — 404. Запросы синтез не запускают.

Сервер постоянно хранит проверенный результат TTS для конфигурации/текста.
Диктофон независимо обновляет три PSRAM-буфера в ожидании (в том числе от батареи),
не пересылает токен по redirect и сам строит audio URL из проверенного SHA.
Буфер удерживается на время воспроизведения; неудачная загрузка сохраняет прежний.
При активации записи сетевого запроса нет. После выключения питания PSRAM пуста,
до первой загрузки звучит короткий встроенный сигнал; речевых PCM в прошивке нет.

## Ответ по заметкам и история

В готовом status/lookup может присутствовать короткий
`answer_url: "/api/voice/turns/<uuid>/answer"`. Полные цитаты не включаются в
обычный status: он остаётся совместимым с JSON-буфером firmware 768 байт.
`GET /api/voice/turns/{turn_id}/answer` возвращает приватные метаданные:

```json
{"status":"found","reply":"Краткий озвученный ответ","citations":[{"ref":"q-…","path":"Отпуск/Раджа.md","title":"Раджа","quote":"Точная цитата","sha256":"…","link":"obsidian://open?…"}],"search":{"coverage":"bounded_local_scan","truncated":false}}
```

Статусы: `found`, `not_found`, `ambiguous`, `conflicting`, `unsupported`.
Путь/quote/hash/link формирует и проверяет backend по реально переданному
retrieval-снимку; ID цитаты позволяет модели не перепечатывать исходный текст.
`GET /api/voice/history` возвращает до 20 ready jobs с ID и `answer_url` текущего
устройства. Все маршруты требуют его токен; чужой/неизвестный/неготовый answer —
404, без токена — 401. History/answer имеют `private, no-store`; answer — до 64 КиБ.

`query` хранит сырой ввод и receipt в archive/DB, но не публикует Markdown в vault.
Источники материализуются только при настоящем изменении заметок. Подробнее:
[вопросы по Obsidian](operations/obsidian-questions.md).
