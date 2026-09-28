# Навык «Моя затея» для Алисы — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать владельцу общий голосовой доступ через Алису и диктофон к Obsidian, LLM Wiki и подготовке планов.

**Architecture:** Адаптер Алисы и устойчивая текстовая очередь внутри существующего gateway. Общий сервис обработки текста использует нынешние LLM, writer и Git sync; у диктофона остаётся аудиоконвейер, у Алисы — платформенные распознавание и озвучивание.

**Tech Stack:** Python, FastAPI, Pydantic, httpx, SQLite, asyncio, Git, Docker Compose; Яндекс Диалоги и Яндекс ID.

**Spec:** [Проект решения](../specs/2026-09-27-alice-skill-design.md).

Статус: backend-код частично реализован и локально проверен; compose-конфиг
прошёл проверку, backend-образ собран. Внешние настройки Яндекса, публичный
HTTPS и интеграционный прогон с отдельным vault/колонкой не выполнены. Alice
должна оставаться отключённой до прохождения этих ручных этапов.

## Global Constraints

- Один владелец, приватный навык, существующий общий vault; многопользовательский режим не реализуется.
- Бюджет webhook 2 s при лимите платформы 4,5 s; LLM и Git запрещены внутри обработчика webhook.
- Реплика и ответ Алисы не более 1024 символов; черновик не более 12 000 символов, без молчаливой обрезки.
- Все постоянные данные рядом с Compose в `data/`; отдельные Redis/Celery не добавлять.
- Прошивку и `/api/voice/turns` не менять; не имитировать аудио для текстовых задач.
- Сохранить capture/amend/query/plan/build, женский род, числа, отрицания и исправления пользователя.
- До подтверждения writer нельзя говорить «Сохранила»; Git push отражается отдельно.
- Не делать миграции старых настроек и баз. Использовать существующий ID контекста диктофона.
- После зелёных относящихся к задаче тестов — отдельный commit и push по AGENTS.md.

## Review Focus

- Повторный webhook после потерянного ответа: один фрагмент, одна задача, один источник (задача 3).
- Алиса и диктофон дополняют последнюю идею одновременно: стабильный target_id и последовательное применение (задача 2).
- Контейнер упал после публикации, но до фиксации результата очереди: без второй заметки/истории (задача 3).
- Чужой пользователь подставляет известные skill_id/user_id: нет доступа по одному JSON (задача 4).
- Долгая LLM, недоступный Git или занятая SQLite: webhook укладывается в бюджет и не подтверждает несохранённый запрос (задачи 3–5).

## 1. Проверить внешние условия на изолированном черновике навыка

**Files:** Create `docs/alice-skill.md`, позднее дополнить в задаче 6.

**Interfaces:** Производит проверенную конфигурацию публикации и тестовые JSON fixtures без токенов/личных реплик.

- [ ] Уточнить у владельца домен/существующий reverse proxy, наличие публичного входа и поверхность тестирования (колонка, приложение). Не просить публично пересылать секреты.
- [ ] Создать приватный черновик «Моя затея» в аккаунте владельца, проверить доступность активационного имени. Для первого прогона использовать ответ-заглушку без vault.
- [ ] Зарегистрировать приложение Яндекс ID, настроить связку аккаунтов по официальной инструкции, пройти её из приложения, проверить передачу токена на колонке и получение владельца через `/info`.
- [ ] Получить обезличенные fixtures: старт, SimpleUtterance, ButtonPressed, новая сессия, ping, отсутствие user/token, событие завершения linking. Проверить паузы и длинную реплику на реальной поверхности; не выдумывать допустимую длительность записи.
- [ ] В runbook зафиксировать результаты и ссылки на документацию из spec. Если связывание/маршрутизация не работает, закончить программные задачи на fixtures, но не публиковать доступ к личному vault с ослабленной авторизацией.

## 2. Выделить общий обработчик текста, сохранив аудиосценарий

**Files:** Create `backend/src/voice_gateway/text_turns.py`, `test_text_turns.py` рядом; modify `pipeline.py`, `app.py`, `knowledge/store.py`, `knowledge/git_sync.py`; tests `test_pipeline.py`, `knowledge/test_store.py`, `knowledge/test_git_sync.py`.

**Interfaces:**
- `TextTurnRequest(request_id, turn_id, context_id, client_id, channel, transcript, created_at, archive_dir)` — dataclass; channel `recorder|alice`, archive_dir `Path`.
- `TextTurnResult(reply, note, receipt, provider, model)` — dataclass; тип note берётся из существующего `HermesResponse`, receipt — существующий JSON writer или None.
- `TextTurnProcessor.process(request: TextTurnRequest) -> TextTurnResult` — async; общий экземпляр для обоих каналов.

- [ ] Зафиксировать тестами существующее поведение: capture, amend, query, plan/build, идемпотентность после TTS failure, фиксация истории один раз. Снять baseline `python -m pytest -q backend/src/voice_gateway`.
- [ ] Перенести участок Git/context/LLM/publish/history из `VoicePipeline.run` в сервис без изменения модели и prompt. Pipeline передаёт результат STT и получает текст для нынешнего TTS. Общие архивные файлы формирует сервис, аудиометаданные остаются в pipeline.
- [ ] Использовать context_id как прежний device_id для истории/активной идеи; сохранить channel/client_id в источнике. Request ID для Алисы всегда имеет префикс `alice:`. Внешний audio API продолжает проверять реальный device token.
- [ ] Последовательно обрабатывать один context_id; на весь сервисный вызов — deadline 180 s. Зафиксировать target_id при выборе контекста и сохранять вместе с ним для повторов. Не держать файловый lock в ожидании LLM. Для busy Git sync сделать ограниченное ожидание в рамках deadline.
- [ ] Тесты: два канала с одним контекстом видят одну последнюю идею; запрос с явным названием выбирает правильную; неоднозначный запрос требует уточнения; одновременные дополнения не теряются; внешняя ручная правка вызывает needs_review; инициализация канала recorder не теряет прежнюю историю.
- [ ] Выполнить тесты выше и полный backend suite; commit `refactor: share text processing between voice channels`, push.

## 3. Добавить устойчивую очередь Алисы и черновики

**Files:** Create `backend/src/voice_gateway/alice/{__init__,models,store,worker}.py`, `alice/test_store.py`, `alice/test_worker.py`; modify lifecycle в `app.py`.

**Interfaces:**
- `AliceStore(database: Path)`; `accept(event: AliceEvent) -> AliceReply`, `claim_next() -> AliceJob | None`, `complete(job_id: str, result: TextTurnResult) -> None`, `fail(job_id: str, code: str) -> None`, `recover_running() -> None`.
- `AliceEvent` содержит проверенный owner/context, ключ события, payload hash и действие диалога. `AliceJob` содержит TextTurnRequest и status. `AliceReply` — готовый ответ протокола.
- `AliceWorker(store, processor)` с async `start()/close()`, вызывает интерфейс задачи 2.

- [ ] Тестами задать атомарность: accept сохраняет событие, изменение черновика/задачу и ответ одной транзакцией; повтор возвращает прежний ответ; несовпадающий payload того же ключа отклоняется.
- [ ] Реализовать таблицы events/drafts/jobs. Предел 8 queued задач и один черновик на owner; sqlite busy timeout не более 150 ms для webhook-операций. SQLite операции выполнять вне event loop, чтобы долгий writer не блокировал webhook.
- [ ] Сохранять каждый фрагмент отдельно с порядком, временной меткой и ID события. Finish атомарно создаёт одну задачу, замораживает текст и закрывает draft. Лимит 12 000 символов проверять до изменения; переполнение не приводит к ложному подтверждению приёма.
- [ ] Worker читает задания из БД, а не полагается на in-memory очередь. На рестарте running возвращаются к обработке с теми же ID. Не сохранять OAuth-токены в заданиях или архивах.
- [ ] Тесты: crash после commit до HTTP-ответа, crash после publish до complete, дубли finish, пустой/слишком длинный draft, переполненная очередь, занятая БД, возврат к черновику в новой сессии. Во всех случаях исходный текст сохранён либо клиент явно не получил подтверждение.
- [ ] Запустить `python -m pytest -q backend/src/voice_gateway/alice/test_store.py backend/src/voice_gateway/alice/test_worker.py`; commit и push.

## 4. Добавить авторизацию и быстрый webhook

**Files:** Create `alice/auth.py`, `alice/api.py`, `alice/config.py`, `alice/test_auth.py`, `alice/test_api.py`; modify `app.py`, `.env.example`, `docker-compose.yml`.

**Interfaces:**
- `AliceAuthenticator.authenticate(token: str) -> AliceIdentity` — async, через httpx и Яндекс ID; identity содержит verified owner и context_id из серверной конфигурации.
- `POST /api/alice/webhook` принимает официальный envelope, возвращает AliceReply. `ALICE_ENABLED=false` отключает маршрут и worker.
- Конфигурация: `ALICE_ENABLED`, `ALICE_SKILL_ID`, `ALICE_ALLOWED_YANDEX_ID`, `ALICE_CONTEXT_DEVICE_ID`; пути БД выводятся из ARCHIVE_ROOT. Не добавлять отдельный LLM/STT/TTS config.

- [ ] Тесты доступа: неверный skill, отсутствующий/отозванный токен, чужой owner, подделка user_id, несовпадающие токены заголовка и тела. Недоступность Яндекс ID не открывает доступ. `/info` timeout 1 s, positive cache 60 s, токены в логах отсутствуют.
- [ ] Отсутствие авторизации возвращает официальный start_account_linking, только если поверхность поддерживает его; иначе инструкция открыть навык в приложении. Событие linking обрабатывать по актуальному fixture задачи 1. Ping получает безопасный ответ без доступа к данным.
- [ ] Ввести бюджет 2 s, лимит тела 64 KiB, 30 запросов/минуту на owner и общий ingress limit. Ошибки авторизации/очереди возвращают корректный безопасный ответ навыка. HTTP отмена после commit не удаляет принятое задание.
- [ ] Тестом с медленным LLM/Git 120 s доказать быстрый ответ webhook: они не вызываются в HTTP-обработчике. Отдельно проверить, что существующие device API не начинают принимать токены Алисы.
- [ ] Запустить тесты auth/api и полный backend suite; `docker compose config --quiet`; commit и push.

## 5. Реализовать диалог и выдачу результата

**Files:** Create `alice/dialogue.py`, `alice/render.py`, `alice/test_dialogue.py`, `alice/test_render.py`; modify `alice/api.py`, `alice/store.py`.

**Interfaces:** `route_utterance(request, state) -> AliceAction`; `render_reply(text: str, *, end_session: bool = False) -> AliceReply`. Action передаётся в AliceEvent задачи 3. Никаких LLM-вызовов для служебных команд.

- [ ] Зафиксировать fixtures для сценариев из spec: новая идея, многофразовая диктовка, дополнение, вопрос, план, помощь, статус, продолжение черновика и подтверждение отмены. Использовать original_utterance для содержания, command/intents только для служебных команд.
- [ ] На старте навыка — приветствие; не записывать активационную фразу. Команда «Запиши дословно: …» сохраняет остаток оригинального текста. Управляющие команды внутри содержательной фразы не исполняются.
- [ ] Для pending отвечать «Обрабатываю», для done — сохранённый reply, для failed/needs_review — понятная причина и возможность повторить после устранения. Повтор использует прежний request_id, не создавая новую идею. Выход сохраняет pending и draft.
- [ ] Ответы длиннее лимита делить по предложениям на части до 900 символов, выдавать продолжение командой «Дальше». Для обычных ответов использовать plain response.text без интерпретации LLM-текста как TTS-разметки; экранировать/очищать управляющие конструкции.
- [ ] Проверить экранные кнопки и голосовой сценарий без экрана, «Отмена» внутри мысли, цитирование чисел/отрицаний, чистую проверку связи без заметки, повтор статуса без повторной генерации.
- [ ] Запустить весь `alice/` suite и `test_text_turns.py`; commit и push.

## 6. Подготовить HTTPS и проверить полный сценарий

**Files:** Update `docs/alice-skill.md`, `docs/architecture.md`, `docs/index.md`, `.env.example`, `docker-compose.yml`; при необходимости create `deploy/alice.Caddyfile` и `deploy/test_alice_proxy.py`.

**Interfaces:** Публичный домен → только POST webhook → backend; внутренние API устройства сохраняют существующую доступность. Данные Caddy, если нужен, в `./data/caddy/`; stdout/stderr видны через существующий systemd unit/journald.

- [ ] Настроить точный маршрут reverse proxy с TLS и лимитами. Проверить, что `/api/voice/*`, `/docs`, `/metrics`, `/data/*` через публичный домен недоступны. Не менять сетевую изоляцию контейнера без необходимости.
- [ ] На отдельном временном vault с bare origin проверить полный набор: Alice capture → recorder amend; recorder capture → Alice query/plan; параллельные обращения; внешние Git-правки; конфликт; дубль webhook; рестарт worker. Заглушки STT/LLM/TTS не должны попадать в production-конфигурацию.
- [ ] Выполнить `python -m pytest -q backend/src/voice_gateway`, `docker compose config --quiet`, сборку backend, `git diff --check`; commit и push.
- [ ] Опубликовать приватный навык после модерации и пройти реальный разговор из приложения и колонки. Только затем включить ALICE_ENABLED на основном сервере, проверить заметку, wiki, commit/push и голосовой ответ диктофона отдельно.
- [ ] Зафиксировать latency webhook, успешное восстановление черновика/задачи и отсутствие личных данных в journald. Если домен/аккаунт не подготовлены, честно отделить пройденные локальные тесты от непроверенного облачного запуска.

## Что потребуется от владельца при реализации

Доступ к консоли Яндекс Диалогов и Яндекс ID под нужным аккаунтом; доступный
домен/HTTPS-маршрут к серверу; приложение Яндекса для привязки аккаунта;
колонка или телефон для проверки. API-ключ LLM, vault и Git SSH уже берём из
существующего deployment. Новый SpeechKit/STT/TTS ключ для навыка не нужен.
