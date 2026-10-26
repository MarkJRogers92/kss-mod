"""Render a fixture with a given mods directory to PNG (system python3).

Usage: /usr/bin/python3 tools/preview.py FIXTURE|STATE MODS_DIR OUT.png [--frames N] [--p1 HEX] [--p2 HEX] [--scale S]
MODS_DIR must contain mods.list. Use MODS_DIR=none for the unmodified game.
Prints the number of pixels that differ from the unmodified game.
"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE / 'tools')]
import fixtures as F
from bg_dump import png_rgb

def frame(fixture, mods_dir, frames, p1, p2):
    F.load(fixture, Path('/Users/markrogers/kss-work/kss-helper/build/Kirby - Seven Abilities.sfc'),
           mods=mods_dir != 'none', mods_dir=None if mods_dir == 'none' else mods_dir)
    F.run(p1, p2, frames)
    w, h = F.lib.kss_fb_w(), F.lib.kss_fb_h(); fb = F.lib.kss_fb()
    return w, h, [fb[i] & 0xFFFFFF for i in range(w * h)]

def main():
    a = sys.argv[1:]
    fixture, mods_dir, out = a[0], a[1], Path(a[2])
    opt = lambda k, d: type(d)(int(a[a.index(k) + 1], 0)) if k in a else d
    frames, p1, p2, scale = opt('--frames', 4), opt('--p1', 0), opt('--p2', 0), opt('--scale', 1)
    w, h, px = frame(fixture, mods_dir, frames, p1, p2)
    _, _, base = frame(fixture, 'none', frames, p1, p2)
    diff = sum(1 for i in range(w * h) if px[i] != base[i])
    W, H = w * scale, h * scale; rgb = bytearray(W * H * 3)
    for y in range(H):
        for x in range(W):
            v = px[(y // scale) * w + x // scale]; o = (y * W + x) * 3
            rgb[o:o + 3] = bytes(((v >> 16) & 255, (v >> 8) & 255, v & 255))
    png_rgb(out, W, H, rgb)
    print(f'{out}: {w}x{h} (x{scale}), {diff} pixels differ from the unmodified game')

if __name__ == '__main__':
    main()
