"""Background tile-replacement tests from hash-bound fixtures (system python3).

Uses tests/selftest-mods/selftest: a tile pack produced by tools/bg_import.py from
a synthetic repaint of the helper card (12 tiles + one cgram_lines run), gated
on the helper being Blaster. Checks: game state unchanged; only the expected
HUD rows change; the gated rule stays off for a native helper; VRAM itself is
never modified; frame-time cost of the per-frame VRAM scan.
"""
import ctypes, json, sys, time
from pathlib import Path
import fixtures as F
ROM = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/Users/markrogers/kss-work/kss-helper/build/Kirby - Seven Abilities.sfc')
MODS = F.HERE / 'tests' / 'selftest-mods'
F.lib.kss_vram.restype = ctypes.POINTER(ctypes.c_uint16)
def snap():
    w, h = F.lib.kss_fb_w(), F.lib.kss_fb_h(); fb = F.lib.kss_fb()
    return w, [fb[i] & 0xFFFFFF for i in range(w * h)], bytes(ctypes.string_at(ctypes.cast(F.lib.kss_vram(), ctypes.c_void_p), 0x10000)), tuple(F.bw(a) for a in range(0, 0x2C10, 2))
def run(fix, mods, n=30):
    F.load(fix, ROM, mods=mods, mods_dir=MODS); out = []
    for _ in range(n): F.run(n=1); out.append(snap())
    return out
res = {}
for fix, expect in (('blaster', True), ('magnet', False)):
    on, off = run(fix, True), run(fix, False); rows = set(); changed = 0
    for (w, a, va, sa), (_, b, vb, sb) in zip(on, off):
        assert sa == sb, (fix, 'BW-RAM state diverged with background mod')
        assert va == vb, (fix, 'VRAM must never be modified by a mod')
        d = [i for i in range(len(a)) if a[i] != b[i]]
        if d: changed += 1; rows |= {i // w for i in d}
    if expect:
        assert changed == len(on), (fix, changed)
        assert rows and min(rows) >= 168 and max(rows) <= 223, (fix, 'change outside the HUD band', min(rows), max(rows))
    else:
        assert changed == 0, (fix, 'gated rule fired for a native helper', changed)
    res[fix] = {'frames': len(on), 'changed_frames': changed, 'rows': [min(rows), max(rows)] if rows else None}
# Scope: with the real mods (blip, blip-card, autumn-greens) loaded, boot from
# power-on through intro, title and menus: those checkpoints must be
# pixel-identical to the unmodified game; the Stage 1 intro card (drawn with the
# Green Greens tileset) and Green Greens gameplay must change.
def boot_frames(mods):
    F.open_rom(ROM, mods=mods); shots = []
    for k in range(11):
        F.run(n=110); w, px, _, _ = snap(); shots.append(px); F.run(F.keys('START'), n=8)
    F.run(n=120); w, px, _, _ = snap(); shots.append(px)
    return shots
on, off = boot_frames(True), boot_frames(False)
same = [a == b for a, b in zip(on, off)]
assert all(same[:10]), ('mod leaked outside Green Greens', same)
assert not same[10] and not same[11], ('autumn-greens missing on the Stage 1 card or in gameplay', same)
res['offstage_checkpoints_identical'] = sum(same[:10]); res['green_greens_screens_changed'] = 2
# Cost of the per-frame VRAM scan (tile rule active) vs no rules.
for label, mods in (('no_rules', False), ('tile_rule_active', True)):
    F.load('blaster', ROM, mods=mods, mods_dir=MODS); t = time.perf_counter(); F.run(n=600); dt = time.perf_counter() - t
    res[label + '_fps'] = round(600 / dt, 1)
print(json.dumps(res))
