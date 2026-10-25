#!/usr/bin/env bash
# Copy the firmware to a Pico W over USB with mpremote.
#
#   pico/install.sh            # install to the first Pico found
#   pico/install.sh a0         # a specific mpremote device shortcut / port
#
# Writes version.py from scripts/version.sh so the device logs the build it
# runs, mirroring what quickstart.sh bakes into the Pi Zero runner. Never
# overwrites a secrets.py already on the board.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
dev="${1:-}"
mp=(mpremote)
[ -n "$dev" ] && mp+=(connect "$dev")

command -v mpremote >/dev/null || { echo "mpremote not found: pip install mpremote" >&2; exit 1; }

version="$("$repo/scripts/version.sh" 2>/dev/null || echo v0.0.0)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
printf 'VERSION = "%s"\n' "$version" > "$tmp/version.py"

modules=(config.py epd2in13b_v4.py font.py homeapi.py layout.py localtime.py power.py schedule.py main.py)
for f in "${modules[@]}"; do
  "${mp[@]}" cp "$here/$f" ":$f"
done
"${mp[@]}" cp "$tmp/version.py" ":version.py"

if "${mp[@]}" fs ls : 2>/dev/null | grep -q ' secrets.py$'; then
  echo "secrets.py already on the board; left as is"
elif [ -f "$here/secrets.py" ]; then
  "${mp[@]}" cp "$here/secrets.py" ":secrets.py"
else
  echo "no secrets.py: copy secrets.example.py to pico/secrets.py and fill it in" >&2
  exit 1
fi

echo "installed $version; resetting"
"${mp[@]}" reset
