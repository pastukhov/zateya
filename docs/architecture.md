# Архитектура

Затея состоит из диктофона StickS3, одного Voice Gateway, внешних сервисов распознавания/LLM/синтеза и Obsidian vault. Gateway выполняет голосовой сценарий, запись знаний и Git-публикацию в одном контейнере.

![Путь записи от устройства до Obsidian](assets/system-overview.svg)

## Компоненты

```mermaid
flowchart LR
    D["StickS3<br/>запись и воспроизведение"]
    subgraph G["Voice Gateway · один контейнер"]
      Q["Очередь и архив"]
      W["STT · проверка LLM-ответа<br/>Obsidian writer · Git publisher · TTS"]
      DB[("SQLite<br/>задания и история LLM")]
      Q --> W
      Q --> DB
    end
    P["OpenAI-совместимые API<br/>STT · Chat Completions · TTS"]
    O[("Obsidian vault<br/>sources · ideas · wiki · builds")]
    R[("Git origin")]
    D -->|"PCM + device token"| Q
    W <-->|"запросы и ответы"| P
    W -->|"проверенный Markdown"| O
    W -->|"коммиты"| R
    W -->|"WAV"| D
```

К Gateway настроенный Chat Completions API получает речь и выбранный контекст базы как данные. Он не получает инструменты, доступ к файлам, Git или SSH-ключи. Gateway проверяет JSON по существующей схеме и применяет изменения через Obsidian writer. API-ключи хранятся в серверном `.env`; устройство получает только свой токен для Gateway.

## Голосовой запрос

```mermaid
sequenceDiagram
    participant D as StickS3
    participant G as Gateway
    participant A as Архив и очередь
    participant S as STT API
    participant L as LLM API
    participant O as Obsidian writer
    participant T as TTS API
    participant Git as Git publisher
    D->>G: PCM + request ID + device token
    G->>A: сохранить запись и задание
    G-->>D: ID задания
    A->>S: распознать WAV
    S-->>A: текст
    A->>L: текст и ограниченный контекст
    L-->>A: reply и предложение изменений
    A->>O: проверить и сохранить Markdown
    O-->>A: успешная запись / receipt
    A->>L: зафиксировать локальный результат в истории
    A->>T: синтезировать подтверждённый ответ
    T-->>A: WAV
    A-->>D: состояние и WAV по запросу
    O-->>Git: локальная очередь публикации
    Git->>Git: commit выбранных файлов и push origin
```

Устройство создаёт UUID перед отправкой записи. Повтор с тем же запросом не создаёт новую задачу. Gateway кеширует проверенный результат LLM по паре device ID/request ID, поэтому повтор после сбоя синтеза не вызывает LLM второй раз и не создаёт повторную заметку. Краткая история хранится отдельно в `/data/archive/llm-sessions.sqlite3` и сбрасывается для каждого устройства отдельно.

## Настройка устройства и сервера

StickS3 записывает моно PCM S16LE 16 кГц по нажатию кнопки и воспроизводит WAV через ES8311. Setup AP называется `Zateya-Setup-XX`; после подключения к Wi-Fi полный веб-интерфейс доступен также через IP или mDNS `zateya-<MAC>.local`.

Compose запускает один backend под числовым непривилегированным UID/GID. `data/archive`, `data/obsidian` и read-only `data/ssh` монтируются с хоста. Скрипт `deploy/prepare-data.sh` согласует владельца с Compose и не удаляет существующие данные. Подробности перехода — в [серверном runbook](../deploy/server-migration.ru.md).

## Obsidian и проверки

Исходники лежат в `Затея/sources/`, идеи — в `ideas/`, связанные страницы — в `wiki/`, планы и задания — в `builds/`. Публикация коммитит только файлы из outbox; ручные staged-изменения сохраняются. Push работает в фоне и не задерживает голосовой ответ. Статус доступен через авторизованный `GET /api/voice/knowledge/git`.

`/health/live` проверяет процесс. `/health/ready` проверяет настройки и запись в архив без сетевых вызовов. Доступ к gateway ограничьте доверенной сетью; не публикуйте его напрямую в Интернет.
