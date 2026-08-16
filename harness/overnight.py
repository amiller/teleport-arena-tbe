#!/usr/bin/env python3
"""Play unsolved levels, one agent at a time, unattended.

    python3 overnight.py [--levels N] [--minutes M] [--provider zai|claude]

Runs ON the machine that hosts the agents, so it survives the laptop it is watched from
going to sleep. One agent at a time, on a level nothing has solved and that the health sweep
says is playable. Each gets M minutes; when it goes idle or runs out, the next starts.

Deliberately not clever. The failure it is built against is the one that has actually
happened twice: an agent told to stop after 8 attempts made 118, and another spent 31
attempts on a level whose game process was segfaulting. So the cap is enforced here rather
than requested in a prompt, and levels the sweep marked CRASHED are never handed out.
"""
import json
import pathlib
import shlex
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tbe                                                    # noqa: E402
import dashboard as dash                                      # noqa: E402

REPO = HERE.parent.parent
LOG = tbe.OUT / "overnight.jsonl"
PASEO_HOST = pathlib.Path.home() / ".paseo" / "cli-host"


def paseo(*args, timeout=120):
    """Run a paseo command. Quoting via shlex, never by hand.

    The first version wrapped any argument containing a space in single quotes. The prompt
    contains the word "author's", whose apostrophe closed the quote early and handed the
    rest of the prompt to the shell as commands -- which then dutifully tried to run
    `python3 playtest/harness/tbe.py setup` in the wrong directory and failed. Every agent
    spawn failed that way and the loop finished in two seconds having done nothing."""
    cmd = ('export NVM_DIR=$HOME/.nvm; . $NVM_DIR/nvm.sh; paseo ' + shlex.quote(args[0])
           + ' --host "$(cat ~/.paseo/cli-host)" '
           + " ".join(shlex.quote(a) for a in args[1:]))
    return subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=timeout)


def note(**kw):
    kw["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as f:
        f.write(json.dumps(kw) + "\n")
    print(json.dumps(kw), flush=True)


def gather_attempts():
    """Pull every worktree's attempt log into this checkout before building a prompt.

    The already-tried list is the whole point of not repeating work, and on the agent host
    each run writes into its own worktree. Read from the main checkout alone, the history is
    empty and every agent starts from nothing -- which is exactly the failure this loop was
    written to stop."""
    root = pathlib.Path.home() / ".paseo" / "worktrees"
    n = 0
    for f in root.glob("*/*/playtest/harness/out/attempts.jsonl"):
        who = f.parents[3].name
        dst = tbe.OUT / f"attempts-{who}.jsonl"
        try:
            if not dst.exists() or dst.stat().st_mtime < f.stat().st_mtime:
                dst.write_bytes(f.read_bytes())
            n += 1
        except OSError:
            continue
    return n


def playable_unsolved():
    """Levels worth handing to an agent: playable, and nobody has solved them yet."""
    health_file = pathlib.Path(__file__).resolve().parent / "level-health.json"
    health = json.loads(health_file.read_text()) if health_file.exists() else {}
    solved = {pathlib.Path(r["level"]).stem for r in dash.attempts()
              if r.get("verdict") in ("SOLVED", "COPIED")}
    out = []
    for lv, h in sorted(health.items()):
        if h.get("verdict") != "SOLVED":          # crashed, unplaceable, or key no longer wins
            continue
        if pathlib.Path(lv).stem in solved:
            continue
        out.append(lv)
    return out, health


def main():
    argv = sys.argv
    n_levels = int(argv[argv.index("--levels") + 1]) if "--levels" in argv else 10
    minutes = int(argv[argv.index("--minutes") + 1]) if "--minutes" in argv else 25
    provider = argv[argv.index("--provider") + 1] if "--provider" in argv else "claude"
    prov, model, vision = dash.PROVIDERS[provider]

    if not PASEO_HOST.exists():
        sys.exit(f"no paseo credentials at {PASEO_HOST}; run this on the agent host")

    gathered = gather_attempts()
    todo, health = playable_unsolved()
    note(event="start", provider=provider, worktree_logs=gathered, playable_unsolved=len(todo),
         health={k: sum(1 for v in health.values() if v.get("verdict") == k)
                 for k in {v.get("verdict") for v in health.values()}},
         will_attempt=min(n_levels, len(todo)))
    if not todo:
        note(event="nothing to do")
        return

    for lv in todo[:n_levels]:
        stem = pathlib.Path(lv).stem
        wt = f"{provider}-{stem.lower().replace('_', '-')[:26]}"
        args = ["run", "--detach", "--json", "--provider", prov]
        if model:
            args += ["--model", model]
        if prov == "claude":
            args += ["--mode", "bypassPermissions"]
        gather_attempts()                     # refresh: the last agent just added to it
        prompt = dash.PROMPT.format(level=lv, vision=vision.format(level=lv),
                                    tried=dash.already_tried(lv))
        import manifest
        run = manifest.write(level=lv, provider=provider, model=model,
                             vision=(provider != "zai"), prompt=prompt, worktree=wt,
                             extra={"loop": "overnight"})
        r = paseo(*args, "--cwd", str(REPO), "--worktree", wt,
                  "--title", f"overnight: {stem}", prompt, timeout=300)
        if r.returncode != 0:
            note(event="spawn failed", level=lv, error=(r.stderr or r.stdout).strip()[:300])
            continue
        agent = json.loads(r.stdout)["agentId"]
        # The agent works in its own worktree, so the run id has to land where its copy of
        # tbe.py will look for it.
        for wt_out in (pathlib.Path.home() / ".paseo" / "worktrees").glob(f"*/{wt}/playtest/harness/out"):
            wt_out.mkdir(parents=True, exist_ok=True)
            (wt_out / "run-id").write_text(run["run"])
        note(event="started", level=lv, agent=agent[:7], run=run["run"],
             worktree=wt, minutes=minutes)

        deadline = time.time() + minutes * 60
        status = "unknown"
        while time.time() < deadline:
            time.sleep(30)
            q = paseo("ls", "--json", timeout=90)
            if q.returncode != 0:
                continue
            row = next((x for x in json.loads(q.stdout) if x["id"] == agent), None)
            status = (row or {}).get("status", "gone")
            if status != "running":
                break
        if status == "running":
            paseo("stop", agent, timeout=90)
            note(event="stopped at cap", level=lv, agent=agent[:7])
        else:
            note(event="finished", level=lv, agent=agent[:7], status=status)

    note(event="done")


if __name__ == "__main__":
    main()
