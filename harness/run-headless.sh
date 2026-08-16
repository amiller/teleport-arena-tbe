#!/bin/bash
# Start tbe on a virtual display and screenshot it. Exits non-zero if the game dies.
set -euo pipefail
Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
sleep 3
export DISPLAY=:99
/usr/games/tbe > /out/tbe.log 2>&1 &
GAME=$!
sleep "${WARMUP:-15}"
kill -0 "$GAME" 2>/dev/null || { echo "tbe exited early; see /out/tbe.log"; exit 1; }
import -window root /out/tbe.png
echo "captured /out/tbe.png"
kill "$GAME" 2>/dev/null || true
