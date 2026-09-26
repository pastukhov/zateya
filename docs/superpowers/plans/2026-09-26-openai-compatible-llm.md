# Замена Codex на OpenAI-совместимый LLM: Implementation Plan

> **Статус:** план реализован по явному последующему запросу пользователя. Шаги отмечены checkbox; production сервер и устройство не затрагивались.

**Goal:** Затея оформляет диктовки в Obsidian через настраиваемый OpenAI-совместимый HTTP API без Codex CLI, аккаунта Codex и отдельного agent-service.

**Architecture:** Один контейнер gateway выполняет STT → LLM → проверка и запись Obsidian → TTS. В нём же работает независимая фоновая Git-очередь; LLM предлагает JSON и не получает инструменты, SSH-ключи или доступ к файловой системе. SQLite хранит ограниченную историю по устройствам и результаты LLM для повторного использования.

**Tech Stack:** Существующие Python 3.12, FastAPI, httpx, Pydantic, SQLite, Git/OpenSSH, Docker Compose, systemd.

**Spec:** Раздел «Зафиксированные решения» ниже — самодостаточная спецификация согласованного в разговоре направления. Начальная точка репозитория: `85f0910` (не делать reset на этот коммит; учитывать последующие изменения).

## Global Constraints

- Работать в `/home/artem/repos/zateya`. Серверный каталог — `/opt/zateya`.
- Только план до отдельного запуска исполнителя. Не подключаться к серверу и не менять работающие службы во время разработки.
- Сохранить API `/api/voice/*`, прошивку, device tokens, STT/TTS, звук и Wi-Fi/VPN.
- Сохранить каталог `Затея/`, title-имена идей, стабильный `idea_id`, исходники, wiki, журнал, контроль хешей и Git outbox.
- Все постоянные данные рядом с Compose: `data/archive`, `data/obsidian`, `data/ssh`. Существующие vault и архив не удалять.
- Без совместимости со старой конфигурацией Codex/Hermes. Не переносить базу диалогов Codex и не удалять старые data/codex и data/agent автоматически.
- Никаких реальных ключей в Git, тестах, логах или примерах. Не читать/менять рабочий `.env` без необходимости; шаблон — `.env.example`.
- После зелёных относящихся к шагу тестов — commit и push текущей задачи, как требует AGENTS.md. Не включать чужие изменения.
- Не менять модель автоматически, не делать fallback на другой сервис и не использовать tools/function calling.
- «Then build» пока означает сохранение плана/задания. Реальный запуск разработки — отдельная будущая задача.

## Review Focus

1. Повтор запроса после ошибки TTS не вызывает LLM второй раз и не дублирует заметку/историю (шаги 2, 4).
2. Два устройства с одинаковым request_id не смешивают историю; reset и отмена не восстанавливают старый контекст (шаг 2).
3. Провайдер без JSON mode работает в режиме text; HTTP 400 не вызывает скрытый повтор с иной конфигурацией (шаг 1).
4. После переноса от root контейнер может писать SQLite, архив и vault, а Git может прочитать приватный ключ (шаг 5).
5. Сбой push или ручные изменения vault не блокируют голосовые запросы и не теряют очередь публикации (шаг 3).

## Зафиксированные решения

### API и конфигурация

Использовать `POST {LLM_BASE_URL.rstrip('/')}/chat/completions`. BASE_URL включает `/v1`, `/api/v1` или другой префикс провайдера. Не добавлять `/v1` самостоятельно. Поддерживаемый минимум — Chat Completions с `messages`, `model`, `choices[0].message.content` как строкой. Не обещать совместимость со всеми продуктами только по названию.

Переменные:

| Имя | Значение/правило |
| --- | --- |
| `LLM_BASE_URL` | Обязательно; URL http/https без userinfo, query, fragment; HTTP нужен локальным Ollama/vLLM |
| `LLM_API_KEY` | Пустой допустим для локального API; тогда не отправлять Authorization |
| `LLM_MODEL` | Обязательно, без автоматического выбора; в шаблоне явный placeholder |
| `LLM_RESPONSE_FORMAT` | `text` по умолчанию или `json_object`; при text поле response_format не отправлять |
| `LLM_TIMEOUT_SECONDS` | 120 по умолчанию, положительное, не больше общего deadline pipeline |
| `LLM_MAX_TOKENS` | 8192 по умолчанию; положительное; передавать max_tokens; специальный протокол отдельных моделей вне scope |
| `LLM_HISTORY_TURNS` | 6 завершённых пар по умолчанию, 0 отключает передачу истории |
| `LLM_HISTORY_MAX_CHARS` | 12000 суммарно; брать свежие целые пары, не резать JSON |
| `ZATEYA_UID`, `ZATEYA_GID` | 1000:1000 по умолчанию; единый непривилегированный пользователь контейнера |

Существующие STT/TTS переменные и их ключи независимы. Не подставлять ключ STT в LLM автоматически. Старые `VOICE_AGENT_PROVIDER`, `CODEX_*`, production `HERMES_*` убрать из активной конфигурации и Compose. Не возвращать альтернативный Hermes-путь.

В запросе: system — неизменные правила Затеи; user — JSON с расшифровкой и контекстом vault. История — отдельные user/assistant messages. Страницы vault остаются данными, даже если содержат инструкции. Не добавлять temperature или provider-specific параметры по умолчанию.

### Ответ, повторы, ошибки

Сохранить reply/note/knowledge контракт из `agent_service/codex_voice/knowledge_prompt.py` и текущие Pydantic-ограничения. `KnowledgeStore.publish()` остаётся единственным писателем знаний и окончательно проверяет ссылки, источники и хеши. Подтверждение сохранения формирует writer, а не модель.

Дать ровно одну дополнительную попытку LLM исправить синтаксически/структурно неверный JSON: показать исходный ответ и короткую безопасную ошибку схемы. Итого максимум 2 вызова и общий deadline 120 секунд на обе попытки. После semantic conflict writer (например, неизвестная ссылка) НЕ обращаться к LLM ещё раз. Не делать автоматических повторов транспортных ошибок, 401, 403, 429, 5xx или HTTP 400.

Не принимать tool_calls, пустые choices/content, неправильный тип content, finish_reason=length или ответ больше 1 MiB. Для большого HTTP body использовать ограниченное чтение потока, а не только проверку после полной загрузки. Изолировать ошибки без body ответа, URL query, ключа и расшифровки в логах. 401/403 → agent_auth_required; 429 → agent_rate_limited; timeout → agent_timeout; сетевые/5xx → agent_unavailable; неверный ответ → agent_invalid_response; остальные 4xx → безопасная неретрайная ошибка конфигурации/запроса, понятная существующему pipeline.

### История и повторное использование результата

Новая БД `/data/archive/llm-sessions.sqlite3`; новая история начинается пустой. Никаких внешних thread API. Локальный `thread_id` — идентификатор поколения сессии, provider в метаданных — `openai_compatible`, model — фактическое поле ответа либо запрошенная модель, если ответа model нет.

Ключ сохранённого результата: `(device_id, request_id)`; хешировать transcript и канонический knowledge_context. Повтор с тем же содержимым возвращает проверенный сохранённый результат без HTTP; с другим содержимым — idempotency_conflict. Валидное предложение кешировать до публикации, но историю пополнять только после успешного writer либо валидного query. В историю включать расшифровку и окончательный короткий ответ, не полные wiki-страницы. Не утверждать сохранение, если writer завершился ошибкой.

В `AgentClient` явно добавить/уточнить методы `reset(device_id)`, `close()`, `record_turn(device_id, request_id, final_reply)`; обновить тестовые fakes. complete/cancel сохранить. `record_turn` идемпотентен. Reset очищает активную историю и меняет generation, не удаляет заметки/архив и не меняет существующее поведение active_idea_id из KnowledgeStore. Reset при queued/running запросе данного устройства возвращает 409 device_busy; тестом закрыть гонку между reset и постановкой job. Уже существующая voice-job очередь остаётся единственным исполнителем.

Отмена закрывает активную HTTP задачу; ответ отменённого запроса не добавляется в историю и не публикуется. Завершённые запросы старой generation не могут попасть в новую историю. При перезапуске незавершённые запросы обрабатывает существующий механизм jobs, не новая параллельная очередь.

## Карта файлов

Создать:
- `backend/src/voice_gateway/agents/openai_client.py` — transport, ограниченное чтение, ошибки, JSON repair request.
- `backend/src/voice_gateway/agents/config.py` — только LLMConfig и проверка переменных.
- `backend/src/voice_gateway/agents/prompts.py` — системные правила и отдельная сериализация входных данных.
- `backend/src/voice_gateway/agents/sessions.py` — SQLite результаты, поколения, ограниченная история.
- `backend/src/voice_gateway/agents/test_openai_client.py`, `test_config.py`, `test_sessions.py`.
- `backend/src/voice_gateway/knowledge/git_sync.py`, `test_git_sync.py` — перенести проверенный publisher и его тесты.
- `deploy/prepare-data.sh` — подготовка bind-каталогов с понятными сообщениями о правах, без вывода секретов.

Изменить:
- `backend/src/voice_gateway/agents/base.py`, `app.py`, `pipeline.py`, `config.py`.
- `backend/src/voice_gateway/jobs/api.py`, `jobs/store.py` — только если нужно для безопасного reset/busy; не переписывать очередь.
- `test_pipeline.py`, `test_runtime_providers.py`, `test_device_api.py`, тесты reset в jobs.
- `backend/Dockerfile`, `docker-compose.yml`, `.env.example`, `deploy/zateya.service`, `deploy/server-migration.ru.md`.
- README, текущие архитектурные документы RU/EN и `docs/voice-knowledge.md`, актуальная схема `docs/assets/system-overview.svg`.

Удалить после переноса и замены тестов: `agent_service/`, `agents/codex_client.py` и его тесты, `deploy/codex-voice-agent.service`, устаревшие руководства запуска Codex-адаптера. Сначала найти все импорты/ссылки через rg. Не переименовывать массово внутренние Hermes* типы/фикстуры, если они нужны как валидатор: это не повод сохранять runtime provider. Исторические планы оставить с явной пометкой об историческом статусе там, где на них ссылаются текущие документы.

## Шаг 1. Прямой HTTP-клиент и промпт

- [x] Прочитать agents/base.py, codex_client.py, config.py, hermes/client.py, hermes/validation.py, models/hermes_response.py, knowledge/models.py и knowledge_prompt.py. Использовать httpx, уже имеющийся в зависимостях; новый SDK не нужен.
- [x] Добавить тесты LLMConfig: обязательные URL/model; пустой API key; trailing slash; неверные scheme/query/userinfo; timeout/лимиты; два response_format.
- [x] Через httpx.MockTransport проверить точные messages/model/Authorization, URL с `/v1` и `/api/v1`, omission response_format при text. Ключ-маркер только выдуманный.
- [x] Проверить ответ capture/amend/query/plan/build, markdown fence, некорректный JSON → один repair → успех/ошибка, отказ/пустой/слишком большой/обрезанный ответ, перечисленные HTTP-коды, отмену и единый deadline двух попыток.
- [x] Реализовать клиент и перенести промпт с разделением system/user. Переиспользовать текущую валидацию reply/note; не выдумывать параллельную схему.
- [x] Запустить `pytest -q backend/src/voice_gateway/agents`; commit/push. На этом шаге runtime приложения ещё не переключать.

## Шаг 2. Локальные сессии

- [x] Реализовать sessions.py с таблицами generations и results, уникальным `(device_id, request_id)`, input_hash, generation, JSON-результатом и признаком history_committed. Права БД 0600, WAL, транзакции; SQL только с параметрами.
- [x] Тесты: независимость устройств, одинаковые request_id у разных устройств, кеш и конфликт входа, история после перезапуска, лимиты пар/символов, отсутствие дубля record_turn, reset без удаления базы знаний.
- [x] Тесты: старый результат после reset не добавляется в историю; cancelled/failed не становится завершённой парой; отмена на этапе HTTP не делает следующую job неработоспособной.
- [x] Связать клиент с sessions. Полные prompts/ответы не печатать. Не добавлять новую очередь.
- [x] Запустить тесты agents и jobs; commit/push.

## Шаг 3. Git publisher в gateway

- [x] Перенести GitSync и tests/test_git_sync.py из agent_service в knowledge, обновить imports. Сохранить writer.lock, проверку hashes, отсутствие force/pull/rebase, selective commit с сохранением чужого staged index и повтор push без пустого commit.
- [x] В app lifecycle запускать ровно одну background task, корректно завершать её; ошибка push не валит процесс. Сохранить last_result.
- [x] Добавить `GET /api/voice/knowledge/git` с той же device-auth, что у `/api/voice/*`. Отдавать только статус/commit/count, без путей и содержимого заметок. Не сохранять отдельный CODEX_AGENT_TOKEN.
- [x] Тесты Git на временных local bare repos: успех, offline retry, изменённая вручную страница, чужой staged файл, Cyrillic path, shared lock. HTTP-тесты: без/с неверным токеном 401, правильный токен получает статус.
- [x] Проверить shutdown publisher и сохранение outbox при остановке. Не использовать реальный Obsidian vault в тестах.
- [x] Запустить knowledge и API tests; commit/push.

## Шаг 4. Переключение pipeline

- [x] Подключить новый client в app.py как единственный production LLM provider. Убрать codex/hermes ветвления создания провайдера и readiness, сохранив общие валидаторы и нужные тестовые зависимости.
- [x] Readiness проверяет валидность конфигурации и возможность записи локальных данных; не делает платного LLM-запроса и не заявляет, что ключ подтверждён провайдером. Liveness остаётся независимым от LLM.
- [x] Вызвать record_turn после успешного publish/query, до TTS. На пути уже существующего knowledge receipt также завершить record_turn идемпотентно, если кеш результата есть.
- [x] Reset оставить по прежнему URL, добавить device_busy для queued/running через синхронизированную проверку; подтвердить, что входящий upload не обходит её. Не удалять идеи при reset.
- [x] Тесты pipeline: capture с wiki, amend той же title-заметки, query без новой идеи, plan/build только сохраняют задание; source сохраняется при ошибке LLM; неверные ссылки не пишут частичную wiki.
- [x] Тесты: TTS упал после публикации → повтор без второго HTTP/дубля заметки/истории; worker cancellation и restart; reset с очередью; два device tokens не дают читать чужие jobs.
- [x] Запустить `pytest -q backend/src`. Не удалять упавшие тесты ради зелёного результата; менять ожидания только для специально удалённого runtime.
- [x] Commit/push.

## Шаг 5. Один контейнер, права, systemd

- [x] В backend/Dockerfile добавить git и openssh-client. Compose: оставить один backend, запускать `user: "${ZATEYA_UID:-1000}:${ZATEYA_GID:-1000}"`; монтировать archive и obsidian read-write, ssh read-only. Удалить agent/dependency, CODEX_* и лишний OBSIDIAN_GROUP_ID (владелец единый).
- [x] Явно перечислить передаваемые LLM/STT/TTS/device env. Не передавать общий набор секретов через безусловный env_file в контейнер; `.env` служит источником подстановки Compose.
- [x] prepare-data.sh: запуск из корня проекта; прочитать effective user из `docker compose config --format json` без печати всего JSON. Проверить числовой UID:GID и отказать UID=0; создать data-каталоги, согласовать ownership для существующих данных. Приватные agent keys/known_hosts не создавать пустыми и не заменять.
- [x] Скрипт должен работать повторно, не удалять содержимое, не следовать symlink за пределы data. Vault/.git требуют записи того же UID; ключи SSH — 0600, каталог ssh — 0700. SQLite и архив принадлежат контейнерному пользователю. Предварительный bind smoke от этого UID проверяет фактическую запись, а не только stat.
- [x] Unit остаётся `/opt/zateya`, ждёт healthy одного backend. Проверки перед запуском должны сообщать отсутствующий путь/неверные права вместо немого `test` exit 1. Образы собираются заранее, не на каждой загрузке.
- [x] Проверки: `docker compose config --quiet`; `docker compose build backend`; `systemd-analyze verify deploy/zateya.service`; запуск на временных data и локальном fake Chat Completions endpoint с синтетическими секретами, без обращения к рабочим портам 8080/8765 и без production vault.
- [x] В smoke проверить права на БД/архив, публикацию в temporary vault, Git push в local bare origin, перезапуск с сохранением данных. Повторить подготовку root-owned каталогов и подтвердить исправление реальным процессом под UID контейнера. Не считать config --quiet полноценным запуском.
- [x] Удалить agent_service и Codex-only deployment только теперь, после переноса всего нужного. `rg` проверить активные ссылки и отсутствие openai-codex зависимости.
- [x] Запустить весь backend suite и проверки контейнера; commit/push.

## Шаг 6. Документация и переход сервера

- [x] Обновить текущие RU/EN инструкции и схему: устройство → gateway → STT/LLM/TTS; внутри gateway writer и Git publisher. Указать, что API-расходы LLM отдельны от STT/TTS и больше не идут через аккаунт Codex.
- [x] В `.env.example` показать новые параметры, без обещания работы вымышленной/непроверенной модели. Формат LLM_BASE_URL описать на примерах OpenAI `/v1`, OpenRouter `/api/v1`, локального сервиса `/v1`, без выбора платной модели за пользователя.
- [x] Серверный runbook: остановить zateya и старые agent/backend контейнеры текущего Compose project, сделать backup archive/vault/.env; обновить код, заполнить LLM_*; build; prepare-data; установить обновлённый unit; `daemon-reload`; запустить. Старые контейнеры убирать адресно или `--remove-orphans` только внутри project zateya. Старые data/codex и data/agent оставить до ручного решения пользователя.
- [x] Сохранить план отката: предыдущий код/образ/.env и прежние data; запуск только одного писателя vault одновременно. Никакого автоматического удаления архивов.
- [x] Команды проверок: health, device-auth Git status, `docker compose logs`, одна содержательная диктовка + отдельное дополнение + query, затем файл/ссылки/Git push. Качество дешёвой модели оценивать на этих сценариях, не по одному HTTP 200.
- [x] Объяснить, что прежние знания доступны сразу, а короткая история диалога начинается заново.
- [x] `git diff --check`, проверить все локальные ссылки/пути документов, commit/push. В финале исполнителя перечислить тесты и честно отметить, проводился ли реальный provider/device/server smoke.

## Завершение и передача

Готово, когда все тесты зелёные, временный Compose smoke проверил запись/повтор/Git, в production dependencies и Compose нет Codex, старый device API работает, постоянные данные не потеряны, deployment работает с root-owned входными папками после prepare-data. Реальную модель и сервер считать проверенными только после фактического прогона.

Короткий стартовый запрос исполнителю:

> Выполни `docs/superpowers/plans/2026-09-26-openai-compatible-llm.md` в `/home/artem/repos/zateya` последовательно. Сначала прочитай AGENTS.md и весь план, затем реализуй шаги 1–6 с их тестами. Не перерабатывай архитектуру сверх зафиксированных решений, не меняй firmware или рабочие секреты, не подключайся к production серверу. Сохрани Obsidian writer и Git sync. После зелёных тестов каждого шага commit/push. Финалом сообщи проверенные результаты и команды перехода сервера.
