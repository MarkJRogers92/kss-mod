"""Dump the visible background layers of one frame for repainting (system python3).

Usage: /usr/bin/python3 tools/bg_dump.py FIXTURE|STATE OUTDIR [--frames N] [--rom ROM] [--with-mods]
(default: mods off, so the dump shows the original game graphics)
Loads a hash-bound fixture (see fixtures.py), runs N frames (default 2) with the
per-scanline BG register capture enabled, then writes:
  screen.png        the composited frame (reference only)
  bgN-yA-yB.png     each layer alone, split into scanline bands that share one
                    CGRAM state (the HUD changes palettes mid-frame); indexed,
                    palette = that band's CGRAM, each palette's colour 0 transparent.
                    Pixel value = CGRAM index. Rows outside the band are blank.
  bgN.map           per pixel '<HBBBB': tile word address, row | col<<4, palette, bpp, valid
  vram.bin cgram.bin meta.json   originals for the importer
Repaint bgN.png keeping each 8x8 tile inside its own palette (tools/bg_import.py
checks this), then import it into a tile pack.
"""
import ctypes, json, struct, sys, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import fixtures as F

def png_indexed(path, w, h, pixels, rgb_palette, transparent):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = bytearray()
    for y in range(h):
        raw.append(0); raw += bytes(pixels[y * w:(y + 1) * w])
    plte = b''.join(bytes(c) for c in rgb_palette)
    trns = bytes(0 if i in transparent else 255 for i in range(256))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 3, 0, 0, 0)) +
                           chunk(b'PLTE', plte) + chunk(b'tRNS', trns) + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))

def png_rgb(path, w, h, rgb):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = bytearray()
    for y in range(h):
        raw.append(0); raw += rgb[y * w * 3:(y + 1) * w * 3]
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                           chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))

def layer_bpp(mode, layer):
    return {0: (2, 2, 2, 2), 1: (4, 4, 2, 0)}.get(mode, (0, 0, 0, 0))[layer]

def main():
    args = sys.argv[1:]
    fixture, out = args[0], Path(args[1]); out.mkdir(parents=True, exist_ok=True)
    frames = int(args[args.index('--frames') + 1]) if '--frames' in args else 2
    rom = Path(args[args.index('--rom') + 1]) if '--rom' in args else Path('/Users/markrogers/kss-work/kss-helper/build/Kirby - Seven Abilities.sfc')
    F.load(fixture, rom, mods='--with-mods' in args)
    lib = F.lib
    lib.kss_capture_regs.restype = ctypes.c_void_p
    lib.kss_vram.restype = ctypes.POINTER(ctypes.c_uint16)
    lib.kss_cgram.restype = ctypes.POINTER(ctypes.c_uint16)
    lib.kss_capture_cgram.restype = ctypes.POINTER(ctypes.c_uint16)
    F.run(n=max(0, frames - 1)); lib.kss_capture_enable(1); F.run(n=1); lib.kss_capture_enable(0)
    stride = lib.kss_capture_stride(); base = lib.kss_capture_regs()
    regs = []
    for y in range(256):
        b = ctypes.string_at(base + y * stride, stride)
        v = struct.unpack('<%dH' % (stride // 2), b)
        regs.append({'mode': v[0], 'enabled': v[1], 'tilemap': v[2:6], 'tileadr': v[6:10], 'xsc': v[10:14], 'big': v[14:18], 'hs': v[18:22], 'vs': v[22:26]})
    vram = [lib.kss_vram()[i] for i in range(0x8000)]
    lcg = lib.kss_capture_cgram(); line_cg = [tuple(lcg[y * 256 + i] for i in range(256)) for y in range(256)]
    cg = [lib.kss_cgram()[i] for i in range(256)]
    def rgb(c): return ((c & 31) << 3 | (c & 31) >> 2, ((c >> 5) & 31) << 3 | ((c >> 5) & 31) >> 2, ((c >> 10) & 31) << 3 | ((c >> 10) & 31) >> 2)
    w, h = lib.kss_fb_w(), lib.kss_fb_h(); extra = (w - 256) // 2
    fb = lib.kss_fb(); scr = bytearray()
    for i in range(w * h):
        v = fb[i]; scr += bytes(((v >> 16) & 255, (v >> 8) & 255, v & 255))
    png_rgb(out / 'screen.png', w, h, scr)
    (out / 'vram.bin').write_bytes(struct.pack('<32768H', *vram))
    (out / 'cgram.bin').write_bytes(struct.pack('<256H', *cg))
    # Screen row r is rendered with the registers captured for line r+1 (line 0 is pre-render).
    layers = {}
    for layer in range(3):
        px = bytearray(w * h); mp = bytearray(w * h * 6); used = 0
        for r in range(h):
            L = regs[r + 1]; bpp = layer_bpp(L['mode'], layer)
            if not bpp or not (L['enabled'] & (1 << layer)): continue
            big = L['big'][layer]; ts = 16 if big else 8
            yy = (r + L['vs'][layer]) & 0x3ff
            for sx in range(w):
                xx = (sx - extra + L['hs'][layer]) & 0x3ff
                adr = L['tilemap'][layer] + (((yy // ts) & 31) << 5 | ((xx // ts) & 31))
                if (xx // ts) & 32 and L['xsc'][layer] & 1: adr += 0x400
                if (yy // ts) & 32 and L['xsc'][layer] & 2: adr += 0x800 if L['xsc'][layer] & 1 else 0x400
                e = vram[adr & 0x7fff]
                tile, pal, hf, vf = e & 0x3ff, (e >> 10) & 7, e & 0x4000, e & 0x8000
                tx, ty = xx % ts, yy % ts
                if hf: tx = ts - 1 - tx
                if vf: ty = ts - 1 - ty
                if big: tile += (tx >> 3) + ((ty >> 3) << 4)
                col, row = tx & 7, ty & 7
                ca = (L['tileadr'][layer] + (tile & 0x3ff) * bpp * 4) & 0x7fff
                w0 = vram[(ca + row) & 0x7fff]
                v = ((w0 >> (7 - col)) & 1) | (((w0 >> (15 - col)) & 1) << 1)
                if bpp == 4:
                    w1 = vram[(ca + 8 + row) & 0x7fff]
                    v |= (((w1 >> (7 - col)) & 1) << 2) | (((w1 >> (15 - col)) & 1) << 3)
                    idx = pal * 16 + v
                else:
                    idx = (layer * 32 if L['mode'] == 0 else 0) + pal * 4 + v
                i = r * w + sx; px[i] = idx; used += v != 0
                mp[i * 6:i * 6 + 6] = struct.pack('<HBBBB', ca, row | (col << 4), pal, bpp, 1)
        if not used: continue
        name = f'bg{layer + 1}'
        bpp_any = next((layer_bpp(regs[r + 1]['mode'], layer) for r in range(h) if layer_bpp(regs[r + 1]['mode'], layer)), 4)
        transparent = {i for i in range(256) if i % (16 if bpp_any == 4 else 4) == 0}
        (out / f'{name}.map').write_bytes(bytes(mp))
        bands = []; start = 0
        for r in range(1, h + 1):
            if r == h or line_cg[r + 1] != line_cg[start + 1]:
                rows = range(start, r)
                if any(px[y * w + x] % (16 if bpp_any == 4 else 4) for y in rows for x in range(w)):
                    band = bytearray(w * h)
                    for y in rows: band[y * w:(y + 1) * w] = px[y * w:(y + 1) * w]
                    fn = f'{name}-y{start:03d}-y{r - 1:03d}.png'
                    png_indexed(out / fn, w, h, band, [rgb(c) for c in line_cg[start + 1]], transparent)
                    bands.append({'file': fn, 'rows': [start, r - 1], 'cgram': list(line_cg[start + 1])})
                start = r
        layers[name] = {'opaque_pixels': used, 'bpp': bpp_any, 'bands': bands}
    meta = {'fixture': fixture, 'frames': frames, 'fb': [w, h], 'extra': extra, 'layers': layers,
            'modes': sorted({regs[r + 1]['mode'] for r in range(h)}), 'rom_sha256': F.sha(rom)}
    (out / 'meta.json').write_text(json.dumps(meta, indent=2) + '\n')
    print(json.dumps({k: (v if k != 'layers' else {n: [b['file'] for b in l['bands']] for n, l in v.items()}) for k, v in meta.items()}))

if __name__ == '__main__':
    main()
