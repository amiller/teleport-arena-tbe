# teleport-arena-tbe

**[Watch agents play it →](https://amiller.github.io/teleport-arena-tbe/)**

Make [The Butterfly Effect](https://github.com/the-butterfly-effect/tbe) — a 2D physics
puzzle game in the *Incredible Machine* line — playable by a program, and adjudicated by the
game itself rather than by something we wrote about it.

You give it a level and a list of parts with coordinates. It plays the level empty to confirm
the level fails on its own, resets, inserts your parts, plays again, and reports whether the
game raised its own "won" event. About 17 seconds a go, headless, in a container.

```
$ python3 harness/tbe.py setup                    # clone the game, lift out the answer keys
$ python3 harness/tbe.py brief finished/bouncing_balls.xml
$ python3 harness/tbe.py solve finished/bouncing_balls.xml RightRamp@1.200,2.100

candidate: bouncing_balls_claude.xml
  place RightRamp@1.200,2.100
adjudicating (empty must fail, yours must win) ...
ADJUDICATED  : SOLVED
```

## Why this exists

We wanted to know what happens when an agent plays an open-ended construction game. Most of
the work turned out to be making the answer trustworthy, because the interesting failure is
not the agent failing — it is the harness saying *solved* when nothing was solved.

The verdicts are the shape of what we learned:

| | |
|---|---|
| `SOLVED` | the game's own `slot_Won` fired. The only evidence we accept |
| `NOT SOLVED` | the referee ran and the level was not won. A real result |
| `UNPROVEN` | recorded as a win, but nothing in the game's log confirms it |
| `COPIED` | the placements match the level author's own answer key |
| `INVALID` | won, but the parts were never placed — the game silently drops a hint naming a part that is not in that level's toolbox |
| `CRASHED` | the game died before the referee ruled. Says nothing about your parts |

The last three each exist because we shipped a version without them and drew a wrong
conclusion. `CRASHED` was added after an agent spent 31 attempts and twelve minutes being
told its mechanism was wrong by a process that had already segfaulted.

## The commands

```
tbe.py setup                     fetch the game; move each level's answer key out of it
tbe.py levels                    the play order, and what each level introduces
tbe.py brief  <level>            the scene, the toolbox and the goals, as text
tbe.py check  <level> P@X,Y ...  does the part start inside something? instant, no simulation
tbe.py solve  <level> P@X,Y ...  write a candidate and adjudicate it
tbe.py where  <level> [ids...]   the path an object took, moment by moment, from the sim
tbe.py trace  <level> [ids...]   what every object did, summarised
tbe.py frame  <level> [0.75|12s] a still from the last attempt, for a player that can see
parts.py                         every placeable part, with its real mass and bounciness
```

`check` is the one that changed the loop most. A placement that begins inside the floor comes
back `NOT SOLVED`, which is indistinguishable from a mechanism that did not work — an agent
here made that mistake across 118 attempts. Geometry answers it in milliseconds, so `solve`
runs it first and refuses to simulate an overlap. That also closes a hole in the referee:
Box2D ejects an overlapping body violently at t=0, and a win caught on the way out is not a
solution.

`parts.py` is generated from the game's own factory declarations rather than transcribed, so
it cannot drift. Across every session we recorded, **153 of 518 shell commands were the agent
reading the game's C++ to find out what a part weighs** — against 21 that attempted a
solution. That is what the generated sheet and `harness/PLAYBOOK.md` are for.

## Watching it

`harness/dashboard.py` serves a page: the live frame of whatever is simulating, every
attempt's recording, the verdicts, and — if the players are agents whose transcripts you can
read — what the agent is thinking between attempts.

```
$ python3 harness/dashboard.py                     # http://127.0.0.1:8765
$ BIND=0.0.0.0 python3 harness/dashboard.py        # reachable from elsewhere
$ REMOTE=somehost python3 harness/dashboard.py     # also watch agents on another machine
```

It listens on localhost by default deliberately: the console can start and stop agents.

The remote half (`sync-agents.sh`, and the console's start/stop) is written around our own
setup — agents in per-level working copies on another machine — and is configured entirely
through `REMOTE`, `REMOTE_REPO` and `REMOTE_WORKTREES`. Unset, everything local still works.

## A note on what agents find hard here

Two things surprised us and are worth knowing before you point a model at this:

**Whether the model can see matters, and the model may not tell you.** One agent extracted
video frames, called its read tool on a PNG, and got back *"The model doesn't support
images"*. It then wrote ImageMagick pixel-diffs to locate the ball. A second did the same an
hour later. `tbe.py where` exists because the simulation already knows every object's path —
better than anything recoverable from a picture.

**A cap requested in a prompt is not a cap.** Told to stop at 8 attempts, one run made 118.

## Licence

MIT, except `tbe-derived/`, which is GPL-2.0 because it derives from the game. The reasoning
is in [NOTICE.md](NOTICE.md), including the part that is easy to get wrong — the answer keys
are the game's content, not ours. Building an image from these Dockerfiles is fine;
publishing one means distributing a modified GPL-2.0 program.

The Butterfly Effect is by Klaas van Gend and contributors. It is not vendored here — `setup`
clones it — and all level design, artwork and content is theirs.
