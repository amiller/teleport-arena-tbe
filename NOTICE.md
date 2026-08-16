# Licensing, and where the line falls

This repository is **MIT**, except `tbe-derived/`, which is **GPL-2.0**.

## Why the split

[The Butterfly Effect](https://github.com/the-butterfly-effect/tbe) is GPL-2.0. Work that
derives from it has to stay GPL-2.0; work that merely drives it does not. The split follows
that line rather than convenience:

**GPL-2.0 — `tbe-derived/`**

- The three patches. A diff against GPL source is a derivative of it. This is not a close
  call.
- `answer-keys.json`, conservatively. It is the levels' own `<hints>` blocks, copied out of
  TBE's level XML — content of the game, not a description of it. The tool that extracted it
  is ours; what it extracted is not.

  The levels are **not** uniformly GPL, which is worth knowing before you reuse them. Each
  level declares its own licence and across all 112 that is **106 CC0, 5 GPLv2, 1 WTFPL**.
  Only three of the keys we hold come from a GPLv2 level:
  `finished/cola-powered-bike.v2.xml`, `attic/poing-poing-poing.xml` and
  `needs-polish/geyser.xml`. The other seventy-one are CC0, which carries no obligations at
  all. The whole file sits under GPL-2.0 here because it is one file and three of its entries
  require it; if you want the CC0 majority under CC0 terms, take them from upstream where the
  per-level declaration travels with each one.

**MIT — everything else**

- `harness/tbe.py`, `parts.py`, `dashboard.py`, and the shell scripts. These contain no TBE
  code. They run the game as a separate process, in a container, and read its output.
- `parts.py` parses TBE's source at runtime on your machine to build a table of part
  dimensions and masses. It ships none of that source, and measurements of a thing are facts
  rather than expression. The generated table is not checked in.
- The Dockerfiles are build recipes and carry no TBE code themselves.

## Two things to be careful about

**A published image is a distribution.** These Dockerfiles build TBE from source and patch
it. Running one locally is your own business; **publishing the resulting image** means
distributing a modified GPL-2.0 program, and the GPL obligations — source, licence,
modification notices — come with it. Nothing here publishes an image.

**This is a reading, not legal advice.** It is written down so the reasoning can be checked
and argued with rather than assumed. If you need certainty, ask someone qualified; if you
think the line is in the wrong place, the argument above is the thing to attack.

## Upstream

The Butterfly Effect, by Klaas van Gend and contributors —
<https://github.com/the-butterfly-effect/tbe>, GPL-2.0. The game is not vendored here;
`tbe.py setup` clones it. All level content, artwork and level design is theirs.
