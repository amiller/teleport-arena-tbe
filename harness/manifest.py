#!/usr/bin/env python3
"""What conditions was a run produced under? Written when it starts, not reconstructed after.

    python3 manifest.py                     the manifests recorded so far
    python3 manifest.py <run-id>            one of them in full

Issue #10's first item. A trajectory is only comparable to another if you know what produced
it, and today the conditions moved under us repeatedly: `brief` stopped asserting something
false about the goals, a generated part sheet appeared, the playbook entered the prompt, the
referee went from half real time to 4x, and placements gained the ability to resize a part --
which changed which levels are solvable at all. A trajectory from the morning and one from
the evening are not the same experiment, and nothing in either file said so.

So each run stamps: the harness commit, the container image digest, the full prompt (it is
small and it is the independent variable), the provider and model, whether that model can
see, and the level. `attempt` rows then carry the run id, which is the join the corpus has
been missing -- reasoning on one side, verdicts on the other, and nothing connecting them.
"""
import hashlib
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
RUNS = HERE / "out" / "runs.jsonl"


def _sh(*cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ""


def image_digest(image="tbe-fb"):
    """The image is the referee. Two runs against different images are different experiments,
    and the tag alone does not say which -- we rebuilt `tbe-fb` five times today."""
    return _sh("docker", "image", "inspect", image, "--format", "{{.Id}}")[:19]


def write(level, provider, model, vision, prompt, worktree="", agent_id="", extra=None):
    repo = HERE.parent.parent
    run = {
        "run": hashlib.sha256(
            f"{time.time()}{level}{provider}{worktree}".encode()).hexdigest()[:12],
        "epoch": time.time(),
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "level": level,
        "provider": provider,
        "model": model,
        "vision": vision,                       # whether this model can look at an image
        "harness_commit": _sh("git", "rev-parse", "--short", "HEAD", cwd=repo),
        "harness_dirty": bool(_sh("git", "status", "--porcelain", cwd=repo)),
        "image": image_digest(),
        "prompt": prompt,                       # stored whole: it is the independent variable
        "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:12],
        "worktree": worktree,
        "agent": agent_id,
        "host": _sh("hostname"),
        **(extra or {}),
    }
    RUNS.parent.mkdir(exist_ok=True)
    with open(RUNS, "a") as f:
        f.write(json.dumps(run) + "\n")
    return run


def load():
    if not RUNS.exists():
        return []
    return [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()]


if __name__ == "__main__":
    runs = load()
    if len(sys.argv) > 1:
        one = next((r for r in runs if r["run"] == sys.argv[1]), None)
        print(json.dumps(one, indent=1) if one else f"no run {sys.argv[1]}")
    elif not runs:
        print(f"no runs recorded yet -> {RUNS}")
    else:
        print(f"{'run':<13} {'when':<20} {'commit':<9} {'model':<22} level")
        for r in runs:
            print(f"{r['run']:<13} {r['when']:<20} {r['harness_commit']:<9} "
                  f"{(r['provider'] + '/' + (r['model'] or '-')):<22} "
                  f"{pathlib.Path(r['level']).stem}"
                  + ("  [dirty]" if r.get("harness_dirty") else ""))
        print(f"\n{len(runs)} runs -> {RUNS}")
