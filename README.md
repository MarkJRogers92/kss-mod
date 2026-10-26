# kss-mod — native runtime and modding layer for Kirby Super Star

A native (non-emulator-frontend) way to play and extend **Kirby Super Star (USA)**. It provides:
- an SA-1 SNES runtime with a 16:9 widescreen view;
- a sprite-replacement **mod engine** (`kss_mods.c`, mods in `mods/`);
- an SDL3 frontend (`frontend/`);
- a Python scenario runner for automated playtests (`scenario.py`, `scenarios/`);
- room tools: an inspector, a ROM room decoder and native checks (`tools/`, `tests/`).

The game side lives in the companion repo **kss-deuce**:
- the Seven Abilities ROM patch;
- the native-only expansion ROM (`Seven-Abilities.kx`) with seven custom helpers;
- `.room` room editing.

**No ROM is included.** You need your own unheadered *Kirby Super Star (USA)* ROM, SHA-256 `4e095fbbdec4a16b075d7140385ff68b259870ca9e3357f076dfff7f3d1c4a62`.

## Setup
```sh
sh tools/get_runtime.sh          # fetches the upstream runtime and applies third_party/snes_runtime.patch
clang -O2 -std=c11 -shared -fPIC -I. kss_mod.c kss_mods.c no_embedded_rom.c -lm -o libkssmod.dylib
cd frontend && make              # needs SDL3
./kss-native --rom "/path/Kirby Super Star (USA).sfc" \
  --ips ../../kss-deuce/build/Seven-Abilities.ips --expansion ../../kss-deuce/build/Seven-Abilities.kx --mods ../mods
```
Build the `.ips`/`.kx` with kss-deuce (`python3 -B -S source/build_combined.py "$KSS_BASE"`). Tests expect the two repos side by side as `kss-deuce/` and `native/kss-mod/`.

## About the runtime
- `snes_runtime.c` / `.h` are **not in this repository**. They come from [KirbySuperStarRecomp](https://github.com/josiahg2502-glitch/KirbySuperStarRecomp) by josiahg2502-glitch, which states no licence. Only our changes are here, as `third_party/snes_runtime.patch`; `tools/get_runtime.sh` fetches upstream commit `50d57b4` and applies it.
- Per its own header, that runtime is built on SNESRecomp (PolyForm Noncommercial 1.0.0), LakeSnes (MIT, elzo_d) and ares-derived code (ISC). Those terms apply to the fetched files.
- Everything else here is this project's own work.

## Snapshot
This repository is a clean snapshot, without history, of a private working repo. Game screenshots and captures were left out.
