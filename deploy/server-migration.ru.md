# Перенос Затеи на Linux-сервер

Этот порядок рассчитан на Linux-сервер с Docker Compose, Git, SSH и Python 3.12.
Gateway остаётся в контейнере, Codex Agent работает отдельной пользовательской
службой systemd без графической сессии. Команды ниже выполняются от одного
обычного пользователя на сервере; его домашний каталог может отличаться от
`/home/artem`. Старый ноутбук остаётся рабочим резервом до проверки диктофона.

## 1. Подготовить сервер

Установите Docker Engine с плагином Compose, Git, rsync, Python 3.12 с `venv`,
Node.js/npm и Codex CLI. Добавьте пользователя сервера в группу `docker` либо
выполняйте команды Docker через `sudo`. Для CLI можно использовать
`npm install -g @openai/codex`; проверьте `codex --version`.

Серверу нужны исходящие HTTPS-соединения к OpenAI и доступ к GitHub для push
Obsidian. Порт Gateway (по умолчанию TCP 8080) откройте только из доверенной
локальной сети и/или WireGuard, не из публичного Интернета. Устройство должно
достигать нового адреса сервера через свой полный VPN-туннель либо локальный
Wi-Fi. Проверьте маршрутизацию и обратный маршрут на WireGuard-сервере.

На сервере от имени будущего владельца служб сначала настройте доступ к
GitHub по SSH для клонирования Zateya и будущего
push в Obsidian. Подойдёт отдельный ключ сервера с необходимыми правами;
ключ с ноутбука переносить не требуется. Проверьте `ssh -T git@github.com`.

```sh
mkdir -p ~/repos ~/zateya-migration ~/.config/systemd/user ~/.config/hermes-echo
chmod 700 ~/zateya-migration ~/.config/hermes-echo
git clone git@github.com:pastukhov/zateya.git ~/repos/zateya
python3.12 -m venv ~/repos/zateya/agent_service/.venv
~/repos/zateya/agent_service/.venv/bin/python -m pip install -r ~/repos/zateya/agent_service/requirements.txt
```

Для автоматического push Git должен знать
`user.name` и `user.email`; `git -C ~/repos/obsidian config user.name` и
`git -C ~/repos/obsidian config user.email` проверяются после копирования vault.

Для подписки ChatGPT войдите в Codex на **сервере**, под тем же пользователем:

```sh
codex login --device-auth
codex login status
```

Откройте предложенную ссылку в браузере и введите одноразовый код. Если вход
по коду устройства недоступен, смотрите [официальные варианты входа на
headless-устройстве](https://learn.chatgpt.com/docs/auth#login-on-headless-devices).
Не копируйте весь `~/.codex`, `auth.json` и личный SSH-ключ ноутбука в Docker.
Вход через API-ключ вместо ChatGPT переключит Codex на отдельную оплату API.

## 2. Сделать согласованный снимок ноутбука

Выберите момент, когда диктофон закончил обработку записи. На **ноутбуке**
остановите обе службы, чтобы архив, Obsidian и очередь Git не менялись во время
копирования:

```sh
systemctl --user stop codex-voice-agent.service
cd /home/artem/repos/zateya
docker compose -p hermes-echo --env-file /home/artem/.hermes/.env --env-file .env stop backend
mkdir -p ~/zateya-migration
chmod 700 ~/zateya-migration
docker run --rm \
  -v hermes-echo_archive_data:/data:ro \
  -v "$HOME/zateya-migration:/backup" \
  alpine:3.20 tar -C /data -czf /backup/archive.tgz .
rsync -a /home/artem/repos/obsidian/ ~/zateya-migration/obsidian/
install -m 600 /home/artem/.hermes/.env ~/zateya-migration/gateway.env
install -m 600 ~/.config/hermes-echo/codex-voice-agent.env ~/zateya-migration/agent.env
```

Копируйте **весь** vault, включая `.git`, `.obsidian` и незакоммиченные
`Hermes/sources`: одного `git clone` недостаточно. `archive.tgz` содержит
аудиозаписи и базу задач Gateway. Два env-файла содержат действующие токены и
ключи STT/TTS; храните каталог переноса приватным и не помещайте его в Git.
Базу `~/.local/state/hermes-echo/codex-voice/agent.sqlite3` копировать не
надо: она ссылается на локальные Codex-диалоги ноутбука. На сервере появятся
новые диалоги, а сохранённые мысли останутся в Obsidian.

Передайте снимок на сервер по SSH (подставьте свой адрес):

```sh
rsync -a ~/zateya-migration/ USER@SERVER:~/zateya-migration/
```

## 3. Восстановить данные и запустить службы

На **сервере**:

```sh
rsync -a ~/zateya-migration/obsidian/ ~/repos/obsidian/
chown -R "$(id -un):$(id -gn)" ~/repos/obsidian
chmod -R g+rwX ~/repos/obsidian
find ~/repos/obsidian -type d -exec chmod g+s {} +
install -m 600 ~/zateya-migration/gateway.env ~/repos/zateya/.env
install -m 600 ~/zateya-migration/agent.env ~/.config/hermes-echo/codex-voice-agent.env
install -m 644 ~/repos/zateya/deploy/codex-voice-agent.service ~/.config/systemd/user/codex-voice-agent.service
docker volume create hermes-echo_archive_data
docker run --rm \
  -v hermes-echo_archive_data:/data \
  -v "$HOME/zateya-migration:/backup:ro" \
  alpine:3.20 tar -C /data -xzf /backup/archive.tgz
```

В `~/repos/zateya/.env` добавьте или обновите следующие строки (укажите
**реальный абсолютный** домашний путь пользователя сервера и его GID):

```dotenv
OBSIDIAN_HOST_PATH=/home/USER/repos/obsidian
OBSIDIAN_GROUP_ID=1000
VOICE_AGENT_PROVIDER=codex
CODEX_AGENT_URL=http://127.0.0.1:8765
```

`OBSIDIAN_GROUP_ID` узнаётся командой `id -g`. Сохраните прежние
`VOICE_DEVICE_TOKENS`, `CODEX_AGENT_TOKEN` и ключи STT/TTS из скопированного
env-файла. В `~/.config/hermes-echo/codex-voice-agent.env` задайте
`CODEX_VOICE_MODEL=gpt-6-luna` и убедитесь, что `CODEX_AGENT_TOKEN` совпадает
с Gateway. Не выводите env-файлы в логи и не добавляйте их в Git.

Службе нужен работающий пользовательский systemd после выхода из SSH:

```sh
sudo loginctl enable-linger "$(id -un)"
systemctl --user daemon-reload
systemctl --user enable --now codex-voice-agent.service
curl --fail http://127.0.0.1:8765/health/ready
cd ~/repos/zateya
docker compose -p hermes-echo --env-file .env up --build -d backend
curl --fail http://127.0.0.1:8080/health/ready
docker compose -p hermes-echo --env-file .env ps backend
```

Оба health endpoint должны сообщить `status: ok`; контейнер должен быть
`healthy`. `systemctl --user status codex-voice-agent.service` и
`journalctl --user -u codex-voice-agent.service -n 100` помогут найти ошибку
авторизации или запуска. `docker compose -p hermes-echo logs backend` покажет
ошибки Gateway. Не публикуйте логи целиком, если в них есть личные записи.

Проверьте на сервере `git -C ~/repos/obsidian status --short` и доступ к
`origin`. Уже ожидающие публикации файлы находятся в `Hermes/.sync`; агент
повторит их commit/push после запуска. Если Git сообщает о расхождении веток,
разрешите его вручную: автоматический обработчик не делает pull или force-push.

## 4. Переключить диктофон и проверить

С устройства или телефона в той же сети проверьте доступность
`http://АДРЕС-СЕРВЕРА:8080/health/live`. В веб-настройках диктофона укажите
новый базовый адрес Gateway `http://АДРЕС-СЕРВЕРА:8080` и **повторно введите
его device token**: при изменении адреса пустое поле токена не сохраняет
старый секрет. Настройки Wi-Fi и WireGuard менять не нужно, если маршруты к
новому серверу уже работают.

Надиктуйте короткую тестовую мысль. Подтвердите голосовой ответ, появление
файла в `~/repos/obsidian/Hermes/ideas` и связанной страницы в `Hermes/wiki`.
Затем проверьте `git -C ~/repos/obsidian status --short` и новый коммит в
`origin`. Голосовое «сохранила» означает запись файла; push выполняется
асинхронно и может занять ещё несколько секунд.

После успешной проверки оставьте старые службы ноутбука остановленными:
одновременный запуск на двух машинах создаст два независимых Gateway и две
очереди Git. Если перенос не удался, верните прежний адрес Gateway в диктофон
и запустите старые службы на ноутбуке:

```sh
systemctl --user start codex-voice-agent.service
cd /home/artem/repos/zateya
docker compose -p hermes-echo --env-file /home/artem/.hermes/.env --env-file .env start backend
```

После завершения переноса удалите `~/zateya-migration` с обеих машин: там
остаются копии токенов, ключей и аудиоархива.
