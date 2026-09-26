# Разработка и запуск

Команды запускайте из корня репозитория, если отдельно не указано иное. Проект состоит из Python gateway, отдельного Python Codex adapter и firmware для ESP-IDF.

## Требования

- Python 3.12.
- Docker Compose для совместного запуска gateway и Codex Agent.
- PlatformIO Core и ESP-IDF environment из `firmware/platformio.ini` для сборки устройства.
- Доступные STT и TTS endpoint’ы, совместимые с OpenAI API, и авторизованный Codex Agent в Compose.

## Настройка окружения

```sh
cp .env.example .env
# Укажите локальные URL, модели и ключи в .env; не коммитьте его.
```

Минимальная конфигурация для voice turn: `STT_BASE_URL`, `TTS_BASE_URL`, `TTS_MODEL`, `VOICE_AGENT_PROVIDER=codex`, `CODEX_AGENT_URL` и `CODEX_AGENT_TOKEN`. Имена и defaults смотрите в `.env.example` и `docker-compose.yml`.

## Запуск шлюза

### Docker Compose

```sh
docker compose up --build -d
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
curl --fail http://127.0.0.1:8080/metrics
```

Compose запускает оба сервиса в host network mode. Так шлюз видит Codex Agent на `127.0.0.1`, но слушающий `0.0.0.0` порт также может быть доступен другим узлам сети — проверьте firewall и доверие к LAN. Остановка: `docker compose down`.

### Локально

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt -r agent_service/requirements.txt
uvicorn backend.src.voice_gateway.app:app --host 127.0.0.1 --port 8080
```

Для самостоятельного запуска Codex adapter следуйте [Codex deployment guide](../deploy/codex-voice-agent.md).

## Проверки

Backend tests запускаются из корня (корневой `conftest.py` настраивает import path):

```sh
pytest -q backend
cd agent_service
python -m pytest -q tests
```

Эти тесты используют fake runtime и HTTP mock transport. Они не доказывают, что текущая сессия Codex авторизована или что внешние STT/TTS endpoint’ы доступны.

Native tests firmware не требуют подключённого устройства:

```sh
cd firmware
pio test -e native
```

Сборка целевой платы:

```sh
cd firmware
export ZATEYA_WIFI_SSID='your-network'
export ZATEYA_WIFI_PASSWORD='your-password'
export ZATEYA_GATEWAY_URL='http://192.168.1.10:8080'
pio run -e sticks3
```

Сборка получает Wi-Fi и endpoint через переменные окружения. Не вставляйте реальные значения в shell history, git или документацию; для повторяемой локальной настройки применяйте защищённый env-файл. Порядок прошивки описан в [руководстве StickS3](flash-sticks3.md).

## Диагностика

| Симптом | Что проверить |
| --- | --- |
| `/health/live` доступен, `/health/ready` возвращает 503 | Поля `checks` в ответе: обязательные STT/agent config и права записи `ARCHIVE_ROOT` |
| Устройство не появляется в домашней сети | После минуты ищите `Zateya-Setup-XX`; устройство продолжает попытки STA-подключения |
| Wi-Fi работает, voice turn завершается ошибкой | Gateway URL, устройство/token mapping, STT/TTS настройки и логи gateway |
| Запись принята, но ответа нет | Проверяйте `GET /api/voice/turns/{turn_id}` и archive metadata; terminal error возвращается кодом `error` |
| Codex service не ready | Проверяйте вход в Codex CLI под тем же системным пользователем и `GET /health/ready` adapter’а; не копируйте credentials в контейнер |

## Данные и безопасность

- Archive содержит аудио, расшифровку и ответ; ограничьте права и срок хранения.
- База заданий хранится рядом с archive, если `VOICE_JOB_DATABASE` не переопределён.
- `/health/ready` не проверяет текущую доступность внешних STT/TTS сетей.
- Не используйте настоящие записи и ключи в тестах. Setup AP открытый и работает только для локального provisioning.
- Перед публикацией gateway проверьте bind address, firewall и отсутствие секретов в логах.
