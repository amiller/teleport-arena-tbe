#!/bin/bash
# Pull what the remote agents are doing, so the dashboard can show them PLAYING and not
# just their verdicts. Each worktree's container writes out/live.png once a second while an
# attempt runs; that frame is the whole point, so it is polled hard and the logs are not.
#
# Use the shortest path you have to the box: measured here, a direct route was ~150ms a
# call against ~370ms through a tunnel, and this runs every few seconds. rsync -t keeps the
# remote mtime, which is how the dashboard tells a live frame from one left behind by an
# attempt that ended hours ago.
OUT="$(cd "$(dirname "$0")" && pwd)/out"
ZLOGS="$(dirname "$OUT")/zlogs"
# The machine running the agents, and where their working copies live. Site-specific:
# ours are paseo worktrees on another box reached over a private overlay, but anything with
# the same layout works. Set REMOTE to an ssh host; unset, this script has nothing to do.
HOST="${REMOTE:?set REMOTE to the ssh host running the agents}"
ROOT="${REMOTE_WORKTREES:-~/worktrees}"
mkdir -p "$OUT" "$ZLOGS"
# --once does a single pass and exits: the dashboard drives it on a thread so there is no
# separate loop to remember to start, and no way for it to die quietly while the page goes
# on serving stale data as though the agents had stopped working.
ONCE=""; SLOW=""
[ "${1:-}" = "--once" ] && ONCE=1
[ "${2:-}" = "--slow" ] && SLOW=1     # this pass also fetches logs, videos and the archive
i=0
while true; do
  # Re-listed every poll: an agent started from the web console lives in a worktree that
  # did not exist when this loop began.
  for d in $(ssh -o BatchMode=yes "$HOST" "ls -d $ROOT/*/*/playtest/harness/out 2>/dev/null"); do
    who=$(basename "$(dirname "$(dirname "$(dirname "$d")")")")
    rsync -qt "$HOST:$d/live.png" "$OUT/live-$who.png" 2>/dev/null
    rsync -qt "$HOST:$d/attempts.jsonl" "$OUT/attempts-$who.jsonl" 2>/dev/null
    # The dashboard adjudicates from the game's own log rather than the verdict field, so
    # the logs come too -- and now the attempt videos, since solve records every attempt.
    # Both only change between attempts, and the videos are ~300kB, so they poll slowly.
    if { [ -z "$ONCE" ] && [ $((i % 10)) -eq 0 ]; } || [ -n "$SLOW" ]; then
      rsync -qt "$HOST:$d/"\*_claude.log "$ZLOGS/" 2>/dev/null
      # Prefixed with the worktree: two agents on the same level would otherwise land on
      # the same filename, and each player's footage should be its own.
      for m in $(ssh -o BatchMode=yes "$HOST" "ls $d/*_claude.mp4 2>/dev/null"); do
        rsync -qt --min-size=2048 "$HOST:$m" "$OUT/$who-$(basename "$m")" 2>/dev/null
      done
      # Every attempt an agent has ever made, not just its latest. tbe.py keeps each one
      # under archive/ with its own timestamp; they are ~150kB apiece and they are the only
      # record of what the agent tried before it got there.
      mkdir -p "$OUT/archive"
      rsync -qrt --ignore-existing "$HOST:$d/archive/" "$OUT/archive/" 2>/dev/null
    fi
  done
  i=$((i + 1))
  # A single pass must still fetch the slow things, or driving it with --once would never
  # pull a log, a video or the archive at all.
  [ -n "$ONCE" ] && exit 0
  sleep 2
done
