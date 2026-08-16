# GPL-2.0 material

Everything in this directory is a derivative of [The Butterfly
Effect](https://github.com/the-butterfly-effect/tbe), which is GPL-2.0. It is therefore
**GPL-2.0**, and `COPYING` here is that licence. The rest of this repository is MIT — see the
root `LICENSE` and `NOTICE.md` for why the line falls where it does.

## The patches

Diffs against TBE's own source, applied when the container image is built. Each one is a
change to the game, so each one is a derivative work of it.

| patch | what it changes | why |
|---|---|---|
| `goal-feedback.patch` | `src/model/Goal.cpp` | logs what each position goal sees against its limit, so a failed attempt says *why* rather than just "no" |
| `world-trace.patch` | `src/model/World.cpp` | logs every object's id, position and angle twice a simulated second, so a run can be debugged from numbers instead of video |
| `fast-sim.patch` | `src/view/ViewWorld.cpp`, `src/view/RegressionTest.cpp` | runs a regression at 4x instead of half real time, steps a fixed amount per tick, and stops the progress dialog covering the playfield |
| `sim-budget.patch` | `src/view/ViewWorld.cpp`, `src/view/RegressionTest.cpp` | ends a level after a number of **simulated** seconds rather than a wall-clock wait standing in for one |

`fast-sim.patch` is the one worth reading if you are doing anything similar. Two notes are in
its comments and both cost time to find: TBE advances its simulated clock by
`simStep() * 2 * theSimSpeed` milliseconds through `QTime::addMSecs`, which takes an **int**,
so the "real fast" setting of 60 truncates the advance to zero and the stepping loop then
saturates the event loop; and the regression driver's progress dialog opens in the middle of
the play area, where it covers the thing you are trying to record.

`sim-budget.patch` is the one to take if you are adjudicating with this driver, because
without it the driver does not really adjudicate. TBE's regression runner waits out a level
with a wall-clock delay, `myLevelDurationSeconds * 1000` milliseconds, standing in for that
many seconds of physics. On a machine that cannot deliver physics that fast the wait expires
first and the level is cut short — and a level cut short reports a working solution as a
failure. Across 939 of our own adjudications, only the 41 that ended in a win ever reached
the driver's own `Regression Successful`; the other 892 were interrupted, at anywhere from
36.3 to 45.8 simulated seconds for the same nominal 25-second budget, varying with nothing
but machine load. The patch has `ViewWorld` accumulate the simulated seconds it steps and
has the state machine wait on that number. A win or a death still short-circuits.

One thing it exposes rather than fixes: a level whose simulation stops advancing will now
wait forever, because the clock it is waiting on has stopped. `harness/run-attempt.sh`
watches the log for silence and calls that **STALLED**, which is a different thing from a
crash and a very different thing from a loss.

## The answer keys

`answer-keys.json` holds each level's `<hints>` block — the level author's own winning
placements — lifted out of the level files by `tbe.py setup`, so that an agent reading the
level it has been asked to solve does not get the answer with it.

This is TBE's content, not ours: it is copied out of the game's level XML. Nothing here is
secret — it is all in the upstream repository — but it is theirs, so it lives on this side of
the line.

It is filed under GPL-2.0 conservatively rather than accurately. Levels declare their licence
individually and most are far more permissive than the code: across all 112 levels it is
**106 CC0, 5 GPLv2, 1 WTFPL**. Exactly three of the 74 keys here come from a GPLv2 level —
`finished/cola-powered-bike.v2.xml`, `attic/poing-poing-poing.xml`, `needs-polish/geyser.xml`
— and the rest are CC0. Because this is a single file, it takes the strictest licence among
its contents. Take the CC0 levels from upstream if you want them on CC0 terms.
