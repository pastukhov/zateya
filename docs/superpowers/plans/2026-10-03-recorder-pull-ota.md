# Pull-OTA через контейнер PlatformIO — план реализации

> **For agentic workers:** Use `superpowers:executing-plans` to implement task-by-task. This document is a plan, not authorization to deploy firmware or evidence of hardware verification.

**Spec:** [TODO](../../../TODO.md), observations dated 2026-10-02 and user request dated 2026-10-03.

## Общие ограничения

- Рабочий репозиторий `/home/artem/repos/zateya`; перед изменениями проверить ветку, status и подтянуть изменения без потери чужих правок.
- Стадия прототипа: не создавать слой миграций и совместимости старых протоколов.
- Не выдавать ключи, токены и сохранённые адреса в setup, логи или метрики.
- Все новые пользовательские сообщения по-русски; Затея — женского рода.
- Каждый программный этап: воспроизводящий тест → ожидаемое падение → реализация → зелёные проверки → отдельный commit и push по AGENTS.md.
- Host-тесты и успешная сборка не доказывают работу реального устройства. Аппаратные пункты оставлять открытыми до проверки.
- Команды firmware запускать из `firmware/`: `pio test -e native`, `pio run -e sticks3`. Сначала проверить доступный PlatformIO и Python, не переиспользовать сломанное окружение после обновления Python.

**Goal:** Собирать прошивку в Compose и позволить устройству самостоятельно безопасно получать опубликованное обновление при старте.

**Architecture:** Одноразовый builder создаёт неизменяемый подписанный релиз в общей папке; backend отдаёт манифест и образ; устройство пишет неактивный OTA-слот, проверяет образ и подтверждает запуск либо откатывается.

**Tech Stack:** C, ESP-IDF 5.5.3, PlatformIO, Python/FastAPI, Docker Compose.

## Что можно сейчас / что требует USB

Сейчас: контейнер сборки, формат релиза, подпись, endpoint, клиентская логика,
новая разметка, тесты и target build. Публикация для автоматической установки —
только после аппаратной проверки кандидата.
USB обязательно для первой установки OTA-capable прошивки и таблицы разделов.
Текущий `partitions.csv` содержит только factory 3 МиБ, OTA-слотов и otadata нет.
План не предусматривает удалённое изменение bootloader или partition table.

## Проверенные источники и исходные условия

ESP-IDF 5.5.3 требует два OTA app-слота и otadata. При включённом rollback
новое приложение должно подтвердить запуск; иначе следующий boot возвращает
предыдущую версию. Источники:
[OTA](https://docs.espressif.com/projects/esp-idf/en/v5.5.3/esp32s3/api-reference/system/ota.html),
[HTTPS OTA](https://docs.espressif.com/projects/esp-idf/en/v5.5.3/esp32s3/api-reference/system/esp_https_ota.html).
В PlatformIO заявлено 8 МиБ flash; фактический размер подтвердить по USB.

## Файлы и интерфейсы

Создать `deploy/firmware/Dockerfile`, `build-release.py`, `test_release.py`,
`backend/src/voice_gateway/firmware_updates/{api,manifest,test_api}.py`,
`firmware/include/voice_ota.h`, `firmware/src/voice_ota_policy.c`,
`voice_ota_esp.c`, `firmware/test/test_ota_policy/test_ota_policy.c`.
Изменить Compose, `.dockerignore`, `.gitignore`, `deploy/prepare-data.sh`,
`app.py`, `firmware/partitions.csv`, `sdkconfig.defaults`, CMake, `platformio.ini`,
`main.c`, display/power policy; ESP-адаптер исключить из native build.

Предлагаемый контракт v1: манифест `schema=1`, `board=sticks3`,
`layout=ota-v1`, `release_seq` (положительное целое), `git_revision`,
`size`, `sha256`, `image_path`, `key_id`. Упаковка: base64 точных байтов JSON
манифеста + base64 подпись. Подписывается SHA-256 этих байтов; ECDSA P-256,
DER signature, проверка через mbedTLS. Публичный ключ в firmware; приватный
ключ только в файле секретов builder, не в backend/репозитории/образе.
Утверждение алгоритма завершить небольшой compile/proof test до полной разработки.

## Review Focus

Потеря питания, злонамеренный/битый образ, одновременные сборки, низкий заряд,
бесконечная повторная установка неудачного релиза. Каждому случаю ниже соответствует проверка.

## Этап 1 — сейчас: пригодность flash и подписи

- [ ] Собрать текущую прошивку и записать реальный размер app. Проверить 3 МиБ на слот с запасом под подпись/рост; если не помещается, остановить публикацию и пересмотреть layout.
- [ ] Кандидат разметки 8 МиБ: сохранить nvs `0x9000/0x6000`, phy `0xf000/0x1000`; otadata `0x10000/0x2000`; ota_0 `0x20000/0x300000`; ota_1 `0x320000/0x300000`; остаток пока не выделять. Factory убрать. Автотест проверяет выравнивание, отсутствие пересечений и границу flash.
- [ ] Включить `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`, проверить собранную конфигурацию. Не прожигать eFuse и не включать аппаратный anti-rollback в рамках POC.
- [ ] Проверить на host и target fixture: правильная подпись принимается, изменённые байты/ключ/DER отклоняются. Это проверка подлинности OTA на уровне приложения, не замена hardware Secure Boot при физическом доступе.

## Этап 2 — сейчас: builder и публикация

- [ ] Добавить Compose service `firmware-builder` в профиль `firmware`, `restart: no`, без privileged, USB, host network и Docker socket. Зафиксировать PlatformIO/toolchain согласно текущему platformio.ini.
- [ ] Маунты только рядом с compose: `./data/firmware` для релизов, `./data/pio` для cache, `./data/firmware-signing` для закрытого ключа (read-only builder). Backend получает `./data/firmware` read-only, ключ не получает.
- [ ] Builder использует снимок текущего checkout, не делает сам `git pull`. Проверить `.dockerignore`: firmware не исключена, `.env` и credentials исключены. Не вшивать Wi-Fi, VPN, device token или server URL в образ; настройки берутся из NVS/setup.
- [ ] Команда `docker compose --profile firmware run --rm firmware-builder` собирает `pio run -e sticks3`, проверяет размер и создаёт candidate в `releases/<release_seq>/`. Входы сборки: revision и release_seq, без секретов окружения всего backend.
- [ ] Публикация отдельной явной командой `build-release.py publish <release_seq>`: lock, проверка подписи/sha256/размера и атомарная замена указателя `stable.json` через rename. Backend никогда не видит полуготовый релиз. Повторный seq с другим digest запрещён.
- [ ] Тесты: упавшая сборка не меняет stable; параллельная публикация сериализована; image immutable; приватный ключ/секреты не попадают в артефакты. Cache и результаты переживают пересоздание контейнера.

## Этап 3 — сейчас: backend-раздача

- [ ] `GET /api/firmware/manifest?board=sticks3&layout=ota-v1&current_seq=N`: авторизация как у voice API; 204 если нет более новой совместимой версии, 200 с подписанным envelope иначе. Неверные board/layout → 204 без прошивки.
- [ ] `GET /api/firmware/images/<sha256>.bin`: только проверенный hash из релиза, стандартный Content-Length, ETag=hash, потоковая отдача. Отклонять traversal и redirects, не разрешать произвольный URL из манифеста.
- [ ] Не публиковать endpoints через alice-proxy/KeenDNS: его whitelist остаётся прежним. Устройство использует настроенный адрес backend и существующий транспорт Wi-Fi/VPN. Подпись проверяется независимо от транспорта; bearer по HTTP имеет те же ограничения, что текущий voice API.
- [ ] Проверки: 401 без токена, неизвестный hash 404, несовместимый/старый seq 204, битый/неполный release не публикуется, одновременное чтение и publish согласованы. Проверить streaming крупного файла без чтения целиком в RAM.
- [ ] `pytest -q backend/src/voice_gateway/firmware_updates deploy/firmware`, `docker compose config --quiet`, clean container build и получение candidate тестовым клиентом. Commit/push; автоматическую установку ещё не объявлять проверенной.

## Этап 4 — сейчас: pull-клиент

- [ ] Чистая policy с состояниями idle/checking/deferred/downloading/verifying/reboot/pending_verify/failed. Проверка один раз после готовности сети на boot/wake, не в setup AP; ошибка сервера не блокирует обычную работу.
- [ ] Manifest timeout 5 секунд. Скачать только совместимый новый seq с доверенной подписью и размером не больше OTA-раздела; image_path строго относительный из того же backend. SHA-256 и размер проверить до переключения boot partition.
- [ ] Первая версия: без HTTP Range/resume; после обрыва abort неактивного слота, новая попытка с начала при следующем старте. Полный download ограничить 10 минутами; не удерживать бодрствование бесконечно.
- [ ] Проверять питание: USB либо батарея >=50%; неизвестный заряд — отложить. Не начинать при recording/playback/recovery. OTA имеет общий mutex активности; во время записи flash запретить сон/начало записи, показывать «ОБНОВЛЯЮ» и процент.
- [ ] Низкий заряд/недоступность backend откладывают обновление без ошибки записи. Автообновление выполняется только для явно опубликованного stable-релиза.
- [ ] Потоково писать через `esp_ota_begin/write/end`, отменять на ошибке, затем `esp_ota_set_boot_partition`; никоим образом не обновлять активный слот, bootloader или таблицу разделов по сети.
- [ ] После boot pending_verify: локальный self-test NVS, памяти, дисплея, микрофона и работоспособности event loop. Подтверждение за 30 секунд не должно зависеть от доступности интернета. На локальной критической ошибке откат; watchdog защищает зависший self-test.
- [ ] Перед переключением сохранять attempted seq; при обнаружении отката помечать его rejected. Не устанавливать снова тот же отвергнутый релиз на каждом wake; нужна публикация более нового seq. Тесты на успешный upgrade и reboot loop.
- [ ] Fake-тесты всех переходов, bad signature/hash/size, power loss, busy race, отсутствующего интернета, rejected seq. Native tests и sticks3 build; commit/push.

## Этап 5 — только с USB: первичная установка и аварийные сценарии

- [ ] Проверить реальный flash ID/размер и текущую таблицу. Локально сохранить восстановимый backup flash/NVS с правами 0600, не коммитить его. Не делать erase-all без необходимости.
- [ ] Установить bootloader, новую таблицу и начальный OTA app по USB, проверить сохранность настроек и ручное восстановление USB. Это контролируемая первоначальная установка, не runtime-миграция конфигурации.
- [ ] Два разных тестовых образа: успешный A→B; B с намеренной ошибкой self-test откатывается к A и не переустанавливается циклически.
- [ ] Прервать Wi-Fi и питание при download/записи, после выбора нового boot slot и до подтверждения. После каждого случая устройство запускает рабочий образ, NVS не повреждается.
- [ ] Проверить заряд ниже порога, отсутствие backend, начало записи одновременно с OTA, короткие wake/sleep циклы, mobile VPN. Сверить отображение и диагностические отчёты.
- [ ] Лишь после матрицы опубликовать stable для повседневного автообновления. Отдельно записать аппаратно проверенный commit, release_seq, layout и процедуру аварийного восстановления.
