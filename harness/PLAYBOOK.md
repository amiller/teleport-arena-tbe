# Playing The Butterfly Effect: what the engine actually does

Everything here is read out of the game's source, and the commands that generate it are
named so you can check any line of it yourself. It exists because across every TBE session
an agent has run, **153 of 518 shell commands — just under a third — were reading the C++ to
find out what a part weighs or what a goal checks**, against 21 commands that actually
attempted a solution. The same files, over and over: `World.cpp` 33 times,
`AbstractObject.cpp` 27, `RectObject.cpp` 23, `Goal.cpp` 10.

## You cannot see

The model behind this agent has no vision. An agent on 13 August extracted video frames,
called `read` on the PNG, and got back:

> "The model doesn't support images. So I can't view the frames directly."

It then wrote ImageMagick code to diff two frames and find the ball by pixel. A second agent
independently did the same thing an hour later. Do not spend your time there — what the
scene is doing is available as numbers:

    python3 playtest/harness/tbe.py brief <level>    the scene, the toolbox and the goals
    python3 playtest/harness/tbe.py trace <level>    every object's position and angle,
                                                     twice a simulated second, from the sim

`trace` is the sim's own state, not an estimate off a picture. It is strictly better than
anything you could recover from a frame.

## The parts

    python3 playtest/harness/parts.py            every placeable part, with its real numbers
    python3 playtest/harness/parts.py --json     same, machine-readable

Generated from the factory declarations in `src/model/*.cpp`, so it cannot drift from the
engine the way a hand-written table would. `mass 0` means fixed in place — it will not move
no matter what hits it. `bounce` is Box2D restitution, and **Box2D mixes two bodies by
taking the larger of the two**, so one bouncy object is enough to make a collision bouncy.

Gravity is `-9.81` (`World::getG`, World.h:256). The physics timestep is fixed at
`theDeltaTime = 0.004` s (World.cpp:29).

## The goals, and what a win actually requires

Read the goals off `tbe.py brief`. Two things about them are not obvious and both have cost
time here:

**`isFail="true"` inverts a goal into a lose condition.** A level's goal block mixes them.
`turn-it-around` reads as *"BowlingPin xbelow 1.8"* and *"BowlingPin xover 2.6"*, which looks
like one pin being asked for two contradictory things. It is not: `xbelow 1.8` is
`isFail="true"`. The level is *get the pin past x=2.6, and you lose if it goes left of 1.8*.
`tbe.py brief` used to omit `isFail` and it produced exactly this misreading — see the
correction note in `what-we-measured.md`.

**Goals do not latch, and a win needs all of them at once.** `Goal` holds no state
(`Goal.h:51-53` — one pure-virtual `checkForSuccess()` and an `isFail` flag). Every goal is
recomputed from scratch on every simulation step, and `World::simStep` (World.cpp:412-429)
emits `signalWon` only when *every* non-fail goal is true **in the same step**; any fail goal
coming true emits `signalDeath` immediately. So a solution has to hold all the win conditions
simultaneously, not visit them one at a time.

(The latching bug in `what-we-measured.md` findings 2 and 3 is real, but it is in Teleport
Arena's own kernel — `levels.py:Level.score()` — not in TBE.)

## What counts as a solve

`tbe.py solve` runs the game's own regression referee: it plays the level empty, which must
fail, then plays it with your parts, which must win. The only evidence of a win is
`slot_Won` in the game's log. Two ways to get a verdict that is not a solve:

- **COPIED** — your placements match the level author's own answer key. The keys are stripped
  out of the level files at setup so the answer does not arrive alongside the question.
  That is hygiene rather than a lock: the answers exist upstream and pass through this
  machine during setup. Transcribing one is not solving it, and the record says so.
- **A part overlapping something already in the scene.** Box2D ejects an overlapping body
  violently at t=0 and the referee cannot tell that explosion from a mechanism. Check your
  placement against the scene geometry in `brief` before running it.

## Check before you simulate

    python3 playtest/harness/tbe.py check <level> Part@X,Y ...

Instant, no simulation. It tells you whether the part starts inside something, and where it
would come to rest if simply dropped there. `solve` runs it first and refuses to simulate an
overlapping placement, because such a run tells you nothing: Box2D ejects an overlapping body
violently at t=0, so you get either a meaningless failure or a fake win. An agent before you
put a VolleyBall 0.055 INTO the floor and did it again and again, spending twenty seconds a
time to be told "NOT SOLVED", which reads exactly like a mechanism that did not work.

For a polygon part (a ramp, a wedge) the check reports a bounding-box touch as a maybe
rather than a refusal: the shape is smaller than its box, so a touch is often fine.

## You can resize a part

    LeftRamp@4.452,2.715,0,2.697x0.786

A placement is `Part@X,Y`, optionally an angle, optionally a size. **The size is part of the
solution language, not a detail**: 155 placements across the level set resize a part, and
several levels cannot be solved without it. A ramp stretched to 2.7 wide is a different
mechanism from the default one, not the same mechanism nudged.

This was missing until it was measured: 13 of the 16 levels whose own author solution failed
to win were failing only because the harness dropped the size and placed a default-sized
part instead. Six of them win now.

## The loop

    tbe.py brief <level>                     read the scene, the toolbox, the goals
    tbe.py check <level> Part@X,Y            before every solve; it is free
    parts.py                                 look up anything you are about to place
    tbe.py solve <level> Part@X,Y[,angle][,WxH]   adjudicate a candidate
    tbe.py trace <level>                     after a failure, read what actually moved

Read `trace` after every failure rather than guessing again. The runs are fast — the
regression plays at the engine's ceiling of about 6 seconds of physics per wall second, so
an attempt is roughly 20 seconds, not 70.
