#!/bin/bash
# Adjudicate one candidate solution. $1 = level file whose <hints> block IS the solution.
# The regression runner plays the level empty (must fail), inserts the hint objects,
# and plays again (must win). Prints a verdict; records video when RECORD is set.
set -uo pipefail
LEVEL="${1:?level file}"; NAME="$(basename "$LEVEL" .xml)"
Xvfb :99 -screen 0 1100x700x24 >/dev/null 2>&1 & sleep 3
export DISPLAY=:99
/usr/games/tbe --regression "$LEVEL:${BUDGET:-25}" > "/out/$NAME.log" 2>&1 &
GAME=$!
# The regression progress dialog is no longer shown at all (fast-sim.patch). This used to
# be an xdotool loop trying to shove it off-screen, which never worked: it searched for a
# window named "Regression testing", and that string is the dialog's label, not its title.
# Live frame for the dashboard: one screenshot a second while this runs.
( while true; do
    if import -window root -crop 602x406+10+28 +repage /out/live.next.png 2>/dev/null; then
      # Only promote a frame with something in it. Once the game exits the root window
      # goes black, and a black frame would sit on the dashboard as the "last frame".
      m=$(convert /out/live.next.png -format "%[fx:mean]" info: 2>/dev/null || echo 0)
      if awk "BEGIN{exit !($m > 0.05)}"; then mv -f /out/live.next.png /out/live.png; fi
    fi
    sleep 1
  done ) &
LIVE=$!
sleep 2
FFMPEG=""
if [ -n "${RECORD:-}" ]; then
  # Grab the PLAYFIELD, not the screen and not even the window. The window is 760x470 in
  # the top-left of a 1100x700 root, and the playfield is 602x406 inside that at +10,+28 --
  # the rest is a menu bar, a toolbox column and an fps counter. Cropping here rather than
  # in CSS means every clip is the game and nothing downstream has to know the geometry.
  ffmpeg -loglevel error -f x11grab -video_size 602x406 -framerate 12 \
      -i :99+10,28 -t "${DUR:-70}" -pix_fmt yuv420p -y "/out/$NAME.mp4" &
  FFMPEG=$!
  START=$(date +%s)
fi
# Exit as soon as the referee has ruled, instead of always waiting out a fixed sleep.
# The state machine prints Regression Successful when it finishes the level list.
#
# DUR is a watchdog and not the budget: the level now ends after BUDGET *simulated* seconds
# (sim-budget.patch), so this only bounds a game that has stopped making progress.
#
# A game can stop without dying. little_balloon_puzzle freezes in 'Start Level to Win' --
# the trace stops mid-level, the process stays alive, and nothing more is ever written. That
# is a third outcome, and calling it CRASHED would say the process died when it did not, or
# NOT SOLVED would say the referee ruled when it never did. Watch the log for silence.
STALL=0
SIZE=0
DEADLINE=$(( $(date +%s) + ${DUR:-70} ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  if grep -q "Regression Successful" "/out/$NAME.log" 2>/dev/null; then sleep 1; break; fi
  if ! kill -0 $GAME 2>/dev/null; then break; fi
  NOW=$(stat -c%s "/out/$NAME.log" 2>/dev/null || echo 0)
  if [ "$NOW" -eq "$SIZE" ]; then STALL=$((STALL + 1)); else STALL=0; SIZE=$NOW; fi
  # Every state the machine passes through logs, and a running level traces twice a
  # simulated second, so 20 quiet seconds is not a slow moment.
  if [ "$STALL" -ge 20 ]; then STALLED=1; break; fi
  sleep 1
done
kill $GAME 2>/dev/null
pkill -P $LIVE 2>/dev/null; kill $LIVE 2>/dev/null   # the frame loop never exits on its own
wait $GAME 2>/dev/null
# The referee now rules in about 17s but ffmpeg was given -t 30, so the script used to end
# with it still recording -- the container exited underneath it and the mp4 was a 48-byte
# stub. SIGINT makes it finalise what it has instead.
#
# A run can also end almost instantly -- most often because the game crashed. Without a
# floor the clip was a 1-second black stub, because the window had not even painted before
# it was over. Keep grabbing until there is something watchable, whatever the referee did.
if [ -n "$FFMPEG" ]; then
  END=$(( START + ${FLOOR:-8} ))
  while [ "$(date +%s)" -lt "$END" ] && kill -0 "$FFMPEG" 2>/dev/null; do sleep 1; done
  kill -INT "$FFMPEG" 2>/dev/null; wait "$FFMPEG" 2>/dev/null
fi
# "STATE 8 'Level Won (expected)'" is the NAME of the state, printed on entry before
# any check runs -- it appears whether or not the level was won. The only real signal is
# slot_Won, emitted by RegressionTest when the game actually raises its won event.
WON=$(grep -c "AUTOMATED TESTING, slot_Won" "/out/$NAME.log")
# Neither is a hang. Winning still counts if it happened before the freeze.
if [ "$WON" -lt 1 ] && [ -n "${STALLED:-}" ]; then
  echo "VERDICT      : STALLED (the game stopped stepping and never ruled; not your mechanism)"
  exit 0
fi
# A crash is not a verdict. brother-plays-soccer segfaults the game on some placements --
# on the unpatched build too, so this is the game and not the harness -- and reporting that
# as NOT SOLVED told an agent its mechanism was wrong when the referee never ran. One agent
# spent 31 attempts and 12 minutes being told "no" by a process that had died. Say so.
if [ "$WON" -lt 1 ] && ! grep -q "Regression Successful" "/out/$NAME.log" 2>/dev/null \
   && ! grep -q "STATE 8" "/out/$NAME.log" 2>/dev/null; then
  echo "VERDICT      : CRASHED (the game died before the referee ruled; not your mechanism)"
  exit 0
fi
if [ "$WON" -ge 1 ]; then
  echo "VERDICT      : SOLVED (slot_Won fired)"
else
  echo "VERDICT      : NOT SOLVED (no slot_Won; the level was never actually won)"
fi
