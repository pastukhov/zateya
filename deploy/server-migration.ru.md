# Перенос Затеи на Linux-сервер

На сервере запускается один `docker-compose.yml`: Gateway и Codex Agent.
Все постоянные данные находятся в папке `data/` рядом с ним. Нужны Linux
(x86-64), Docker Engine с Compose, Git, SSH, доступ к OpenAI и GitHub.
Порт 8080 разрешайте только из доверенной LAN/WireGuard, не из Интернета.

## 1. Подготовить сервер

Войдите под пользователем, который будет владеть `/opt/zateya` и `data/`.
Настройте ему доступ к GitHub по SSH. Создайте каталог для проекта:

```sh
ssh -T git@github.com
sudo mkdir -p /opt/zateya
sudo chown "$(id -u):$(id -g)" /opt/zateya
git clone git@github.com:pastukhov/zateya.git /opt/zateya
cd /opt/zateya
mkdir -p data/archive data/obsidian data/agent data/codex data/ssh
chmod 700 data data/agent data/codex data/ssh
cp .env.example .env
```

Если переносите проект с ноутбука целиком через `rsync`, используйте после
создания `/opt/zateya` эту команду **вместо** `git clone` и `cp`:

```sh
rsync -a /home/artem/repos/zateya/ USER@SERVER:/opt/zateya/
```

Она скопирует также скрытый `.env` и историю Git. На сервере затем создайте
недостающие каталоги `data/archive`, `data/obsidian`, `data/agent`,
`data/codex`, `data/ssh` и установите для них права, как показано выше.

Агент внутри контейнера работает под UID/GID из `.env` (`ZATEYA_UID` и
`ZATEYA_GID`, по умолчанию `1000:1000`). Не подставляйте `id -u`/`id -g`
сеанса `root`: так агент тоже запустится от root. `OBSIDIAN_GROUP_ID` должен
совпадать с GID агента, чтобы backend мог записывать в vault. Задайте
действующие STT/TTS-ключи, `VOICE_DEVICE_TOKENS` и общий для двух контейнеров
`CODEX_AGENT_TOKEN`. Права `.env` — `chmod 600 .env`.

Для push Obsidian создайте отдельный ключ, выдав ему право записи **только**
в репозиторий `pastukhov/obsidian` через GitHub → Settings → Deploy keys:

```sh
ssh-keygen -t ed25519 -f data/ssh/id_ed25519 -N '' -C zateya-obsidian
cp ~/.ssh/known_hosts data/ssh/known_hosts
chmod 600 data/ssh/id_ed25519 data/ssh/known_hosts
cat data/ssh/id_ed25519.pub
```

В GitHub добавьте выведенный **публичный** ключ с `Allow write access`.
Приватный ключ остаётся только в `data/ssh`, исключённой из Git.
`known_hosts` должен содержать проверенный ключ GitHub после `ssh -T`.

## 2. Перенести данные с ноутбука

Выберите момент, когда диктофон не обрабатывает запись. На ноутбуке остановите
старые службы, чтобы получить согласованный снимок:

```sh
systemctl --user stop codex-voice-agent.service
cd /home/artem/repos/zateya
docker compose -p hermes-echo --env-file /home/artem/.hermes/.env --env-file .env stop backend
```

Скопируйте **весь** `/home/artem/repos/obsidian/` в
`/opt/zateya/data/obsidian/` на сервере, включая `.git`, `.obsidian` и
незакоммиченные записи `Затея/sources`. Одного `git clone` недостаточно.
Архив из старого Docker volume перенесите через tar:

```sh
mkdir -p ~/zateya-transfer
chmod 700 ~/zateya-transfer
docker run --rm -v hermes-echo_archive_data:/data:ro \
  -v "$HOME/zateya-transfer:/backup" alpine:3.20 \
  tar -C /data -czf /backup/archive.tgz .
rsync -a /home/artem/repos/obsidian/ USER@SERVER:/opt/zateya/data/obsidian/
rsync -a ~/zateya-transfer/archive.tgz USER@SERVER:/opt/zateya/data/archive.tgz
```

На сервере распакуйте архив в `data/archive/`, затем удалите временный tar:

```sh
cd /opt/zateya
tar -C data/archive -xzf data/archive.tgz
rm data/archive.tgz
agent_owner="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["agent"]["user"])')"
chown -R "$agent_owner" data/agent data/codex data/ssh data/obsidian
chmod 700 data/agent data/codex data/ssh
chmod -R g+rwX data/obsidian
find data/obsidian -type d -exec chmod g+s {} +
```

Перенесите файл **проекта** с токенами по защищённому каналу:

```sh
scp /home/artem/repos/zateya/.env USER@SERVER:/opt/zateya/.env
```

В checkout ноутбука `zateya/.env` — обычный файл с токенами Затеи и
`VOICE_TOOLS_OPENAI_KEY` для STT/TTS. Его можно перенести вместе с проектом
через `rsync`, сохранив права доступа. Общий `/home/artem/.hermes/.env`
не копируйте: в нём секреты других сервисов. При использовании иных
провайдеров задайте соответствующие URL и ключи из `.env.example`.
Не выводите ключи в журнал терминала и не коммитьте `.env`.

После копирования проверьте `chmod 600 .env` и укажите в нём числовые
`ZATEYA_UID`, `ZATEYA_GID` и `OBSIDIAN_GROUP_ID` непривилегированного агента.
Если изменили эти значения после команды `chown` выше, повторите её.
Не добавляйте абсолютный `OBSIDIAN_HOST_PATH`: vault всегда берётся из
`./data/obsidian`.

База прежнего host-агента хранит ссылки на локальные Codex-диалоги ноутбука.
Её переносить не надо: новый агент создаст диалоги на сервере; знания и
архив сохраняются в скопированных папках. Не копируйте `~/.codex` или
`auth.json` в Docker image.

## 3. Войти в Codex внутри контейнера и запустить Compose

Соберите образ агента, затем выполните вход в **его** постоянный каталог
`data/codex`. Для ChatGPT-подписки используется вход по коду устройства:

```sh
cd /opt/zateya
docker compose build
backend_owner="$(docker run --rm --entrypoint sh zateya-voice-gateway:latest -c 'printf "%s:%s" "$(id -u)" "$(id -g)"')"
chown -R "$backend_owner" data/archive
docker compose run --rm --no-deps --entrypoint codex agent login --device-auth
docker compose run --rm --no-deps --entrypoint codex agent login status
sudo install -m 644 deploy/zateya.service /etc/systemd/system/zateya.service
sudo systemctl daemon-reload
sudo systemctl enable --now zateya.service
sudo systemctl status --no-pager zateya.service
curl --fail http://127.0.0.1:8765/health/ready
curl --fail http://127.0.0.1:8080/health/ready
docker compose ps
```

Откройте ссылку из `codex login --device-auth` в браузере и введите код.
[Документация OpenAI](https://learn.chatgpt.com/docs/auth#login-on-headless-devices)
описывает этот способ для headless-сервера. API-ключ для Codex меняет оплату
на тарифы API. Контейнер агента не публикует порт: он слушает только
`127.0.0.1:8765`; Gateway использует его внутри общей host-сети.

Оба health endpoint должны вернуть `status: ok`, контейнеры — `healthy`.
Проверьте `journalctl -u zateya.service -b` и `docker compose logs agent backend`,
если проверка не прошла. Unit поднимет Compose после загрузки сервера; Docker
перезапускает контейнеры при их отдельном сбое. Для обновления выполните
`git pull`, `docker compose build`, затем `sudo systemctl restart zateya.service`.
Для Git push проверьте `git -C data/obsidian remote -v`, локальные
`user.name`/`user.email` и доступ ключа `data/ssh/id_ed25519` к GitHub.

## 4. Переключить диктофон

Проверьте с устройства путь к `http://АДРЕС-СЕРВЕРА:8080/health/live` через
его Wi-Fi или WireGuard. В веб-настройках задайте новый базовый URL Gateway
`http://АДРЕС-СЕРВЕРА:8080` и **повторно введите device token**: при смене
адреса пустое поле токена не сохраняет прежнее значение.

Надиктуйте содержательную тестовую мысль. Проверьте ответ, новый файл с
читаемым названием в `data/obsidian/Затея/ideas`, связанную wiki-страницу,
затем commit/push в `origin` vault. Голосовое подтверждение означает запись
файла; Git push выполняется асинхронно. Не запускайте старые службы ноутбука
одновременно с сервером: они будут писать в разные vault.

Если проверка не удалась, верните старый адрес Gateway на диктофоне и
запустите старые службы ноутбука. После успеха удалите временные архивы и
копии `.env` из каталогов переноса.
