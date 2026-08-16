#!/usr/bin/env python3
"""The part sheet, read out of the game's C++ rather than written by hand.

    python3 parts.py            the table
    python3 parts.py --json     the same, as JSON

Why this exists: across every TBE session an agent has run, 153 of 518 shell commands --
just under a third -- were reading the engine's source to find out what a part weighs, how
bouncy it is, or how big it is. The same files over and over: World.cpp 33 times,
AbstractObject.cpp 27, RectObject.cpp 23. That is the single largest use of an agent's time
on this game, and none of it is about solving a puzzle.

It is generated rather than transcribed on purpose. A hand-written table would drift from
the source the first time upstream changed a mass, and an agent trusting a stale number is
worse off than one that read the file.
"""
import json
import pathlib
import re
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / "tbe-src" / "src" / "model"

# What the trailing numeric arguments of each factory mean. Taken from the constructor
# declarations in the matching header; the comment above the rect objects in RectObject.cpp
# spells the order out too ("anImageName, aWidth,aHeight, aMass, aBounciness").
SHAPES = {
    "CircleObjectFactory": ["radius", "mass", "bounce"],
    "AbstractRectObjectFactory": ["width", "height", "mass", "bounce"],
    "AbstractPolyObjectFactory": ["width", "height", "mass", "bounce"],
}

DECL = re.compile(r"static\s+(\w+Factory)\s+\w+\s*\(", re.S)
STRINGS = re.compile(r'"((?:[^"\\]|\\.)*)"')
NUMBERS = re.compile(r"(?<![\w.])(-?\d+\.?\d*)(?![\w.])")


def arglist(text, open_paren):
    """The text between this '(' and its matching ')', with string literals respected.

    Regex cannot do this: a polygon outline is a string full of parentheses --
    "(0.02,0.17)=(-0.02,0.17)=..." -- and matching to the first ')' or ');' cut the
    argument list off before the numbers, so the mass and bounciness reported were
    actually outline coordinates.
    """
    depth, i, in_str = 0, open_paren, False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1:i]
        i += 1
    return ""


def parts():
    out = {}
    for f in sorted(SRC.glob("*.cpp")):
        text = f.read_text(errors="replace")
        for m in DECL.finditer(text):
            kind = m.group(1)
            rest = arglist(text, m.end() - 1)
            strings = STRINGS.findall(rest)
            if not strings:
                continue
            name = strings[0]                          # the internal name a hint must use
            strings = strings[1:]
            # Numbers only from OUTSIDE string literals. A poly object's outline
            # ("(-0.5,-0.5);(0.5,-0.5)...") and its trailing default-properties string both
            # contain numbers, and counting those shifted the mapping far enough to report
            # negative masses.
            nums = [float(n) for n in NUMBERS.findall(STRINGS.sub("", rest))]
            fields = SHAPES.get(kind)
            rec = {"part": name, "factory": kind, "source": f.name,
                   "display": strings[0] if strings else "",
                   "tooltip": (strings[1] if len(strings) > 1 else "").replace("\\n", " ")}
            if fields and len(nums) >= len(fields):
                # The numbers are the tail of the argument list; anything earlier is a
                # string. Take the last len(fields) of them so an outline or a properties
                # string in between cannot shift the mapping.
                rec.update(dict(zip(fields, nums[-len(fields):])))
            out[name] = rec
    return out


def table(ps):
    cols = ["part", "width", "height", "radius", "mass", "bounce"]
    rows = [[p.get(c, "") for c in cols] for p in ps.values()]
    rows = [[f"{v:g}" if isinstance(v, float) else str(v) for v in r] for r in rows]
    w = [max(len(str(c)), *(len(r[i]) for r in rows)) for i, c in enumerate(cols)]
    line = lambda vals: "  ".join(str(v).ljust(w[i]) for i, v in enumerate(vals)).rstrip()
    yield line(cols)
    yield line(["-" * x for x in w])
    for p, r in zip(ps.values(), rows):
        yield line(r)
    yield ""
    yield "mass 0 means fixed in place: it will not move no matter what hits it."
    yield "bounce is Box2D restitution. Box2D mixes two bodies by taking the LARGER of the"
    yield "two, so one bouncy object is enough to make a collision bouncy."
    yield ""
    yield "Behaviours that are not numbers:"
    for p in ps.values():
        if p.get("tooltip") and not p.get("mass"):
            yield f"  {p['part']:22} {p['tooltip'][:90]}"


if __name__ == "__main__":
    ps = parts()
    if "--json" in sys.argv:
        print(json.dumps(ps, indent=1))
    else:
        print("\n".join(table(ps)))
