#!/bin/sh
set -eu
preview_dir=$(mktemp -d /tmp/zateya-screen-preview-smoke.XXXXXX)
python3 "$(dirname "$0")/../render-screen-previews.py" "$preview_dir"
test -s "$preview_dir/contact-sheet.png"
test -s "$preview_dir/setup-270.ppm"
