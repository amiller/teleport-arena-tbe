#!/usr/bin/env python3
"""Which levels can actually be played? Run the author's own solution through the referee.

    python3 level-health.py [--redo]

Cheap and agent-free: no model is involved, so this is the thing to run before pointing
anything expensive at a level. The author's placements are known to be a solution, so the
verdict says something about the LEVEL rather than about the player:

    SOLVED   the level is playable and the referee agrees with its own author
    CRASHED  the game dies on it -- the_pit and goal_maker do, and an agent that is sent
             here will be told NOT SOLVED forever by a process that already died
    other    interesting, and worth a look: the author's answer no longer wins

Writes out/level-health.json. Levels already recorded are skipped unless --redo.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tbe

HEALTH = tbe.OUT / "level-health.json"


def main():
    redo = "--redo" in sys.argv
    keys = json.loads(tbe.KEYS.read_text())
    health = {} if redo else (json.loads(HEALTH.read_text()) if HEALTH.exists() else {})
    todo = [lv for lv, hints in sorted(keys.items()) if hints and lv not in health]
    print(f"{len(keys)} levels with an author solution, {len(todo)} to check")

    for i, lv in enumerate(todo, 1):
        places = tbe.key_to_places(keys[lv])
        try:
            tbe._check_parts(lv, places)
        except SystemExit as e:
            health[lv] = {"verdict": "UNPLACEABLE", "note": str(e)[:120]}
            print(f"[{i}/{len(todo)}] {lv}  UNPLACEABLE")
            HEALTH.write_text(json.dumps(health, indent=1, sort_keys=True))
            continue
        cand = tbe._write_candidate(lv, places, "health")
        r = tbe._docker(["bash", "/run.sh", f"/solve/{cand.name}"], {"DUR": "40"})
        out = (r.stdout or "") + (r.stderr or "")
        if "VERDICT      : CRASHED" in out or "Segmentation fault" in out:
            v = "CRASHED"
        elif "VERDICT      : SOLVED" in out:
            v = "SOLVED"
        else:
            v = "AUTHOR KEY DID NOT WIN"
        health[lv] = {"verdict": v, "parts": len(places), "when": time.strftime("%Y-%m-%d %H:%M")}
        print(f"[{i}/{len(todo)}] {lv}  {v}", flush=True)
        HEALTH.write_text(json.dumps(health, indent=1, sort_keys=True))

    tally = {}
    for v in health.values():
        tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
    print("\n" + json.dumps(tally, indent=1))
    print(f"-> {HEALTH}")


if __name__ == "__main__":
    main()
