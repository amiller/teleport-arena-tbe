#!/usr/bin/env python3
"""Read, solve and record The Butterfly Effect levels — the agent's side of the loop.

  tbe.py setup                       fetch the level source (once per checkout)
  tbe.py levels                      the play order, and what each level introduces
  tbe.py brief  <level>              the scene, the toolbox and the goals, as text
  tbe.py solve  <level> P@X,Y ...    write a candidate solution and adjudicate it (records
                                     the attempt; --no-record to skip the video)
  tbe.py record <level>              record the level running, parts pre-placed
  tbe.py record-missing              record every solved level lacking a replay
  tbe.py trace  <level> [ids...]     what every object did, from the sim itself
  tbe.py check  <level> P@X,Y ...    does it start inside something? instant, no sim
  tbe.py where  <level> [ids...]     the path an object took, moment by moment
  tbe.py frame  <level> [0.75|12s]   a still from the last attempt, if you can see

A level's <hints> block is the solution format: an ordered list of part placements.
`solve` writes your placements there and runs the game's own regression referee, which
plays the level empty (must fail) then with your parts (must win).

Levels live in the container at /usr/share/games/tbe/levels; pass a path relative to
that, e.g. finished/bouncing_balls.xml.
"""
import datetime
import gzip
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
SRC = REPO / "tbe-src"                       # a checkout of the game, for reading levels
SOLVE = REPO / "solve"                       # candidate level files this harness writes
OUT = HERE / "out"
KEYS = HERE.parent / "tbe-derived" / "answer-keys.json"
IMAGE = "tbe-fb"          # WM image plus a referee that logs each goal check
CONTAINER_LEVELS = "/usr/share/games/tbe/levels"


def levels_dir():
    d = SRC / "levels"
    if not d.is_dir():
        sys.exit(f"no level source at {d}\n"
                 f"  run:  python3 {pathlib.Path(__file__).name} setup\n"
                 f"  (tbe-src is gitignored, so a fresh clone or git worktree will not have it)")
    return d


def cmd_setup():
    """Fetch the level source. Needed once per checkout — tbe-src is not in git."""
    if not (SRC / "levels").is_dir():
        SRC.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1",
                        "https://github.com/the-butterfly-effect/tbe.git", str(SRC)], check=True)
    cmd_strip()
    print(f"levels ready: {SRC}")


def cmd_strip():
    """Move every level's <hints> block out of the level file and into KEYS.

    Upstream ships each puzzle with the author's winning placements inside the puzzle
    itself. A solver reading the file it was asked to solve gets the answer for free, so
    the levels on disk must not carry it -- run at setup, before any agent sees them."""
    keys = json.loads(KEYS.read_text()) if KEYS.exists() else {}
    found = {}
    for f in sorted(levels_dir().rglob("*.xml")):
        src = f.read_text()
        block = re.search(r"[ \t]*<hints>.*?</hints>\n?", src, flags=re.S)
        if not block:
            continue
        hints = []
        for tag in re.findall(r"<hint\b[^>]*>", block.group(0)):
            # attributes by regex, not ET: finished/the_pit.xml repeats Y= on one hint,
            # which is malformed upstream and makes the whole document unparseable.
            a = {}
            for k, v in re.findall(r'(\w+)="([^"]*)"', tag):
                a.setdefault(k, v)
            hints.append({"object": a["object"], "X": float(a["X"]), "Y": float(a["Y"]),
                          # width/height resize the part, and 155 hints across the level set
                          # use them. Dropping them silently placed a default-sized part and
                          # the author's own solution then lost -- 13 of the 16 levels whose
                          # key "did not win" were this.
                          **({"angle": float(a["angle"])} if "angle" in a else {}),
                          **({"width": float(a["width"])} if "width" in a else {}),
                          **({"height": float(a["height"])} if "height" in a else {})})
        found[f] = (hints, src[:block.start()] + src[block.end():])
    # Persist every key before editing any level: a crash partway through the rewrite
    # would otherwise destroy the answers it had already removed.
    keys.update({str(f.relative_to(levels_dir())): h for f, (h, _) in found.items()})
    KEYS.write_text(json.dumps(keys, indent=1, sort_keys=True))
    for f, (_, body) in found.items():
        f.write_text(body)
    print(f"stripped answer keys from {len(found)} levels -> {KEYS.name}")


def cmd_levels():
    """The manifest is an ordered curriculum: each entry says what it introduces."""
    text = (levels_dir() / "levels.xml").read_text()
    n = 0
    for line in text.splitlines():
        m = re.search(r"<level>\s*(\S+)\s*</level>(?:\s*<!--\s*(.*?)\s*-->)?", line)
        if not m:
            continue
        n += 1
        note = m.group(2) or ""
        print(f"{n:3d}. {m.group(1):<45s} {note}")


def _box(o):
    X, Y = float(o.get("X", 0)), float(o.get("Y", 0))
    w, h = float(o.get("width", 0.2)), float(o.get("height", 0.2))
    return X, Y, w, h


def cmd_brief(level):
    r = ET.parse(levels_dir() / level).getroot()
    info = r.find("levelinfo")
    print(f"# {info.findtext('title')}   (by {info.findtext('author')})")
    print(f"  {info.findtext('description')}\n")
    s = r.find(".//scenesize")
    print(f"scene: {s.get('width')} wide x {s.get('height')} tall   (Y is up)\n")

    print("TOOLBOX — what you may place:")
    for ti in r.findall(".//toolboxitem"):
        o = ti.find("object")
        dims = ""
        if o.get("width"):
            dims = f"  {o.get('width')} x {o.get('height')}"
        props = {p.get("key"): p.text for p in o.findall("property")}
        extra = f"   {props}" if props else ""
        print(f"  {ti.get('count')}x {o.get('type')}{dims}{extra}")

    print("\nFIXED SCENE:")
    for o in r.find(".//predefined"):
        if o.get("type") == "PostItHint":
            continue
        X, Y, w, h = _box(o)
        print(f"  {o.get('type'):<14s} centre=({X:5.2f},{Y:5.2f})  "
              f"x:[{X-w/2:5.2f},{X+w/2:5.2f}]  y:[{Y-h/2:5.2f},{Y+h/2:5.2f}]"
              + (f"  id={o.get('ID')}" if o.get("ID") else ""))

    print("\nGOALS:")
    for g in r.findall(".//goal"):
        p = {q.get("key"): q.text for q in g}
        obj = p.pop("object", "?")
        # isFail inverts the goal: it must NEVER happen. Dropping it reads a lose
        # condition as a win condition, which is worse than not printing it at all.
        kind = "MUST NOT HAPPEN" if g.get("isFail") == "true" else "must hold"
        print(f"  {obj:<12s} {kind:<16s} {g.get('type'):<15s} {p}")
    # This line used to claim thresholds latch. They do not, and saying so sent agents
    # looking for solutions that visit each condition in turn. Goal keeps no state
    # (Goal.h:51-53), every goal is recomputed each simulation step, and World::simStep
    # (World.cpp:412-429) only emits signalWon when every must-hold goal is true together.
    print("  (every 'must hold' goal has to be true in the SAME instant to win;")
    print("   a MUST NOT HAPPEN goal ends the run the moment it becomes true)")

    n = len(json.loads(KEYS.read_text()).get(str(level), [])) if KEYS.exists() else 0
    print(f"\n(the author solved this with {n} parts — the placements are not in the level file)")


def _scene_boxes(level):
    r = ET.parse(levels_dir() / level).getroot()
    out = []
    for o in r.find(".//predefined"):
        if o.get("type") == "PostItHint":
            continue
        X, Y, w, h = _box(o)
        out.append((o.get("ID") or o.get("type"), X - w / 2, X + w / 2, Y - h / 2, Y + h / 2))
    return out


def _part_size(part):
    """Size and shape kind. The kind decides how much the answer can be trusted.

    A RightRamp is a triangle in a 1x1 box, so box-overlap says it hits four balls that a
    real solve leaves alone -- blocking on a bounding box would reject working solutions.
    Circles and rectangles fill their box well enough to be certain about; polygons only
    warrant a warning."""
    import parts
    p = parts.parts().get(part, {})
    if p.get("radius"):
        return p["radius"] * 2, p["radius"] * 2, "circle"
    kind = "poly" if "Poly" in p.get("factory", "") else "rect"
    return p.get("width", 0.2), p.get("height", 0.2), kind


def cmd_check(level, places):
    """Does this placement start inside something? Answered by geometry, in milliseconds.

    An agent watched here placed a VolleyBall 0.055 INTO the floor, over and over, and
    learned nothing from it each time: a 20-second simulation came back NOT SOLVED, which
    is indistinguishable from a mechanism that simply did not work. Box2D also ejects an
    overlapping body violently at t=0, which the referee cannot tell from a mechanism -- so
    an overlap is not only a wasted run, it is how a fake solve gets made (see finding 4 in
    what-we-measured.md).
    """
    boxes = _scene_boxes(level)
    bad = False
    for spec in places:
        m = PLACEMENT.fullmatch(spec)
        if not m:
            sys.exit(f"bad placement {spec!r}; want Part@X,Y[,angle][,WxH]")
        part, x, y = m.group(1), float(m.group(2)), float(m.group(3))
        w, h, kind = _part_size(part)
        if m.group(5) is not None:                 # the placement resizes it
            w, h = float(m.group(5)), float(m.group(6))
        l, r_, b, t = x - w / 2, x + w / 2, y - h / 2, y + h / 2
        hits = []
        for name, bl, br, bb, bt in boxes:
            ox, oy = min(r_, br) - max(l, bl), min(t, bt) - max(b, bb)
            if ox <= 0.001 or oy <= 0.001:
                continue
            if kind == "circle":
                # Exact for a circle: the nearest point of the box to the centre has to be
                # inside the radius. A box test alone flags a ball resting in a corner.
                dx = max(bl - x, 0, x - br)
                dy = max(bb - y, 0, y - bt)
                if (dx * dx + dy * dy) ** 0.5 >= w / 2 - 0.001:
                    continue
            hits.append((name, ox, oy))
        print(f"{spec}   {part} is {w:g} x {h:g} ({kind}), so it occupies "
              f"x:[{l:.3f},{r_:.3f}] y:[{b:.3f},{t:.3f}]")
        if hits and kind == "poly":
            # The box is bigger than the shape, so this is a maybe and must not block.
            for name, ox, oy in hits:
                print(f"    bounding box touches {name} by {ox:.3f} x {oy:.3f} -- but "
                      f"{part} is a polygon inside that box, so this may well be fine")
        elif hits:
            bad = True
            for name, ox, oy in hits:
                print(f"    OVERLAPS {name}: {ox:.3f} across, {oy:.3f} deep")
        # Where it would come to rest if simply dropped here: the top of the highest thing
        # under it, plus half its height. Cheaper to be told than to discover by simulating.
        under = [bt for name, bl, br, bb, bt in boxes if bl < r_ and br > l and bt <= t]
        if under:
            print(f"    resting here would be y={max(under) + h / 2:.3f} "
                  f"(on top of the surface at y={max(under):.3f})")
        if not hits:
            print("    clear")
    return bad


# Part@X,Y, optionally an angle, optionally a size. Several levels can only be solved by
# resizing a ramp, so the size is part of the language rather than an extra.
PLACEMENT = re.compile(r"([A-Za-z][A-Za-z0-9]*)@(-?[\d.]+),(-?[\d.]+)"
                       r"(?:,(-?[\d.]+))?(?:,([\d.]+)x([\d.]+))?")


def key_to_places(hints):
    """Turn an answer-key entry into placement strings.

    Not every resizing hint sets both dimensions -- there are 155 width= and 150 height=
    across the level set -- so the missing one comes from the part's own default rather than
    being dropped, which would resize the part in one axis only and change the solution."""
    out = []
    for h in hints:
        spec = f"{h['object']}@{h['X']},{h['Y']}"
        if "angle" in h or "width" in h or "height" in h:
            spec += f",{h.get('angle', 0)}"
        if "width" in h or "height" in h:
            dw, dh, _ = _part_size(h["object"])
            spec += f",{h.get('width', dw)}x{h.get('height', dh)}"
        out.append(spec)
    return out


def _hints_xml(places):
    rows = []
    for i, spec in enumerate(places, 1):
        m = PLACEMENT.fullmatch(spec)
        if not m:
            sys.exit(f"bad placement {spec!r}; want Part@X,Y[,angle][,WxH] -- e.g. "
                     f"Skyhook@2.5,1.98 or Floor@2.5,1.98,-0.6 or LeftRamp@4.45,2.72,0,2.7x0.79")
        part, x, y = m.group(1), float(m.group(2)), float(m.group(3))
        angle = f' angle="{float(m.group(4)):.4f}"' if m.group(4) is not None else ""
        size = ""
        if m.group(5) is not None:
            size = f' width="{float(m.group(5)):.3f}" height="{float(m.group(6)):.3f}"'
        rows.append(f'        <hint number="{i}" object="{part}" X="{x:.3f}" Y="{y:.3f}"'
                    f'{angle}{size} />')
    return "    <hints>\n" + "\n".join(rows) + "\n    </hints>"


def _write_candidate(level, places, tag):
    src = (levels_dir() / level).read_text()
    out = re.sub(r"    <hints>.*?</hints>", _hints_xml(places), src, flags=re.S)
    if "<hints>" not in out:                       # level shipped without a hints block
        out = out.replace("</tbe-level>", _hints_xml(places) + "\n</tbe-level>")
    SOLVE.mkdir(parents=True, exist_ok=True)
    p = SOLVE / f"{pathlib.Path(level).stem}_{tag}.xml"
    p.write_text(out)
    return p


# GoalSerializer: POSITIONX=0, POSITIONY=1, ANGLE=2, ANYTHING=3 -> 4*base + kind
GOAL_TYPE = {1: "x changed", 2: "x below", 3: "x over",
             5: "y changed", 6: "y below", 7: "y over",
             9: "angle changed", 13: "anything changed"}


def explain(level):
    """What the referee saw: each goal object's last known position against its limit."""
    log = OUT / f"{pathlib.Path(level).stem}_claude.log"
    if not log.exists():
        return
    last = {}
    for line in log.read_text(errors="replace").splitlines():
        m = re.search(r"GOALCHK obj=(\S+) type=(\d+) now=\(([-\d.]+),([-\d.]+)\) limit=([-\d.]+)", line)
        if m:
            obj, ty, x, y, lim = m.group(1), int(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
            last[(obj, ty)] = (x, y, lim)
    if not last:
        return
    print("\n  what the referee saw at the end:")
    for (obj, ty), (x, y, lim) in sorted(last.items()):
        kind = GOAL_TYPE.get(ty, f"type{ty}")
        val = x if ty in (1, 2, 3) else y
        if ty in (2, 6):
            ok, gap = val < lim, val - lim
        elif ty in (3, 7):
            ok, gap = val > lim, lim - val
        else:
            ok, gap = None, 0.0
        mark = "met" if ok else ("MISSED" if ok is False else "?")
        tail = f"  (off by {abs(gap):.3f})" if ok is False else ""
        print(f"    {obj:<12s} {kind:<14s} needs {lim:>8.3f}   ended at ({x:.3f}, {y:.3f})  {mark}{tail}")


def cmd_frame(level, at="0.75"):
    """Pull a still out of the last attempt's video, for a model that can actually see one.

    `at` is a fraction of the clip (0.75) or a number of seconds (12s). The blind agents had
    to build this out of ffmpeg and ImageMagick every time; a sighted one should not have to
    build it at all.
    """
    stem = pathlib.Path(level).stem
    vid = OUT / f"{stem}_claude.mp4"
    if not vid.exists():
        sys.exit(f"no video for {stem}; run solve first (it records every attempt)")
    if at.endswith("s"):
        secs = float(at[:-1])
    else:
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(vid)], capture_output=True, text=True)
        secs = float(dur.stdout.strip()) * float(at)
    png = OUT / f"{stem}_t{secs:.1f}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{secs}", "-i", str(vid),
                    "-frames:v", "1", "-y", str(png)], check=True)
    print(f"{png}   ({secs:.1f}s into {vid.name})")


def _oid(raw, t, state):
    """A stable name for a traced object.

    Most objects in a level carry no id -- only the ones a goal refers to are named. Keyed on
    the id alone, every floor, ramp, chest and the part you placed shared the empty string
    and collapsed into one row, reporting one object's start against another's end. Keying an
    unnamed body on its position instead splits it into a new object every time it moves.

    The trace walks the world's object list in the same order every tick, so the position
    within a tick is the identity. It shifts if objects are created or destroyed mid-run --
    an explosion, say -- which is a limitation worth knowing rather than a reason not to."""
    raw = (raw or "").strip()
    if t != state.get("t"):
        state["t"], state["i"] = t, 0
    state["i"] += 1
    return raw or f"unnamed#{state['i']}"


def cmd_where(level, ids=None):
    """The path an object took, moment by moment, out of the simulation.

    Two agents independently hit the same wall here: they extracted video frames, tried to
    `read` the PNG, were told the model cannot see images, and fell back to writing
    ImageMagick pixel-diffs to find the ball. They did not need to. The trace already
    carries every object's position twice a simulated second; it was only ever summarised
    as start-and-end, which is why it looked like the detail was not there.
    """
    log = OUT / f"{pathlib.Path(level).stem}_claude.log"
    if not log.exists():
        sys.exit(f"no log yet for {level}; run solve first")
    paths, seen_at = {}, {}
    for line in log.read_text(errors="replace").splitlines():
        # id and type can both contain spaces -- levels name objects things like "the Pin".
        # A \S+ here silently captured "the", so trace and where returned nothing at all on
        # any level with a spaced id, which is most of the interesting ones.
        m = re.search(r"TRACE t=([\d.]+) id=(.*?) type=.*? pos=\(([-\d.]+),([-\d.]+)\) "
                      r"angle=([-\d.]+)", line)
        if not m:
            continue
        t, x, y, a = (float(m.group(1)), float(m.group(3)),
                      float(m.group(4)), float(m.group(5)))
        oid = _oid(m.group(2), t, seen_at)
        if ids and oid not in ids:
            continue
        paths.setdefault(oid, []).append((t, x, y, a))
    if not paths:
        sys.exit(f"no trace rows{' for ' + ', '.join(ids) if ids else ''} in {log.name}")
    for oid, rows in sorted(paths.items()):
        # A run replays the level twice (empty, then with your parts) and t restarts, so
        # split on the reset rather than drawing one impossible path through both.
        runs, cur = [], []
        for r in rows:
            if cur and r[0] < cur[-1][0]:
                runs.append(cur); cur = []
            cur.append(r)
        runs.append(cur)
        for n, run in enumerate(runs):
            label = f"{oid}  (play {n + 1} of {len(runs)})" if len(runs) > 1 else oid
            print(f"\n{label}")
            print(f"  {'t':>6}  {'x':>8}  {'y':>8}  {'angle':>7}")
            for t, x, y, a in run:
                print(f"  {t:6.2f}  {x:8.3f}  {y:8.3f}  {a:7.3f}")
            xs = [r[1] for r in run]; ys = [r[2] for r in run]
            print(f"  x {min(xs):.3f}..{max(xs):.3f}   y {min(ys):.3f}..{max(ys):.3f}"
                  f"   highest y={max(ys):.3f} at t={run[ys.index(max(ys))][0]:.2f}")


def cmd_trace(level, ids=None):
    """The recorded state timeline: what every object did, from the simulation itself."""
    log = OUT / f"{pathlib.Path(level).stem}_claude.log"
    if not log.exists():
        sys.exit(f"no log yet for {level}; run solve first")
    seen, seen_at = {}, {}
    for line in log.read_text(errors="replace").splitlines():
        m = re.search(r"TRACE t=([\d.]+) id=(.*?) type=.*? pos=\(([-\d.]+),([-\d.]+)\) angle=([-\d.]+)", line)
        if not m:
            continue
        t = float(m.group(1))
        x, y, a = float(m.group(3)), float(m.group(4)), float(m.group(5))
        oid = _oid(m.group(2), t, seen_at)
        if ids and oid not in ids:
            continue
        first, _ = seen.get(oid, (None, None))
        seen[oid] = (first if first is not None else (t, x, y, a), (t, x, y, a))
    print(f"{'object':<14s} {'start (x,y,angle)':<28s} {'end (x,y,angle)':<28s} moved")
    for oid, (f0, f1) in sorted(seen.items()):
        d = ((f1[1]-f0[1])**2 + (f1[2]-f0[2])**2) ** 0.5
        da = abs(f1[3]-f0[3])
        mark = "-" if d < 0.01 and da < 0.01 else f"{d:.3f} / {da:.3f} rad"
        print(f"{oid:<14s} ({f0[1]:7.3f},{f0[2]:7.3f},{f0[3]:6.3f})      "
              f"({f1[1]:7.3f},{f1[2]:7.3f},{f1[3]:6.3f})      {mark}")


def _log(level, places, verdict, empty="", replace_running=False, clip="", log=""):
    """Append an attempt for the dashboard. Overwrites the trailing RUNNING row."""
    OUT.mkdir(exist_ok=True)
    f = OUT / "attempts.jsonl"
    rows = [l for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
    if replace_running and rows and '"RUNNING"' in rows[-1]:
        rows.pop()
    # epoch as well as the clock: zed runs on CDT and the dashboard on EDT, so a row
    # written there and read here appeared an hour old the moment it landed, and the page
    # reported live work as stale. The wall-clock fields stay for reading logs by eye.
    # The run id joins this verdict to the conditions that produced it. Written by whoever
    # started the agent into out/run-id; absent for a hand-run attempt, which is honest --
    # those were not produced under a recorded set of conditions either.
    runid = ""
    rf = OUT / "run-id"
    if rf.exists():
        runid = rf.read_text().strip()
    rows.append(json.dumps({"level": level, "places": list(places), "verdict": verdict,
                            "empty": empty, "epoch": time.time(), "run": runid,
                            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
                            "time": datetime.datetime.now().strftime("%H:%M:%S"),
                            "clip": clip, "log": log}))
    f.write_text("\n".join(rows) + "\n")


def _watchable(path):
    """Is there anything on this clip, or is it a black screen?

    The dashboard has had this check since some recordings came back 93% black, but the
    archive did not, so every fast-failing attempt filed a one-second black stub and the
    footage grid filled up with them. Every dead clip measured bottoms out at YAVG 16.02,
    pure black; no live one goes below 118."""
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-vf",
         "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    ys = [float(m) for m in re.findall(r"YAVG=([0-9.]+)", r.stderr)]
    return bool(ys) and sum(1 for y in ys if y < 30) / len(ys) <= 0.3


def _archive(level):
    """Keep this attempt's video and log instead of letting the next one overwrite them.

    run-attempt.sh names its output after the level, so every attempt at a level clobbered
    the one before it and only the most recent survived. An attempt clip is ~150kB and a
    gzipped log ~20kB, so a thousand attempts is a couple of hundred megabytes -- there is
    no reason to be throwing away the history of what an agent tried.
    """
    stem = pathlib.Path(level).stem
    arc = OUT / "archive"
    arc.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    clip = logname = ""
    src = OUT / f"{stem}_claude.mp4"
    if src.exists() and src.stat().st_size > 2048 and _watchable(src):
        clip = f"archive/{stamp}_{stem}.mp4"
        shutil.copy2(src, OUT / clip)
    src = OUT / f"{stem}_claude.log"
    if src.exists():
        logname = f"archive/{stamp}_{stem}.log.gz"
        with open(src, "rb") as fh, gzip.open(OUT / logname, "wb") as gz:
            shutil.copyfileobj(fh, gz)
    return clip, logname


def _docker(args, env=None):
    cmd = ["docker", "run", "--rm",
           "-v", f"{OUT}:/out", "-v", f"{SOLVE}:/solve",
           "-v", f"{HERE/'run-attempt.sh'}:/run.sh",
           "-v", f"{HERE/'record-run.sh'}:/rec.sh"]
    for k, v in (env or {}).items():
        cmd += ["-e", f"{k}={v}"]
    return subprocess.run(cmd + [IMAGE] + args, text=True, capture_output=True)


def _check_parts(level, places):
    """Reject unknown part names up front. tbe ignores a hint naming a part that is not
    in the level's toolbox, places nothing, and can still report Level Won -- so an
    unchecked typo costs 90 seconds and returns a meaningless verdict."""
    root = ET.parse(levels_dir() / level).getroot()
    stock = {}
    for ti in root.findall(".//toolboxitem"):
        stock[ti.find("object").get("type")] = int(ti.get("count", 1))
    used = {}
    for spec in places:
        part = spec.split("@")[0]
        used[part] = used.get(part, 0) + 1
    for part, n in used.items():
        if part not in stock:
            sys.exit(f"'{part}' is not in this level's toolbox.\n"
                     f"  available: {', '.join(f'{k} x{v}' for k, v in stock.items())}")
        if n > stock[part]:
            sys.exit(f"you placed {n} x {part} but the toolbox has only {stock[part]}")


def _matches_author_key(level, places, tol=0.05):
    """A win that lands on the author's own placements is a transcription, not a solve.

    This is hygiene, not a control, and it is worth being clear about which. Stripping the
    hints stops the answer arriving unbidden alongside the level you were asked to solve.
    It cannot stop an agent that goes looking: `setup` clones the game with the hints still
    in it, so the answers pass through the agent's own machine, and failing that the
    upstream repository is public. Any adjudication that has to survive a motivated player
    belongs on a referee the player does not control -- see the hosting/attestation issue.

    Checked to date across all 22 recorded agent sessions: 50 incidental mentions of the key
    file (setup output, directory listings, a source line) and zero reads of its contents."""
    key = [(h["object"], h["X"], h["Y"])
           for h in json.loads(KEYS.read_text()).get(str(level), [])]
    if len(key) != len(places):
        return False
    for spec in places:
        part, _, rest = spec.partition("@")
        x, y = (float(v) for v in rest.split(",")[:2])
        hit = next((k for k in key if k[0] == part
                    and abs(k[1] - x) <= tol and abs(k[2] - y) <= tol), None)
        if hit is None:
            return False
        key.remove(hit)
    return True


def cmd_solve(level, places, record=True):
    OUT.mkdir(exist_ok=True)
    _check_parts(level, places)
    if cmd_check(level, places):
        sys.exit("\nREJECTED: a part starts inside something. Box2D ejects an overlapping "
                 "body violently at t=0 and the referee cannot tell that from a mechanism, "
                 "so this run would tell you nothing either way. Move it clear and retry.")
    cand = _write_candidate(level, places, "claude")
    print(f"candidate: {cand.name}")
    for p in places:
        print(f"  place {p}")
    print("\nadjudicating (empty must fail, yours must win) ...")
    _log(level, places, "RUNNING")
    # Record every attempt, not only the wins. A verdict says whether the level was won, not
    # whether the mechanism worked -- the spawn-overlap exploit was caught by a person
    # watching a replay, and the referee still cannot see it. Failures are also the ones
    # worth watching. Affordable since the regression runs at 4x: an attempt is ~20s, not 70.
    # DUR is a watchdog, not the budget. The level ends after BUDGET simulated
    # seconds (sim-budget.patch); this only bounds a game that has stopped stepping.
    env = {"DUR": "90", "RECORD": "1"} if record else {"DUR": "90"}
    r = _docker(["bash", "/run.sh", f"/solve/{cand.name}"], env)
    out = r.stdout.strip() or r.stderr.strip()
    print(out)
    # A win is only a solve if the parts were actually placed. tbe silently ignores a
    # hint naming a part that is not in this level's toolbox, and some levels then "win"
    # from an empty board -- which the game reports as Level Won just the same.
    log = OUT / f"{pathlib.Path(level).stem}_claude.log"
    added = None
    if log.exists():
        m = re.findall(r"Added (\d+) hints", log.read_text(errors="replace"))
        if m:
            added = int(m[-1])
    # A crash is its own outcome. Told apart from a failure so an agent stops tuning a
    # mechanism the referee never got to judge, and so the page can say what happened.
    for tag, why in (("CRASHED", "the game died"), ("STALLED", "the game stopped stepping")):
        if f"VERDICT      : {tag}" in out:
            clip, logname = _archive(level)
            _log(level, places, tag, "", replace_running=True, clip=clip, log=logname)
            print(f"\nADJUDICATED  : {tag}  ({why}; this says nothing about your parts)")
            return
    won = "VERDICT      : SOLVED" in out   # slot_Won, not the state label
    if won and added != len(places):
        verdict = f"INVALID ({added} of {len(places)} parts placed)"
    elif won and _matches_author_key(level, places):
        verdict = "COPIED"
    else:
        verdict = "SOLVED" if won else "NOT SOLVED"
    empty = ""
    clip, logname = _archive(level)
    _log(level, places, verdict, empty, replace_running=True, clip=clip, log=logname)
    explain(level)
    # run.sh only knows whether slot_Won fired; the adjudicated verdict is this one, and
    # it goes last so a reader skimming for the outcome cannot stop at the raw SOLVED.
    print(f"\nADJUDICATED  : {verdict}")
    if verdict.startswith("COPIED"):
        print("  These are the author's own placements. The level was won, but not solved.")


def cmd_record_missing():
    """Record a replay for every solved level that does not have one yet."""
    import json as _json
    best = {}
    for f in [OUT / "attempts.jsonl"] + sorted(OUT.glob("attempts-*.jsonl")):
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = _json.loads(line)
            if r.get("verdict") == "SOLVED":
                best[pathlib.Path(r["level"]).stem] = r
    todo = [(k, r) for k, r in best.items() if not (OUT / f"{k}_placed.mp4").exists()]
    print(f"{len(best)} solved, {len(todo)} without a replay")
    for i, (stem, r) in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {stem}: {' '.join(r['places'])}")
        try:
            cmd_record(r["level"], r["places"])
        except Exception as e:                    # one bad level must not stop the batch
            print(f"    failed: {e}")


def cmd_record(level, places):
    """Promote placements into the scene and film it — visualisation, not adjudication."""
    OUT.mkdir(exist_ok=True)
    src = (levels_dir() / level).read_text()
    objs = []
    for spec in places:
        m = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)@(-?[\d.]+),(-?[\d.]+)(?:,(-?[\d.]+))?", spec)
        part, x, y = m.group(1), m.group(2), m.group(3)
        angle = f' angle="{m.group(4)}"' if m.group(4) is not None else ""
        root = ET.parse(levels_dir() / level).getroot()
        proto = None
        for ti in root.findall(".//toolboxitem"):
            if ti.find("object").get("type") == part:
                proto = ti.find("object")
        dims = ""
        if proto is not None and proto.get("width"):
            dims = f' width="{proto.get("width")}" height="{proto.get("height")}"'
        objs.append(f'            <object{dims} X="{x}" Y="{y}" type="{part}"{angle}/>')
    out = src.replace("        </predefined>", "\n".join(objs) + "\n        </predefined>", 1)
    out = re.sub(r"    <hints>.*?</hints>", "    <hints>\n    </hints>", out, flags=re.S)
    SOLVE.mkdir(parents=True, exist_ok=True)
    p = SOLVE / f"{pathlib.Path(level).stem}_placed.xml"
    p.write_text(out)
    print(f"recording {p.name} ...")
    r = _docker(["bash", "/rec.sh", f"/solve/{p.name}"])
    print(r.stdout.strip() or r.stderr.strip())
    print(f"video: {OUT}/{p.stem}.mp4")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    what = sys.argv[1]
    if what == "setup":
        cmd_setup()
    elif what == "strip":
        cmd_strip()
    elif what == "levels":
        cmd_levels()
    elif what == "brief":
        cmd_brief(sys.argv[2])
    elif what == "solve":
        cmd_solve(sys.argv[2], [a for a in sys.argv[3:] if not a.startswith("-")],
                  record="--no-record" not in sys.argv)
    elif what == "trace":
        cmd_trace(sys.argv[2], sys.argv[3:] or None)
    elif what == "frame":
        cmd_frame(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "0.75")
    elif what == "check":
        sys.exit(1 if cmd_check(sys.argv[2], sys.argv[3:]) else 0)
    elif what == "where":
        cmd_where(sys.argv[2], sys.argv[3:] or None)
    elif what == "record-missing":
        cmd_record_missing()
    elif what == "record":
        cmd_record(sys.argv[2], [a for a in sys.argv[3:] if not a.startswith("-")])
    else:
        sys.exit(__doc__)
