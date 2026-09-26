# Перенос Затеи на Linux-сервер

На сервере запускается один `docker-compose.yml`: Gateway и Codex Agent.
Все постоянные данные находятся в папке `data/` рядом с ним. Нужны Linux
(x86-64), Docker Engine с Compose, Git, SSH, доступ к OpenAI и GitHub.
Порт 8080 разрешайте только из доверенной LAN/WireGuard, не из Интернета.

## 1. Подготовить сервер

Войдите под пользователем, который будет владеть `data/`. Настройте его
доступ к GitHub по SSH и клонируйте проект:

```sh
mkdir -p ~/repos
ssh -T git@github.com
git clone git@github.com:pastukhov/zateya.git ~/repos/zateya
cd ~/repos/zateya
mkdir -p data/archive data/obsidian data/agent data/codex data/ssh
chmod 700 data data/agent data/codex data/ssh
cp .env.example .env
```

Все пять каталогов должны принадлежать этому пользователю. В `.env` задайте
`ZATEYA_UID=$(id -u)`, `ZATEYA_GID=$(id -g)` и
`OBSIDIAN_GROUP_ID=$(id -g)` **числами**, а не буквальной подстановкой;
задайте существующие STT/TTS-ключи, `VOICE_DEVICE_TOKENS` и общий для двух
контейнеров `CODEX_AGENT_TOKEN`. Права `.env` — `chmod 600 .env`.

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
`~/repos/zateya/data/obsidian/` на сервере, включая `.git`, `.obsidian` и
незакоммиченные записи `Затея/sources`. Одного `git clone` недостаточно.
Архив из старого Docker volume перенесите через tar:

```sh
mkdir -p ~/zateya-transfer
chmod 700 ~/zateya-transfer
docker run --rm -v hermes-echo_archive_data:/data:ro \
  -v "$HOME/zateya-transfer:/backup" alpine:3.20 \
  tar -C /data -czf /backup/archive.tgz .
rsync -a /home/artem/repos/obsidian/ USER@SERVER:~/repos/zateya/data/obsidian/
rsync -a ~/zateya-transfer/archive.tgz USER@SERVER:~/repos/zateya/data/archive.tgz
```

На сервере распакуйте архив в `data/archive/`, затем удалите временный tar:

```sh
cd ~/repos/zateya
tar -C data/archive -xzf data/archive.tgz
rm data/archive.tgz
chown -R "$(id -un):$(id -gn)" data
chmod -R g+rwX data/obsidian
find data/obsidian -type d -exec chmod g+s {} +
```

Перенесите файл **проекта** с токенами по защищённому каналу:

```sh
scp /home/artem/repos/zateya/.env USER@SERVER:~/repos/zateya/.env
```

В checkout ноутбука `zateya/.env` — обычный файл с токенами Затеи и
`VOICE_TOOLS_OPENAI_KEY` для STT/TTS. Его можно перенести вместе с проектом
через `rsync`, сохранив права доступа. Общий `/home/artem/.hermes/.env`
не копируйте: в нём секреты других сервисов. При использовании иных
провайдеров задайте соответствующие URL и ключи из `.env.example`.
Не выводите ключи в журнал терминала и не коммитьте `.env`.

После копирования проверьте `chmod 600 .env` и задайте в нём числовые
`ZATEYA_UID`, `ZATEYA_GID` и `OBSIDIAN_GROUP_ID` пользователя сервера.
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
cd ~/repos/zateya
docker compose build agent
docker compose run --rm --no-deps --entrypoint codex agent login --device-auth
docker compose run --rm --no-deps --entrypoint codex agent login status
docker compose up --build -d
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
Проверьте `docker compose logs agent` и `docker compose logs backend`, если
проверка не прошла. Обе службы автоматически перезапускаются после перезагрузки.
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
