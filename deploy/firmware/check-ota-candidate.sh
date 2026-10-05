#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
scratch="$(mktemp -d "${TMPDIR:-/tmp}/zateya-ota-check.XXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT

rsync -a --exclude '.pio/' --exclude 'sdkconfig.sticks3' \
  "$repo_root/firmware/" "$scratch/"
cp "$scratch/partitions.ota.csv" "$scratch/partitions.csv"
printf '\nCONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y\n' >> "$scratch/sdkconfig.defaults"

pio_binary="${PIO_BINARY:-pio}"
(cd "$scratch" && "$pio_binary" run -e sticks3)

rg -q '^CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y$' "$scratch/sdkconfig.sticks3"
rg -q '^CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"$' "$scratch/sdkconfig.sticks3"
python3 - "$scratch/.pio/build/sticks3/firmware.bin" <<'PY'
from pathlib import Path
import sys

size = Path(sys.argv[1]).stat().st_size
if size >= 0x300000:
    raise SystemExit(f"OTA app {size} bytes exceeds 3 MiB slot")
print(f"Candidate OTA app: {size} bytes of 3145728-byte slot")
PY
