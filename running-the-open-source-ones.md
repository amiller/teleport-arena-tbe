# Can we run the open-source ones headless?

Asked 2026-08-13: can these be run in an Xvfb container, so an agent could play them and we
could look at them without installing anything? Answered by doing it, not by reading.

**Short answer: one of the four, and it is the only one worth running.**

| Project | Runs headless? | Evidence |
|---|---|---|
| **The Butterfly Effect** | **Yes — verified** | Built from a clean image and screenshotted at level 1. `harness/Dockerfile.tbe` |
| OpenTIM | No, and there is nothing to run | Requires the original commercial game assets |
| sevren Java clone | Untested | Student project; nothing to learn from it |
| SimpleMachines | Effectively no | A Unity *project*, needs the Editor. Not container-shaped |

## The Butterfly Effect — works, reproducibly

`harness/Dockerfile.tbe` builds it and `run-headless.sh` starts it on a virtual
display and screenshots it. Verified end to end from a clean `docker build`.

Three things cost time and are worth recording:

1. **`gettext` is required and is not in the project's own `INSTALLING.md`.** Without it the
   build fails with `Error 127` on `i18n/tbe_levels_be.gmo` — a missing-binary error that
   looks nothing like a missing package.
2. **Run the installed binary, not the build-tree one.** `build/src/tbe` looks for levels at
   `../share/games/tbe/levels/levels.xml` and aborts with a modal dialog. `make install`
   puts a working binary at `/usr/games/tbe`.
3. **Box2D is vendored** in `src/Box2D`. No external physics dependency at all.

**On the age.** The 2021 last-commit date is a real constraint but a narrow one: it pins the
image to Qt5, and the project declares `cmake_minimum_required(VERSION 2.8.12)`, which CMake
4.x refuses outright. Ubuntu 22.04 satisfies both. Beyond that, nothing about the age got in
the way — it compiled with no source patches and ran first try. Untested: whether a newer
base still works.

## What it was actually worth: the level format

The reason to run it was never to play it. It ships **83 finished levels** in a declarative
XML format, and that format answers questions we have open.

**Goals are conjunctions of threshold predicates on named objects.** 695 goals across the
83 levels, in only four types:

| type | count |
|---|---|
| `positionchange` | 604 |
| `statechange` | 79 |
| `escapedPingusCount` | 7 |
| `distance` | 5 |

A level's win condition is an AND over several of these. `bridge_gap` requires the Pin to
cross `xover 4.3`, **and** the Ball to cross `xover 4.3`, **and** the Ball to fall
`ybelow 0.5`. Half the levels use one goal; the rest use two to sixteen.

**This bears directly on our own bug.** `positionchange`/`ybelow` is precisely the shape of
our `pass-through-down` failure — a latching threshold crossing, the thing that let 51 of 60
designs "solve" THE GAP by falling through the target
(tracked separately in our own issues). tbe
does not appear to solve the latching problem; it *dilutes* it, by requiring several cheap
predicates at once. Satisfying one threshold by accident is easy. Satisfying four, on
different named objects, is not. That is a cheaper mitigation than a smarter predicate and
we should try it before writing one.

**Two other things worth stealing:**

- **The toolbox is counted.** `<toolboxitem count="2">` — the player gets exactly two I-beams,
  and each item can carry per-instance constraints like `Resizable: none`. That is our stock
  catalogue, already designed, including the scarcity that makes a choice a choice.
- **`levels.xml` is an annotated teaching order.** Each entry carries a comment naming what
  that level introduces — "Introduces rotation", "Introduces dynamite and detonator box" —
  plus hard ordering constraints ("MUST BE FIRST LEVEL"). Our Track D has a stated tier-2 gap
  and no vocabulary for what a level teaches. This is the artifact that closes it.
- Levels also ship a `<hints>` block giving reference solution positions — the "every level
  ships with a reference solution the referee must accept" idea, already in production.

## Why not the others

**OpenTIM** is a reverse-engineering effort, not a game: `src/resource_dos.rs`,
`level_file_format.rs`, a `reverse-engineering/` directory of Ghidra scripts. Its README states
it "requires the user to provide the original game assets," so it cannot be run in a container
without owning a copy of the 1993 game. Its documented **original TIM level format** is
readable as a source without running anything, which is the only thing we would want from it.

---

## Is there a headless, fast-iteration version? Not shipped — but the codebase is built for one

Asked as a follow-up, and it is the right question: the GUI is irrelevant to us. What we want
is *submit a configuration, step the physics, get a verdict*, as fast as possible. Checked in
the source rather than guessed.

**The model layer has zero GUI dependencies.** Across 22 `.cpp` files in `src/model/`, the
count of `QGraphics*`, `QWidget`, `QPixmap`, `QPainter` and `QApplication` references is
**zero**. The only Qt types it uses are QtCore: QString (118), QObject (12), QPointF (10),
QList (7), QStringList, QDebug, QMap, QSet.

**The referee is in that layer too:**

- `World::simStep()` (`src/model/World.cpp:362`) advances the physics.
- `Goal::checkForSuccess()` (`src/model/Goal.h:51`) is a pure virtual with one implementation
  per goal type — `GoalDistance`, and the position/state variants behind the four types
  counted above.

**And the authors already did the hard part.** `test/src/` ships `StubDrawObject`,
`StubDrawWorld` and `StubPivotPoint` — stub implementations of the view interface, written so
the model can be exercised with no GUI at all.

**So a headless runner is glue, not a port:** load XML via `loadsave/` → build `World` →
place the player's objects → loop `simStep()` → poll `checkForSuccess()` → print a verdict.
It links QtCore, QtXml and the vendored Box2D. No X server, no Xvfb, no Qt Widgets, no Svg.

**What the work actually is.** The existing testers are qmake-era (`.pro` files) and the top
level `CMakeLists.txt:62` excludes `test` from the build, so they are almost certainly
bit-rotted. Reviving them, or writing one new headless `main` against the stubs, is the job.
Small and well-scoped — but unestimated, because nobody has tried it yet.

### The catch, and it is not technical

**tbe is GPL-2.0.** See NOTICE.md for how that shapes this repository's licensing.
Deriving a headless referee from tbe's model would make that derived work GPL-2.0, and the
licence question for our own repos is currently unanswered rather than answered permissively.

That points at a cleaner split, and it is the recommendation:

- **Read tbe for its design**, which is where the value is anyway — the counted toolbox, the
  conjunction-of-thresholds goal format, the annotated teaching order. Reading costs nothing
  and encumbers nothing.
- **Do not vendor its code** into our referee unless we have decided to be GPL-2.0.
- Our own headless fast path is tracked separately, the
  FAB/FIT stages, whose entire justification is rejecting candidates *without* simulating
  them. That is a stronger position than tbe's: tbe still has to run the physics to know.
