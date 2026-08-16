#!/bin/bash
# Record a level running. Parts are already in the scene; dismiss the briefing, press Play.
set -uo pipefail
LEVEL="${1:?level}"; NAME="$(basename "$LEVEL" .xml)"
Xvfb :99 -screen 0 760x470x24 >/dev/null 2>&1 & sleep 3
export DISPLAY=:99
matchbox-window-manager -use_titlebar no >/dev/null 2>&1 &   # focus, so key events land
sleep 1
/usr/games/tbe "$LEVEL" > "/out/$NAME-play.log" 2>&1 &
GAME=$!
sleep 9
# Dismiss the level briefing. Return hits the dialog's default button regardless of where
# it lands; a fixed pixel does not. NOT followed by Escape: on levels where Return had
# already closed the briefing, the Escape reached the main window and quit the game, and
# the recording was one frame of the level and then twenty seconds of black. Half the
# recordings were coming out that way.
xdotool key --clearmodifiers Return; sleep 1
ffmpeg -loglevel error -f x11grab -video_size 760x470 -framerate 20 -i :99 -t 20 -pix_fmt yuv420p -y "/out/$NAME.mp4" &
sleep 1
xdotool key --clearmodifiers space  # Play (the game's own regression driver uses Key_Space)
sleep 1
# Prove the sim is actually stepping; a frozen scene is a failed recording, not a slow one.
import -window root /tmp/a.png 2>/dev/null; sleep 2
import -window root /tmp/b.png 2>/dev/null
if compare -metric AE /tmp/a.png /tmp/b.png null: 2>&1 | awk '{exit !($1 < 500)}'; then
  echo "WARNING: scene is static after Play - recording will show a frozen level" >&2
fi
sleep 22
kill $GAME 2>/dev/null
wait $GAME 2>/dev/null   # NOT bare wait: Xvfb never exits
echo "recorded"
