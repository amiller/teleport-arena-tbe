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
| `fast-sim.patch` | `src/view/ViewWorld.cpp`, `src/view/RegressionTest.cpp` | runs a regression at 4x instead of half real time, scales the driver's waits to match, and stops the progress dialog covering the playfield |

`fast-sim.patch` is the one worth reading if you are doing anything similar. Two notes are in
its comments and both cost time to find: TBE advances its simulated clock by
`simStep() * 2 * theSimSpeed` milliseconds through `QTime::addMSecs`, which takes an **int**,
so the "real fast" setting of 60 truncates the advance to zero and the stepping loop then
saturates the event loop; and the regression driver's progress dialog opens in the middle of
the play area, where it covers the thing you are trying to record.

## The answer keys

`answer-keys.json` holds each level's `<hints>` block — the level author's own winning
placements — lifted out of the level files by `tbe.py setup`, so that an agent reading the
level it has been asked to solve does not get the answer with it.

This is TBE's content, not ours: it is copied out of the game's level XML, which ships under
the same licence. Nothing here is secret — it is all in the upstream repository — but it is
theirs, so it lives on this side of the line.
