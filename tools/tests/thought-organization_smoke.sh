#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
python tools/replay-thought-organization.py --help >/dev/null
output=$(python tools/replay-thought-organization.py)
case "$output" in
  'No provider called.'*) ;;
  *) exit 1 ;;
esac
