# kss-native

A small, playable macOS desktop frontend (SDL3) for the local KSS SNES runtime.
It runs the unheadered USA **Kirby Super Star** ROM and, optionally, an IPS fan
hack (tested with `Seven-Abilities.ips`) applied **in memory only**.

The player's ROM is verified against a fixed SHA-256 before the runtime sees it.
No ROM or patched ROM is ever written to disk.

## Requirements

- macOS (Apple clang 17 is what this was built with).
- SDL3 3.4.x from Homebrew: `brew install sdl3`.
  `pkg-config --cflags --libs sdl3` should work; the Makefile falls back to
  `/opt/homebrew/{include,lib}` if it does not.
- The runtime sources next to this directory: `../kss_mod.c`, `../kss_mods.c`,
  `../no_embedded_rom.c`, `../kss_api.h`. They are compiled from here and are
  never modified.
- The exact unheadered USA ROM, 4,194,304 bytes,
  SHA-256 `4e095fbbdec4a16b075d7140385ff68b259870ca9e3357f076dfff7f3d1c4a62`.

`kss_mod.c` is one translation unit that `#include`s `snes_runtime.c`; the
Makefile never compiles `snes_runtime.c` separately.

## Build

```sh
cd native/kss-mod/frontend
make              # -> ./kss-native
make test         # IPS/SHA-256 unit tests + headless stock/patched/bad-ROM checks
make clean
```

`make` uses `clang`, `-O2 -std=c11 -Wall -Wextra`. The third-party runtime is
compiled with warnings suppressed so the frontend's own warnings stay visible.

Test assets default to the paths on this machine; override them if needed:

```sh
make test \
  ROM="/path/to/Kirby Super Star (USA).sfc" \
  IPS="/path/to/Seven-Abilities.ips"
```

## Run

```sh
# stock
./kss-native --rom "/path/to/Kirby Super Star (USA).sfc"

# patched, with mods, larger window
./kss-native --rom "/path/to/Kirby Super Star (USA).sfc" \
             --ips "/path/to/Seven-Abilities.ips" \
             --mods ./mods --scale 4

# 16:9 instead of the default 256x224 (side columns show tiles the game never loaded)
./kss-native --rom "/path/to/Kirby Super Star (USA).sfc" --widescreen

# fullscreen
./kss-native --rom "/path/to/Kirby Super Star (USA).sfc" --fullscreen

# windowed smoke test (no interaction)
./kss-native --rom "/path/to/Kirby Super Star (USA).sfc" \
             --exit-after-frames 180
```

Full CLI:

```
kss-native --rom ORIGINAL.sfc [--ips PATCH.ips] [--mods DIR] [--saves DIR]
           [--scale N] [--widescreen | --no-widescreen] [--fullscreen]
           [--headless-frames N [--press-start-every K] [--dump out.ppm] [--audio-stats]]
           [--exit-after-frames N] [--load-state STATE]
```

`--load-state` starts from a runtime save state instead of power-on, e.g. a
test fixture from `../fixtures/`. Fixtures are bound to the exact patched
ROM and emulator core (`../fixtures/manifest.json`); the frontend does not
re-check that binding, so use matching ROM/IPS only. To jump straight to the
Blaster helper with Blip:

```
./kss-native --rom 'Kirby Super Star (USA).sfc' \
             --ips /Users/markrogers/kss-work/kss-helper/build/Seven-Abilities.ips \
             --mods ../mods --load-state ../fixtures/blaster.state
```

Defaults: scale 3, 4:3 (256x224; the original SNES view, no edge artifacts), saves in
`~/Library/Application Support/KSSNative/`, mods from `mods/` next to the
executable if that directory exists (otherwise no mods).

## Controls

| Action | Player 1 | Player 2 |
| --- | --- | --- |
| D-pad | Arrow keys | I / J / K / L |
| B | Z | N |
| A | X | M |
| Y | A | H |
| X | S | U |
| L | Q | 7 |
| R | E | 9 |
| Start | Enter | 0 |
| Select | Right Shift | 8 |

System keys:

| Key | Action |
| --- | --- |
| Esc | quit (SRAM is saved first) |
| F11 | fullscreen toggle |
| W | widescreen toggle (352x224 <-> 256x224) |
| P | pause / resume |
| F1 | save state to the slot file |
| F2 | load state from the slot file |
| Tab (held) | fast-forward up to 4 frames per present, audio muted |

Gamepads are hot-pluggable. The first connected gamepad is player 1 and the
second is player 2. SNES layout by physical position: south=B, east=A, west=Y,
north=X, left/right shoulders=L/R, back=Select, start=Start, D-pad plus the left
stick (deadzone 0.5). Keyboard and gamepad bits for the same player are ORed.

## Files

Save directory (created on startup):

```
~/Library/Application Support/KSSNative/
```

The base name depends on the patch:

| Mode | SRAM | State slot |
| --- | --- | --- |
| stock | `kss.srm` | `kss.state` |
| `--ips Seven-Abilities.ips` | `kss-Seven-Abilities.srm` | `kss-Seven-Abilities.state` |

SRAM is loaded at startup if present, saved on quit, and saved every 30 seconds
when its bytes changed. Saves go to a `.tmp` file and are renamed atomically
over the real file. F1/F2 use the single state slot shown above and report
success or failure on stderr.

The ROM is never copied to the save directory. IPS records (normal and RLE) are
applied to a private in-memory copy; the original file on disk is untouched.

## Headless mode (CI)

`--headless-frames` does not initialize SDL video or audio. It runs the
requested number of frames and prints one JSON line to stdout:

```sh
./kss-native --rom "$ROM" --headless-frames 1300 --press-start-every 118 \
             --dump test-stock.ppm --audio-stats
```

```json
{"frames":1300,"fb":[352,224],"nonblack_pixels":75187,"audio_samples":1911000,"audio_nonzero":1299698,"sram_bytes":65536}
```

- `--press-start-every K`: hold Start for 6 frames out of every K frames
  (K >= 1; with K < 6, Start is held continuously).
- `--dump PATH`: write the final frame as binary PPM (P6).
- `--audio-stats`: extra human-readable audio/video numbers on stderr.
- `audio_samples` counts interleaved int16 samples (stereo pairs x 2), matching
  the `kss_audio()` return value.
- Runtime diagnostics are redirected to stderr so stdout stays valid JSON.
- SRAM is saved at the end of a headless run so `sram_bytes` reports the actual
  file size (64 KiB for this cartridge).

`make test` first runs unit tests for the IPS parser (standard and RLE records,
truncation, out-of-bounds, bad magic) and SHA-256 known vectors. It then asserts,
for both stock and patched ROMs:

- framebuffer is `[352,224]`,
- more than 20,000 non-black pixels in the final frame,
- more than 1,000 non-zero audio samples,
- passing the IPS file as `--rom` is rejected with a non-zero exit status.

## Limits

- The ROM hash is fixed to the USA revision above; other regions, headered
  dumps, and other revisions are refused. No ROM is embedded in the binary.
- IPS support is standard records plus RLE plus `EOF`. It does not implement
  the (rare) IPS "truncate" extension. A bad record aborts startup; the partial
  in-memory copy is discarded.
- Widescreen is 256 or 352 pixels wide by 224 high; there is no arbitrary
  aspect or filter selection. Presentation is nearest-neighbor with integer
  scaling when possible and fractional aspect-fit only when the window is
  smaller than the framebuffer.
- Fast-forward is capped at 4 emulated frames per present (about 4x).
- One state slot per ROM/patch; there is no slot browser or auto-save state.
- SRAM is written every 30 s only when it changed, plus on a clean exit.
  Killing the process (SIGKILL) loses up to 30 s of SRAM.
- Audio is 44.1 kHz stereo S16. If no audio device is available the game still
  runs silently; audio queueing is capped at roughly 4 frames to avoid drift.
- Mods use the runtime's `kss_mods_init()`. Put a `mods/` directory next to
  the executable or pass `--mods DIR`; the directory format is defined by the
  runtime's `kss_mods.c`. No mod files are bundled with this frontend.
- macOS-only path handling (`_NSGetExecutablePath`, `~/Library/Application
  Support`); not intended for Windows/Linux as-is.
