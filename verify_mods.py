"""Native-runtime evidence for the data-driven Blip mod (system python3, no PIL).

Boots the hack ROM, gets Beam with real inputs, creates (a) a Blaster helper and
(b) for the negative case a Magnet-made native helper, then records which pose
animations / bolt replacements were active, and dumps PPM frames.
Usage: /usr/bin/python3 verify_mods.py ROM OUTDIR
"""
import ctypes, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
lib = ctypes.CDLL(str(HERE / 'libkssmod.dylib'))
lib.kss_fb.restype = ctypes.POINTER(ctypes.c_uint32)
lib.kss_read_bwram16.restype = ctypes.c_uint16
lib.kss_read_bwram16.argtypes = [ctypes.c_uint32]
lib.kss_step.argtypes = [ctypes.c_uint16, ctypes.c_uint16]
lib.kss_oam.restype = ctypes.POINTER(ctypes.c_uint16)
K = {'B':0x8000,'Y':0x4000,'SELECT':0x2000,'START':0x1000,'UP':0x0800,'DOWN':0x0400,'LEFT':0x0200,'RIGHT':0x0100,'A':0x0080,'L':0x0020}
def keys(*n): return sum(K[x] for x in n)
def bw(o): return lib.kss_read_bwram16(o)
def run(p1=0, p2=0, n=1):
    for _ in range(n): lib.kss_step(p1, p2)
def dump(path):
    w, h = lib.kss_fb_w(), lib.kss_fb_h(); fb = lib.kss_fb(); d = bytearray()
    for i in range(w * h):
        v = fb[i]; d += bytes(((v >> 16) & 255, (v >> 8) & 255, v & 255))
    Path(path).write_bytes(b'P6\n%d %d\n255\n' % (w, h) + bytes(d))
def helper_objs():
    oam = lib.kss_oam(); out = []
    for i in range(128):
        a, b = oam[i * 2], oam[i * 2 + 1]
        if (a >> 8) < 224 and ((b & 0xE00) >> 9) == 2 and 0x20 <= (b & 0x1FF) <= 0x3F: out.append(i)
    return out

def installed_rules():
    """Rule count of every mod in mods/mods.list, parsed the way kss_mods.c does."""
    total = 0
    for line in (HERE / 'mods' / 'mods.list').read_text().splitlines():
        name = line.split('#')[0].split()[0] if line.split('#')[0].split() else ''
        if not name: continue
        for row in (HERE / 'mods' / name / 'mod.txt').read_text().splitlines():
            tok = row.split('#')[0].split()
            if tok and tok[0] == 'rule': total += 1
    return total

def boot_to_helper(rom, rights):
    assert lib.kss_open(str(rom).encode())
    expected = installed_rules()
    loaded = lib.kss_mods_init(str(HERE / 'mods').encode())
    assert expected > 0 and loaded == expected, f'loaded {loaded} mod rules, mods.list declares {expected}'
    for _ in range(11): run(n=110); run(keys('START'), n=8)
    run(n=120)
    for _ in range(6):
        run(keys('RIGHT'), n=30); run(keys('Y'), n=90); run(n=20); run(keys('DOWN'), n=2); run(n=120)
        if bw(0x149F) == 2: break
    assert bw(0x149F) == 2, 'no Beam'
    for _ in range(rights): run(keys('SELECT', 'RIGHT'), n=2); run(n=24)
    assert bw(0x2802) == rights
    run(keys('LEFT'), n=30); run(n=10); run(keys('A'), n=1); run(n=120)
    assert bw(0x240) in (2, 3) and bw(0x14A1) == 2

def main():
    rom, out = Path(sys.argv[1]), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    report = {'rom': str(rom), 'installed_rules': installed_rules()}
    boot_to_helper(rom, 1)
    assert bw(0x2C02) == 1, 'helper is not Blaster'
    seen = {}
    def watch(label, p1=0, p2=0, n=1, shot=None):
        for i in range(n):
            run(p1, p2, 1); pose = bw(0x43A); seen.setdefault(hex(pose), label)
            if shot and i == n - 1: dump(out / f'{shot}.ppm')
    watch('idle', n=40, shot='a-idle')
    watch('join', p2=keys('Y'), n=3); watch('idle', n=40)
    watch('walk', p2=keys('LEFT'), n=14, shot='b-walk'); watch('walk', p2=keys('LEFT'), n=6)
    watch('idle', n=12)
    watch('fire', p2=keys('Y'), n=1); watch('fire', n=5, shot='c-fire'); watch('fire', n=30)
    watch('jump', p2=keys('B'), n=7, shot='d-jump'); watch('air', n=14, shot='e-fall'); watch('air', n=40)
    watch('guard', p2=keys('L'), n=10); watch('idle', n=20)
    watch('overlap', p1=keys('LEFT'), n=24, shot='f-overlap'); watch('idle', n=10)
    # Hurt: walk right with Kirby (AI helper follows) until the helper takes a hit.
    hp = bw(0x137E); hurt = None
    for f in range(2400):
        run(keys('RIGHT', *(['B'] if (f % 40) < 12 else [])), 0, 1)
        if bw(0x137E) < hp:
            hurt = f; run(n=3); dump(out / 'g-hurt.ppm'); seen.setdefault(hex(bw(0x43A)), 'hurt'); break
        hp = bw(0x137E)
    report['blaster'] = {'poses_seen': seen, 'hurt_frame': hurt, 'helper_tag': bw(0x2C02)}
    lib.kss_close()
    # Negative case: helper made from Magnet stays a native Waddle Doo (rule inactive).
    boot_to_helper(rom, 2)
    assert bw(0x2C02) == 0, 'Magnet helper must be native'
    run(n=20); dump(out / 'h-native-helper.ppm')
    report['native_helper'] = {'helper_tag': bw(0x2C02), 'native_objects_visible': len(helper_objs())}
    lib.kss_close()
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))

if __name__ == '__main__':
    main()
