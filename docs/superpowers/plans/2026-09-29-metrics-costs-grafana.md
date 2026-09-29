# Метрики, расходы и Grafana — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Предназначено для последовательного исполнения Sol; Luna — отдельные задачи после проверки интерфейсов. Не запускать других агентов без явного запроса пользователя.

**Goal:** Показывать состояние Затеи, расходы на обработку и стоимость заметок в существующей Grafana.

**Architecture:** Backend экспортирует Prometheus `/metrics`; существующий vmagent собирает их в VictoriaMetrics, Grafana отображает дашборд. Отдельный SQLite-журнал хранит факты внешних вызовов и завершения пользовательских задач, переживает перезапуски и служит источником финансовых агрегатов. Никаких новых Grafana/Prometheus-контейнеров.

**Tech Stack:** Python, FastAPI, sqlite3, Decimal, prometheus_client, pytest/httpx.MockTransport, VictoriaMetrics/vmagent, Grafana JSON.

**Spec:** Требования и принятые решения полностью приведены ниже; источник — Obsidian `Затея/ideas/Метрики и дашборд в Grafana для ИИ-диктофона.md` и связанные исходные диктовки. Пользователь согласовал первым этапом сервер, расходы и дашборд; прошивка и телеметрия устройства — отдельный будущий этап.

## Требования и границы

- Два канала: `alice`, `recorder`. Один сервер и общий Obsidian vault.
- Видеть число задач, ошибки, длительности этапов, очередь, Git-синхронизацию, расходы на LLM/STT/TTS, общую сумму и среднюю стоимость заметки.
- Существующие метрики находятся в `backend/src/voice_gateway/metrics.py`, `/metrics` подключён в `app.py`. Часть метрик объявлена, но не обязательно подключена к реальному пути; сначала проверить точки обновления.
- Запрос пользователя, HTTP polling, вызов провайдера и изменение заметки — разные сущности. Не считать GET статуса и healthcheck платными запросами.
- Фактическая стоимость принимается только из документированного поля провайдера с известной валютой. Не угадывать значение произвольного поля `cost` и не считать USD по умолчанию.
- Если провайдер не отдаёт стоимость, оценивать только по явно заданным тарифам и доступным единицам usage. При неполных данных — `unknown`. Фактическое и оценочное отображать раздельно.
- Расходы начинаются с внедрения. Не восстанавливать прошлые расходы из числа заметок. В дашборде показывать дату начала учёта.
- При сбое учёта не терять диктовку: продолжить обработку, увеличить метрику ошибки учёта, записать безопасный лог. Дашборд предупреждает о неполноте данных.
- Установка дашборда и scrape-конфига не должна менять посторонние настройки мониторинга.

## Global Constraints

- Репозиторий `/home/artem/repos/zateya`, сервер `root@192.168.11.2:/opt/zateya`. Перед работой проверить AGENTS.md, git status и актуальность main. Не включать пользовательские файлы в коммиты.
- Все новые постоянные данные внутри существующего bind mount `data/`; журнал `data/archive/usage.sqlite3`. Не создавать Docker named volumes.
- Не менять LLM_BASE_URL/LLM_API_KEY и действующие модели. Не добавлять отдельные STT/TTS ключи и адреса. Не печатать .env, OAuth, заголовки авторизации и транскрипты в диагностике.
- Не открывать `/metrics` через KeenDNS. Публичный alice-proxy по-прежнему допускает только POST webhook.
- Не добавлять совместимость/миграции прототипа. Новая отдельная БД создаётся с чистой схемой; существующие БД и архивы не удалять.
- Не увеличивать время ответа webhook и не ждать финансовых запросов к провайдеру внутри webhook. Сбор usage выполняется там, где уже выполняется внешний вызов.
- Labels: только channel, stage, configured model, outcome, operation, cost_kind, currency. Никаких turn_id, session_id, title, текста, URL и произвольного ответа провайдера в labels.
- Каждый этап: сначала тест и ожидаемое падение, затем минимальная реализация, полный `python -m pytest backend -q`, `git diff --check`, коммит и push текущей задачи. Непройденные тесты не скрывать.

## Review Focus

1. Повтор события, кэш и перезапуск не удваивают затраты; настоящий повторный HTTP-вызов провайдера учитывается отдельно — задачи 1, 3.
2. Валюта/цена/usage отсутствуют или повреждены: unknown, без ложного нуля и смешения валют — задача 2.
3. Запрос оплачен, но JSON невалиден или публикация не удалась: расход остаётся — задачи 3, 4.
4. Заметка сохранена, TTS упал; query/amend/capture имеют разные знаменатели стоимости — задачи 4, 5.
5. SQLite занята/диск недоступен и несколько потоков записывают одновременно: диктовка не ломается, неполнота видна — задачи 1, 6.

## Карта файлов и интерфейсы

Создать пакет `backend/src/voice_gateway/usage/`:
- `models.py`: неизменяемые dataclass `CallContext(turn_id: str, channel: str, stage: str, model: str)`, `UsageObservation(input_tokens: int | None, output_tokens: int | None, audio_seconds: Decimal | None, text_characters: int | None, reported_amount: Decimal | None, reported_currency: str | None)`, `Cost(amount: Decimal | None, currency: str | None, kind: str)`.
- `pricing.py`: загрузка тарифов, проверка usage, `price_usage(stage: str, model: str, usage: UsageObservation, rates: dict) -> Cost`.
- `store.py`: `UsageStore(path: Path)`, `initialize()`, `begin_call(context: CallContext) -> str`, `finish_call(call_id: str, *, outcome: str, elapsed_seconds: float, usage: UsageObservation, cost: Cost) -> None`, `finish_turn(turn_id: str, *, channel: str, outcome: str, operation: str, note_saved: bool) -> None`, `snapshot() -> dict`. call_id — UUID физической попытки HTTP.
- `recorder.py`: `UsageRecorder` с теми же операциями записи, безопасно перехватывающий только ошибки учёта; не подавлять ошибки провайдера. `begin_call` может вернуть None при сбое, `finish_call(None, ...)` не падает.
- `collector.py`: пользовательский Prometheus collector, читает агрегаты SQLite, без SQL-записи во время scrape.
- `test_store.py`, `test_pricing.py`, `test_collector.py`.

Изменять существующие точки: `app.py`, `metrics.py`, `text_turns.py`, `pipeline.py`, `agents/openai_client.py`, `stt/client.py`, `tts/openai_compatible.py`, `alice/worker.py`, `knowledge/git_sync.py`. Проверить фабрики клиентов и базовые классы перед передачей новых необязательных аргументов; обновить fake providers и вызывающие тесты.

## Task 1: Постоянный журнал попыток и задач

- [ ] Создать тесты `test_store.py`: reopen сохраняет сумму; два finish одного call_id не меняют сумму; два begin одного turn_id создают две оплачиваемые попытки; конкурентные записи не теряются; разные валюты не объединяются.
- [ ] Запустить `python -m pytest backend/src/voice_gateway/usage/test_store.py -q`, увидеть падение из-за отсутствующей реализации.
- [ ] Реализовать models/store: таблицы calls и turns, PRIMARY KEY call_id/turn_id, транзакции, WAL, busy_timeout 150 ms. Денежные значения хранить десятичным текстом; суммировать Decimal, не SQLite float SUM. У calls состояние started/finished; незавершённый после рестарта вызов считать неизвестной стоимостью, не успешным нулём. Не делать повторный платный вызов ради восстановления учёта.
- [ ] Добавить UsageRecorder и тест, что ошибка SQLite не прерывает работу вызывающего кода; счётчик `zateya_usage_write_errors_total` и безопасный лог содержат только тип ошибки.
- [ ] Проверить тесты, полный backend, diff; commit/push `feat: persist provider usage and turn accounting`.

## Task 2: Тарифы и нормализация стоимости

- [ ] Посмотреть официальную документацию фактически настроенного провайдера (сейчас RouterAI), сохранить ссылки и дату в `docs/monitoring.md`. Проверять только разрешённые поля usage; не копировать ключи. Если денежное поле не документировано, оставить reported unsupported и использовать оценки/unknown.
- [ ] Создать `deploy/pricing.example.json`: version=1, rates — список объектов stage/model/currency/unit/price. Поддержать только units `input_tokens_1m`, `output_tokens_1m`, `audio_minute`, `text_characters_1m`. Пример без фиктивных рабочих цен, пустой rates и пояснение в docs. Локальный `data/pricing.json` подключить read-only; отсутствие файла допустимо, означает unknown. Использовать существующий data mount если доступен, иначе не создавать обязательный пустой mount-файл.
- [ ] Тесты: input=1000/output=500 при ценах 1/2 за миллион дают 0.002; 30 секунд по 0.01 за минуту дают 0.005; reported имеет приоритет; missing output при input/output тарифе => unknown; 0 расход действителен только явно; отрицательные/NaN/Infinity/bool/неизвестные единицы запрещены; валюты не конвертируются.
- [ ] Реализовать pricing с Decimal; частичные известные токены экспортировать даже при unknown цене. Тариф фиксировать в записи попытки, изменение конфига не пересчитывает историю.
- [ ] Полные тесты, diff; commit/push `feat: calculate explicit provider cost estimates`.

## Task 3: Подключение реальных LLM/STT/TTS вызовов

- [ ] Написать MockTransport-тесты в существующих test_openai_client.py, stt/test_client.py, tts/test_openai_compatible.py: один реальный POST = одна попытка; repair JSON = отдельная попытка; кэш и повтор webhook без POST = ноль новых попыток; HTTP error/timeout/невалидный JSON учитываются; usage сохраняется до проверки смыслового контракта.
- [ ] Передать один UsageRecorder из app.py в клиенты. CallContext явно передавать к месту HTTP-вызова; у STT добавить необязательный keyword context и обновить base/fake и вызов в pipeline. У TTS использовать явный context, не выводить канал из device_id. LLM получает канал/turn_id через AgentRequest (добавить поля с безопасными defaults и обновить конструкторы). Не использовать изменяемый глобальный current_turn.
- [ ] Оборачивать каждую физическую попытку begin/finally finish; не записывать завершение второй раз. В LLM различать initial/repair в журнале, но stage остаётся llm. Успешный HTTP с невалидным model content может быть платным.
- [ ] STT длительность брать из исходного WAV, TTS число символов из отправленного input; usage ответа предпочтительнее локальных единиц при совпадающей документированной семантике. Если тариф провайдера зависит от токенов, а TTS вернул только bytes, не переводить символы в токены эвристикой.
- [ ] На timeout после отправки outcome=timeout, цена unknown, даже если известен тариф: факт списания неизвестен. Не делать скрытых billable запросов для уточнения.
- [ ] Полные тесты, diff; commit/push `feat: record usage across speech and language providers`.

## Task 4: Метрики рабочих процессов и семантика заметки

- [ ] Добавить тесты общего TextTurnProcessor/worker/pipeline: success/failure/cancel в обоих каналах; busy Git ожидается и не считается ошибкой; query не создаёт заметку; needs_review не считается saved; amend не увеличивает число новых заметок; TTS failure после capture сохраняет факт созданной заметки.
- [ ] Обновлять turns один раз по turn_id. `operation` брать из подтверждённого receipt, не из текста ответа модели; перечисление capture/amend/query/none. note_saved=true только после фактической публикации capture/amend. Общий processor фиксирует операцию записи, внешний pipeline фиксирует итог после TTS, AliceWorker — после обработки. UPSERT не стирает уже подтверждённый факт note_saved при последующей ошибке.
- [ ] Добавить series: `zateya_turns_total{channel,outcome}`, `zateya_notes_total{channel,operation}`, `zateya_stage_duration_seconds{channel,stage,outcome}`, `zateya_alice_jobs{status}`, `zateya_git_sync_total{status}`, `zateya_git_last_success_timestamp_seconds`, `zateya_git_lock_wait_seconds`. Stage enum stt/llm/tts/git_refresh/publish; outcome success/error/timeout/cancelled. Очередь gauge читать из SQLite; status ограничен состояниями очереди.
- [ ] Финансовые cumulative series из SQLite: `zateya_provider_cost_total{channel,stage,model,currency,cost_kind}`, `zateya_provider_calls_total{channel,stage,model,outcome}`, `zateya_usage_unknown_total{channel,stage,model}`, `zateya_usage_tokens_total{channel,stage,model,direction}`, `zateya_accounting_started_timestamp_seconds`.
- [ ] Для средней стоимости успешно созданной заметки дать отдельные `zateya_completed_note_cost_total{channel,currency,cost_kind}` и `zateya_completed_notes_costed_total{channel,currency,cost_kind}`. Включать только завершённые capture с полностью известной ценой всех попыток; mixed actual/estimated считать estimated. Amend отдельно как обновления. Отображать число исключённых неполных capture. Метрику «все расходы / все созданные заметки» можно показать отдельно как операционную себестоимость, не подменять ею среднюю цену успешного capture.
- [ ] Один источник на series; не инкрементировать в памяти и одновременно читать тот же counter из БД. Существующие метрики не переименовывать массово. SQLite работу в async-пути выносить в to_thread; scrape не вызывает внешних сетевых запросов.
- [ ] Полные тесты, diff; commit/push `feat: expose workflow and persistent cost metrics`.

## Task 5: Дашборд и конфигурация сбора

**Files:** `deploy/grafana/zateya.json`, `deploy/monitoring/zateya-scrape.yml`, `deploy/test_monitoring.py`, `docs/monitoring.md`.

- [ ] JSON дашборда UID `zateya`, русские заголовки, переменная datasource типа prometheus (совместима с VictoriaMetrics), фильтры channel/currency, диапазон по умолчанию 24h. Никаких паролей и жёстко заданного UID чужого datasource.
- [ ] Панели: up, частота/доля ошибок задач, p50/p95 этапов, очередь Алисы, последняя успешная синхронизация, reported и estimated расходы раздельно по стадиям, неизвестные расходы, текущая накопленная сумма, расходы за выбранный период, средняя цена capture и количество исключённых записей, количество capture/amend/query.
- [ ] Использовать increase(counter[$__range]) для периода, rate(...[$__rate_interval]) для скорости; percentile через histogram_quantile и sum by(le,stage). Средняя цена — отношение increase соответствующих cost/count при count>0, отсутствие знаменателя показывать «нет данных», не бесконечность/ноль. Не складывать валюты. Для начала сбора показать предупреждение: первый scrape не позволяет восстановить точную временную историю.
- [ ] Scrape job `zateya`, target `192.168.11.2:7070`, path /metrics, interval 15s, timeout 5s; уточнить фактический LAN порт до применения. Сохранить как пример отдельного job, не заменять основной конфиг vmagent.
- [ ] Тестировать json parsing, обязательные панели, все используемые имена metrics присутствуют в fixture scrape, переменные datasource, отсутствие секретов. Проверить несколько PromQL на реальной VictoriaMetrics после развёртывания; JSON lint сам по себе не доказывает корректность запросов.
- [ ] Полные backend и `python -m pytest deploy/test_monitoring.py -q`, diff; commit/push `feat: add Zateya Grafana dashboard and scrape configuration`.

## Task 6: Интеграционная проверка и развёртывание

- [ ] Тест со временными vault/БД и MockTransport: capture recorder (STT+LLM+TTS), capture Alice (только LLM), amend/query, невалидный LLM с repair, TTS failure, повтор webhook, restart и одновременный scrape. Проверить суммы/число попыток/заметки и отсутствие секретов в export.
- [ ] Выполнить `python -m pytest backend deploy/test_monitoring.py -q`, `git diff --check`, Compose config без вывода интерполированных секретов (`docker compose config --quiet`). Обновить README.md/README.en.md ссылкой на docs/monitoring.md.
- [ ] На сервере сначала выяснить способ конфигурирования vmagent и Grafana через mounts/аргументы конкретных контейнеров. Не выводить environment целиком. Снять резервную копию только изменяемого файла конфигурации, не копировать секреты в репозиторий.
- [ ] Обновить backend обычным git pull/build/restart; проверить health и локальный /metrics. Проверить публичный /metrics через KeenDNS возвращает 404. Встроить один scrape job в существующую конфигурацию, reload поддержанным способом. Не перезапускать весь мониторинг без необходимости.
- [ ] Импортировать дашборд через доступный аутентифицированный Grafana API/UI. Если доступа нет — подготовить JSON и точную инструкцию импорта, сообщить блокер; не менять пароль и не создавать новую Grafana.
- [ ] Проверить up=1, запросы панелей без ошибок. При отсутствии реального usage показывать «нет данных». Платный пользовательский E2E выполнять только на согласованной тестовой диктовке, не создавать тестовую заметку в боевом vault молча.
- [ ] Зафиксировать в docs/monitoring.md фактически проверенные уровни: unit/integration, server scrape, Grafana, реальный провайдер; непроверенное явно перечислить. Commit/push.

## Приёмка и откат

Готово: оба канала видны, дашборд использует реальные series, деньги переживают restart без удвоения, unknown отличим от 0, ошибки наблюдаемости не ломают диктовку. У пользователя есть ссылка на установленный дашборд либо честно указан блокер импорта.

Откат: вернуть предыдущий backend image/commit, убрать только добавленный scrape job и dashboard UID zateya. Сохранить usage.sqlite3 и vault. Не удалять пользовательские заметки и не менять сетевую изоляцию.

## Передача исполнителю

Рекомендуется Sol: наиболее сложны семантика оплаты, идемпотентность и привязка к опубликованным заметкам. Luna подходит для задачи 5 после реализации и фиксации метрик. Исполнять последовательно, не менять финансовые определения ради зелёных тестов. Этот документ — план, реализация и развёртывание ещё не выполнены.
