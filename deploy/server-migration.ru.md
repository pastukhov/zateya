# Переезд сервера на OpenAI-совместимый LLM

Инструкция обновляет существующую установку в `/opt/zateya`. Она не подключается к серверу и не выполняет команды за администратора.

## Что будет запущено

Один контейнер `backend` выполняет цепочку STT → LLM → проверка и запись в Obsidian → TTS. Внутри gateway также работает фоновая публикация изменений Obsidian в Git. Отдельный контейнер Codex/agent больше не нужен.

Постоянные каталоги находятся рядом с Compose: `data/archive`, `data/obsidian` и `data/ssh`. В `data/obsidian` лежит существующий vault с `.git`. Каталог `data/ssh` подключается в контейнер только для чтения.

## Подготовка и резервная копия

Остановите текущую службу и Compose-проект, чтобы во время обновления vault не записывали два процесса:

```sh
cd /opt/zateya
sudo systemctl stop zateya
docker compose -p zateya down --remove-orphans
```

Не добавляйте `-v`: тома удалять не нужно. Создайте защищённую резервную копию архива, vault и `.env` перед обновлением. Например, каталог резервной копии должен быть доступен только root:

```sh
sudo install -d -m 700 /root/zateya-before-llm
sudo cp -a data/archive data/obsidian data/ssh /root/zateya-before-llm/
sudo cp -a .env /root/zateya-before-llm/
sudo chmod 600 /root/zateya-before-llm/.env
```

Сохраните также старые `data/codex` и `data/agent`, если они есть. Новая версия их не использует и автоматически не удаляет.

## Обновление конфигурации и кода

Обновите checkout и подготовьте `.env` по актуальному шаблону:

```sh
cd /opt/zateya
git pull --ff-only origin main
cp .env.example .env.new
```

Перенесите в `.env.new` действующие STT/TTS/device-token настройки из прежнего `.env`, затем задайте параметры LLM и UID/GID. После проверки замените `.env` и ограничьте права:

```sh
mv .env.new .env
chmod 600 .env
```

Задайте `LLM_BASE_URL`, `LLM_MODEL`, при необходимости `LLM_API_KEY`, `LLM_RESPONSE_FORMAT`, а также модели `STT_MODEL` и `TTS_MODEL`, `ZATEYA_UID` и `ZATEYA_GID`. Один `LLM_API_KEY` используется для LLM, STT и TTS. Не задавайте `VOICE_AGENT_PROVIDER`, `CODEX_*` или `HERMES_*`: это не настройки новой версии.

`LLM_BASE_URL` включает префикс API; gateway добавляет только `/chat/completions`. Примеры формы URL: `https://api.openai.com/v1`, `https://openrouter.ai/api/v1`, `http://ollama:11434/v1`. Это примеры адресов API, а не рекомендация конкретной модели. Расходы LLM оплачиваются отдельно от STT/TTS. Проверка готовности gateway не отправляет платный запрос и не проверяет ключ у провайдера.

## SSH-ключ Git publisher

Проверьте содержимое `data/ssh` до создания ключа. Не перезаписывайте существующий приватный ключ. Если ключа ещё нет, создайте отдельный deploy key для vault, добавьте его публичную часть в настройки GitHub-репозитория и установите права `0600` на приватный ключ и `0700` на каталог. `known_hosts` должен содержать ключ хоста, полученный и проверенный доверенным способом; не принимайте его вслепую через непроверенный `ssh-keyscan`. Не печатайте приватный ключ и не помещайте его в Git.

## Сборка и права на данные

Проверьте Compose, соберите образ и подготовьте bind-каталоги:

```sh
docker compose -p zateya config --quiet
docker compose -p zateya build backend
./deploy/prepare-data.sh
```

Скрипт читает UID/GID из итоговой конфигурации Compose, отказывает при UID 0, создаёт нужные каталоги и исправляет root-owned данные, не удаляя содержимое. Он не следует по символьным ссылкам и не создаёт пустые SSH-ключи. Убедитесь, что vault и его `.git` доступны на запись контейнерному UID/GID, а SSH-каталог остаётся закрытым от записи контейнера.

База локальной истории создаётся пустой. Старые заметки и архив сохраняются, но диалоги Codex не переносятся.

## Запуск и проверка

Установите обновлённый unit, затем запустите службу:

```sh
sudo install -m 644 deploy/zateya.service /etc/systemd/system/zateya.service
sudo systemctl daemon-reload
sudo systemctl enable --now zateya
docker compose -p zateya ps
docker compose -p zateya logs --tail=100 backend
```

Проверьте локальные `/health/live` и `/health/ready`. Для статуса Git используйте авторизованный `GET /api/voice/knowledge/git` с заголовками `X-Device-Id` и `Authorization: Bearer …`; endpoint возвращает статус публикации, а не содержимое заметок.

Затем сделайте содержательную диктовку, отдельное дополнение и вопрос к базе. Проверьте файл, ссылки и Git push в Obsidian. Одного HTTP 200 недостаточно, чтобы оценить качество выбранной модели.

## Откат

Остановите службу, восстановите прежний checkout или образ и прежний `.env`, затем запустите прежнюю Compose-конфигурацию. Не удаляйте данные и не накатывайте резервную копию поверх более новых заметок без проверки. Во время переключения должен работать только один процесс, записывающий vault.
