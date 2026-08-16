#!/usr/bin/env bash
# Build the image the harness runs against.
#
# There are several Dockerfiles because the game was brought up in stages, and they stack:
#
#   Dockerfile.debug   ubuntu -> tbe built as a DEBUG build, which is the only one whose
#                      --regression driver exists at all (it is inside #ifdef QT_DEBUG)
#   Dockerfile.wm      + a window manager, so key events land where they are aimed
#   Dockerfile.feedback + our three patches: goal logging, world tracing, and the speedup
#
# Only the last image, tbe-fb, is what tbe.py actually uses. Dockerfile.tbe is the plain
# release build kept for reference; it cannot run a regression.
#
#   ./build.sh          builds the chain
#
# Run it from the repository root: Dockerfile.feedback copies the patches out of
# tbe-derived/, so the build context has to be the root and not harness/.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> tbe-dbg      (debug build; the regression driver only exists in one)"
docker build -q -f harness/Dockerfile.debug -t tbe-dbg harness/

echo "==> tbe-dbg-wm   (+ window manager)"
docker build -q -f harness/Dockerfile.wm -t tbe-dbg-wm harness/

echo "==> tbe-fb       (+ goal logging, world trace, 4x regression)"
docker build -q -f harness/Dockerfile.feedback -t tbe-fb .

echo
echo "built. try:"
echo "  python3 harness/tbe.py setup"
echo "  python3 harness/tbe.py solve finished/bouncing_balls.xml RightRamp@1.200,2.100"
