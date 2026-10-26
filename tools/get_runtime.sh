#!/bin/sh
# Fetch the emulator runtime this project forks and apply our changes.
# snes_runtime.c/.h come from KirbySuperStarRecomp (josiahg2502-glitch), which
# is not ours to redistribute, so only our patch (third_party/snes_runtime.patch)
# is in this repository. Run from the repository root:  sh tools/get_runtime.sh
set -e
UPSTREAM=https://github.com/josiahg2502-glitch/KirbySuperStarRecomp.git
COMMIT=50d57b4
TMP=$(mktemp -d)
git clone --quiet "$UPSTREAM" "$TMP/upstream"
git -C "$TMP/upstream" checkout --quiet "$COMMIT"
cp "$TMP/upstream/src/snes_runtime.c" "$TMP/upstream/src/snes_runtime.h" .
patch -p1 --quiet < third_party/snes_runtime.patch
rm -rf "$TMP"
echo "snes_runtime.c/.h ready (upstream $COMMIT + third_party/snes_runtime.patch)"
