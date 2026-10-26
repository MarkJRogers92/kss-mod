"""Import repainted background bands into a tile-replacement mod (needs Pillow).

Usage: python3 tools/bg_import.py DUMPDIR EDITED.png [EDITED2.png ...] --out MODDIR
          [--name NAME] [--when "0x2C02 == 1" ...] [--strict]
Each EDITED.png must be a repaint of one band file from DUMPDIR (same name, or
"<band>.edit.png"), same size, indexed with the band's 256-colour palette.
  * Changed pixels become new 8x8 tile data, keyed by the hash of the ORIGINAL
    tile in VRAM (content match: works wherever the game uploads that tile).
    A pixel must use a colour of its tile's own palette (or index 0 = clear).
  * Changed palette entries become `cgram_lines` for that band's scanlines.
Writes MODDIR/tiles.ktp and MODDIR/mod.txt and prints a report. Exits non-zero
on palette violations, or on conflicting edits of one tile with --strict.
"""
import json, struct, sys
from pathlib import Path
from PIL import Image

def fnv(words):
    h = 1469598103934665603
    for w in words:
        for b in (w & 0xff, w >> 8):
            h ^= b; h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h

def decode(words, bpp):
    px = [[0] * 8 for _ in range(8)]
    for r in range(8):
        w0 = words[r]; w1 = words[8 + r] if bpp == 4 else 0
        for c in range(8):
            v = (w0 >> (7 - c)) & 1 | ((w0 >> (15 - c)) & 1) << 1
            if bpp == 4: v |= ((w1 >> (7 - c)) & 1) << 2 | ((w1 >> (15 - c)) & 1) << 3
            px[r][c] = v
    return px

def encode(px, bpp):
    words = [0] * (16 if bpp == 4 else 8)
    for r in range(8):
        for c in range(8):
            v = px[r][c]; bit = 7 - c
            words[r] |= (v & 1) << bit | ((v >> 1) & 1) << (bit + 8)
            if bpp == 4: words[8 + r] |= ((v >> 2) & 1) << bit | ((v >> 3) & 1) << (bit + 8)
    return words

def to555(rgb):
    r, g, b = rgb
    return (r >> 3) | (g >> 3) << 5 | (b >> 3) << 10

def main():
    a = sys.argv[1:]
    dump = Path(a[0]); edits = []; out = None; name = 'bg-tiles'; whens = []; strict = False; i = 1
    while i < len(a):
        if a[i] == '--out': out = Path(a[i + 1]); i += 2
        elif a[i] == '--name': name = a[i + 1]; i += 2
        elif a[i] == '--when': whens.append(a[i + 1]); i += 2
        elif a[i] == '--strict': strict = True; i += 1
        else: edits.append(Path(a[i])); i += 1
    assert out and edits, __doc__
    meta = json.loads((dump / 'meta.json').read_text()); W, H = meta['fb']
    vram = struct.unpack('<32768H', (dump / 'vram.bin').read_bytes())
    tiles = {}; sets = {}; conflicts = []; errors = []; cg_lines = []; report = []
    for ed in edits:
        base = ed.name.replace('.edit.png', '.png')
        layer, band = None, None
        for ln, L in meta['layers'].items():
            for b in L['bands']:
                if b['file'] == base: layer, band = ln, b
        if not band: sys.exit(f'{ed}: no matching band in {dump}/meta.json')
        orig = Image.open(dump / band['file']); new = Image.open(ed)
        if new.mode != 'P': sys.exit(f'{ed}: must stay an indexed (P) image with the band palette')
        if new.size != orig.size: sys.exit(f'{ed}: size {new.size} != {orig.size}')
        po, pn = orig.getpalette()[:768], (new.getpalette() + [0] * 768)[:768]
        changed_pal = [k for k in range(256) if to555(tuple(pn[k * 3:k * 3 + 3])) != band['cgram'][k] & 0x7FFF]
        y0, y1 = band['rows']
        if changed_pal:                      # one span per band; gaps keep the band's original colours
            lo, hi = changed_pal[0], changed_pal[-1]
            cg_lines.append((y0 + 1, y1 + 1, lo, [to555(tuple(pn[j * 3:j * 3 + 3])) if j in changed_pal else band['cgram'][j] & 0x7FFF for j in range(lo, hi + 1)]))
        mp = (dump / f'{layer}.map').read_bytes()
        o, n = orig.load(), new.load(); edited_px = 0
        for y in range(y0, y1 + 1):
            for x in range(W):
                if o[x, y] == n[x, y]: continue
                ca, rc, pal, bpp, valid = struct.unpack_from('<HBBBB', mp, (y * W + x) * 6)
                if not valid: errors.append(f'{ed.name} ({x},{y}): no tile here'); continue
                e = n[x, y]; span = 16 if bpp == 4 else 4
                if e % span == 0: v = 0
                elif e // span == pal: v = e % span
                else: errors.append(f'{ed.name} ({x},{y}): colour {e} is palette {e // span}, tile uses palette {pal}'); continue
                key = (ca, bpp)
                if key not in tiles: tiles[key] = decode(vram[ca:ca + (16 if bpp == 4 else 8)], bpp)
                row, col = rc & 15, rc >> 4
                prev = sets.get((ca, bpp, row, col))
                if prev is not None and prev != v: conflicts.append(f'tile {ca:04X} px ({col},{row}) set to {prev} and {v} (at {x},{y})')
                sets[(ca, bpp, row, col)] = v; tiles[key][row][col] = v; edited_px += 1
        report.append({'edit': ed.name, 'band': band['file'], 'layer': layer, 'pixels_changed': edited_px, 'palette_entries_changed': len(changed_pal)})
    if errors:
        print('\n'.join(errors[:40])); sys.exit(f'{len(errors)} palette error(s); nothing written')
    if conflicts:
        print('\n'.join(conflicts[:20]))
        if strict: sys.exit(f'{len(conflicts)} conflicting tile edit(s)')
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for (ca, bpp), px in sorted(tiles.items()):
        nw = 16 if bpp == 4 else 8; old = list(vram[ca:ca + nw]); new = encode(px, bpp)
        if new != old: entries.append((bpp, fnv(old), new, ca))
    blob = bytearray(b'KTP1' + struct.pack('<I', len(entries)))
    for bpp, h, words, _ in entries: blob += struct.pack('<B3xQ', bpp, h) + struct.pack('<%dH' % len(words), *words)
    (out / 'tiles.ktp').write_bytes(bytes(blob))
    lines = [f'# Background tile replacement generated by tools/bg_import.py from {dump.name}', f'rule tiles {name}']
    lines += [f'when {w}' for w in whens] + ['tilepack tiles.ktp']
    seen_runs = []
    for run in cg_lines:
        if run not in seen_runs: seen_runs.append(run)
    if len(seen_runs) > 32: sys.exit(f'{len(seen_runs)} palette spans exceed the loader limit of 32 per rule')
    lines += [f'cgram_lines {a} {b} 0x{s:02X} ' + ' '.join(f'{w:04X}' for w in ws) for a, b, s, ws in seen_runs]
    (out / 'mod.txt').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'tiles_replaced': len(entries), 'cgram_runs': len(seen_runs), 'conflicts': len(conflicts), 'edits': report}, indent=1))

if __name__ == '__main__':
    main()
