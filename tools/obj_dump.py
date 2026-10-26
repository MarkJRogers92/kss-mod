"""List the sprites (OAM objects) on screen, to find what a sprite mod must match.

Usage: /usr/bin/python3 tools/obj_dump.py FIXTURE|STATE OUTDIR [--frames N]
Writes objects.json (index, x, y, size, first tile, OBJ palette, priority, flips)
grouped by palette, and objects.png: the frame with a coloured box per object
(box colour = OBJ palette: 0 red, 1 orange, 2 yellow, 3 green, 4 cyan, 5 blue,
6 violet, 7 white). Actor rules match `palette P tiles LO HI` (first tile of each
object); see mods/README.md. Known: Kirby body = palette 0 tiles 00-1F,
helper body = palette 2 tiles 20-3F, helper FX = palette 1 tiles 48-4F.
"""
import ctypes, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE / 'tools')]
import fixtures as F
from bg_dump import png_rgb
COL = [(255,40,40),(255,150,0),(255,230,0),(40,220,40),(0,220,220),(60,90,255),(190,80,255),(255,255,255)]
def main():
    a = sys.argv[1:]; src, out = a[0], Path(a[1]); out.mkdir(parents=True, exist_ok=True)
    frames = int(a[a.index('--frames') + 1]) if '--frames' in a else 2
    F.load(src, Path('/Users/markrogers/kss-work/kss-helper/build/Kirby - Seven Abilities.sfc'), mods=False)
    F.run(n=frames)
    oam = F.lib.kss_oam(); F.lib.kss_high_oam.restype = ctypes.POINTER(ctypes.c_uint8); hi = F.lib.kss_high_oam()
    w, h = F.lib.kss_fb_w(), F.lib.kss_fb_h(); extra = (w - 256) // 2; fb = F.lib.kss_fb()
    rgb = bytearray()
    for i in range(w * h):
        v = fb[i]; rgb += bytes(((v >> 16) & 255, (v >> 8) & 255, v & 255))
    objs = []
    for i in range(128):
        a0, a1 = oam[i * 2], oam[i * 2 + 1]; y = a0 >> 8
        if y >= 224 and y < 240: continue
        x = (a0 & 255) | ((hi[i >> 2] >> ((i & 3) * 2)) & 1) << 8
        if x >= 256: x -= 512
        big = (hi[i >> 2] >> ((i & 3) * 2 + 1)) & 1; size = 16 if big else 8   # KSS uses OBJSEL 8/16
        o = {'index': i, 'x': x, 'y': y, 'size': size, 'tile': f'0x{a1 & 0x1FF:03X}', 'palette': (a1 >> 9) & 7,
             'priority': (a1 >> 12) & 3, 'hflip': bool(a1 & 0x4000), 'vflip': bool(a1 & 0x8000)}
        objs.append(o)
        c = COL[o['palette']]
        for dx in range(size):
            for dy in (0, size - 1):
                X, Y = x + extra + dx, y + dy
                if 0 <= X < w and 0 <= Y < h: rgb[(Y * w + X) * 3:(Y * w + X) * 3 + 3] = bytes(c)
        for dy in range(size):
            for dx in (0, size - 1):
                X, Y = x + extra + dx, y + dy
                if 0 <= X < w and 0 <= Y < h: rgb[(Y * w + X) * 3:(Y * w + X) * 3 + 3] = bytes(c)
    png_rgb(out / 'objects.png', w, h, rgb)
    by_pal = {}
    for o in objs: by_pal.setdefault(o['palette'], []).append(o)
    (out / 'objects.json').write_text(json.dumps({'fb': [w, h], 'extra': extra, 'by_palette': by_pal}, indent=1) + '\n')
    print(json.dumps({p: sorted({o['tile'] for o in v}) for p, v in by_pal.items()}))
if __name__ == '__main__':
    main()
