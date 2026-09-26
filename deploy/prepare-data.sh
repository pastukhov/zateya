#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

if [[ -L data ]]; then
  echo "Refusing symlink: data" >&2
  exit 1
fi
mkdir -p data

# Compose interpolation may contain secrets; parse its JSON without printing it.
container_user="$(docker compose config --format json | python3 -c '
import json, sys
try:
    services = json.load(sys.stdin)["services"]
    raw = services["backend"]["user"]
    uid, gid = raw.split(":", 1)
    if not uid.isdecimal() or not gid.isdecimal() or int(uid) == 0:
        raise ValueError
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    print("Compose backend must use a numeric non-root UID:GID", file=sys.stderr)
    raise SystemExit(1)
print(uid + ":" + gid)
')"
uid="${container_user%%:*}"
gid="${container_user##*:}"

for directory in archive obsidian ssh; do
  path="data/$directory"
  if [[ -L "$path" ]]; then
    echo "Refusing symlink: $path" >&2
    exit 1
  fi
  mkdir -p "$path"
  if find -P "$path" -type l -print -quit | grep -q .; then
    echo "Refusing symlink below $path" >&2
    exit 1
  fi
done

# Chown only known data trees, after symlink checks; never delete or replace data.
chown -R "$uid:$gid" data/archive data/obsidian data/ssh
chmod 700 data/ssh
for secret_file in data/ssh/id_ed25519 data/ssh/known_hosts; do
  if [[ -e "$secret_file" ]]; then
    chmod 600 "$secret_file"
  fi
done

printf 'Prepared data for container UID:GID %s:%s\n' "$uid" "$gid"
if [[ ! -f data/ssh/id_ed25519 || ! -f data/ssh/known_hosts ]]; then
  echo "SSH key or known_hosts is missing; configure Git publishing before expecting pushes." >&2
fi
