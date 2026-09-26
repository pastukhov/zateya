# Разработка и запуск

Команды запускайте из корня репозитория. В проекте — Python 3.12 Gateway и прошивка ESP-IDF. Серверный Gateway напрямую использует настраиваемый OpenAI-совместимый Chat Completions API; отдельный Codex Agent не запускается.

## Требования и конфигурация

- Python 3.12 и `pytest` для локальных проверок.
- Docker Engine с Compose для контейнерного запуска.
- PlatformIO Core и ESP-IDF environment из `firmware/platformio.ini` для сборки устройства.
- Доступные OpenAI-совместимые STT, LLM и TTS endpoint’ы.

Скопируйте `.env.example` в `.env` и задайте `LLM_BASE_URL`, `LLM_MODEL`, модели STT/TTS. `LLM_BASE_URL` должен включать API-префикс, например `/v1` или `/api/v1`; Gateway добавляет к нему `/chat/completions`, `/audio/transcriptions` и `/audio/speech`. Ключ LLM необязателен для локального сервера без авторизации. Тестовые readiness-проверки не отправляют запрос к платному API и не проверяют валидность ключа у провайдера.

`LLM_RESPONSE_FORMAT` принимает `text` или `json_object`. В text-режиме Gateway не передаёт JSON-mode параметр. Автоматического выбора модели, смены endpoint и tool/function calling нет. Расходы LLM оплачиваются отдельно от STT/TTS.

## Запуск в Docker Compose

Для локального запуска без существующих данных создайте каталоги; для сервера с vault и Git SSH используйте [runbook](../deploy/server-migration.ru.md).

```sh
docker compose config --quiet
docker compose build backend
./deploy/prepare-data.sh
docker compose up -d --wait
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
curl --fail http://127.0.0.1:8080/metrics
```

Gateway работает в стандартной bridge-сети Compose и публикует `VOICE_BIND_PORT` на хосте для диктофона. Порт доступен на интерфейсах хоста, поэтому ограничьте входящий доступ firewall’ом. Для локальных STT/LLM/TTS сервисов используйте адрес сервиса в общей Compose-сети или специальный адрес хоста; `localhost` внутри контейнера указывает на сам Gateway. Остановка: `docker compose down`.

## Локальный запуск

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt
uvicorn backend.src.voice_gateway.app:app --host 127.0.0.1 --port 8080
```

Укажите локальные `LLM_*`, `STT_*`, `TTS_*` и `ARCHIVE_ROOT`. Если включён Obsidian writer, задайте `OBSIDIAN_VAULT_PATH` и `VOICE_KNOWLEDGE_ENABLED=true`.

## Проверки

```sh
pytest -q backend/src deploy/test_prepare_data.py
bash -n deploy/prepare-data.sh
docker compose config --quiet
docker compose build backend
systemd-analyze verify deploy/zateya.service
```

Unit-тесты используют fake API и временные Git-репозитории. Они не доказывают доступность реального endpoint, качество выбранной модели, работу диктофона или настройку production-сервера.

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

Сборка получает Wi-Fi и Gateway endpoint через переменные окружения. Не помещайте реальные значения в shell history, Git или документацию; для повторяемых сборок используйте защищённый env-файл. Порядок прошивки описан в [руководстве StickS3](flash-sticks3.md).

## Диагностика

| Симптом | Что проверить |
| --- | --- |
| `/health/live` доступен, `/health/ready` возвращает 503 | `checks` в ответе, обязательные `LLM_BASE_URL`, `LLM_MODEL` и запись в archive |
| HTTP 401/403 от LLM | `LLM_API_KEY` у провайдера; ключ не виден через readiness |
| HTTP 429 или 5xx | Ограничение/доступность внешнего LLM API; автоматической смены провайдера нет |
| Не отправляются Obsidian-коммиты | `GET /api/voice/knowledge/git`, remote vault, `data/ssh`, права и Git-конфликт |
| Запись принята, но ответа нет | `GET /api/voice/turns/{turn_id}`, metadata в archive и логи Gateway |

Archive содержит аудио, расшифровки и ответы; ограничьте права и срок хранения. Не используйте настоящие записи и ключи в тестах. `/health/ready` проверяет настройки и локальную запись, но не делает сетевых запросов к STT/LLM/TTS.
