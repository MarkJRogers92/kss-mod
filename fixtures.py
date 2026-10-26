"""Hash-bound save-state fixtures for the native runtime (system python3).

`fixtures.py build ROM` boots once with real inputs and saves checkpoints:
  gameplay    - Green Greens, normal Kirby
  beam        - Kirby holds Beam (inhaled Waddle Doo)
  blaster     - Blaster helper just created (H_TAG=1), P2 joined
  magnet      - native helper created from Magnet (H_TAG=0)
  prehurt     - Blaster helper about 30 frames before a natural enemy hit
Each state is bound to the ROM SHA-256 and the emulator core source (snes_runtime.c) SHA-256 in
fixtures/manifest.json; `load(name)` refuses stale fixtures.
"""
import ctypes, hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / 'fixtures'
LIB = HERE / 'libkssmod.dylib'
lib = ctypes.CDLL(str(LIB))
lib.kss_fb.restype = ctypes.POINTER(ctypes.c_uint32)
lib.kss_read_bwram16.restype = ctypes.c_uint16
lib.kss_read_bwram16.argtypes = [ctypes.c_uint32]
lib.kss_step.argtypes = [ctypes.c_uint16, ctypes.c_uint16]
lib.kss_oam.restype = ctypes.POINTER(ctypes.c_uint16)
K = {'B':0x8000,'Y':0x4000,'SELECT':0x2000,'START':0x1000,'UP':0x0800,'DOWN':0x0400,'LEFT':0x0200,'RIGHT':0x0100,'A':0x0080,'L':0x0020}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def keys(*n): return sum(K[x] for x in n)
def bw(o): return lib.kss_read_bwram16(o)
def run(p1=0, p2=0, n=1):
    for _ in range(n): lib.kss_step(p1, p2)
def dump(path):
    w, h = lib.kss_fb_w(), lib.kss_fb_h(); fb = lib.kss_fb(); d = bytearray()
    for i in range(w * h):
        v = fb[i]; d += bytes(((v >> 16) & 255, (v >> 8) & 255, v & 255))
    Path(path).write_bytes(b'P6\n%d %d\n255\n' % (w, h) + bytes(d))

def open_rom(rom, mods=True, mods_dir=None):
    lib.kss_close()
    assert lib.kss_open(str(rom).encode()), 'ROM load failed'
    lib.kss_mods_init(str(mods_dir or HERE / 'mods').encode() if mods else b'/nonexistent')

def save(name, meta):
    FIX.mkdir(exist_ok=True)
    assert lib.kss_save_state(str(FIX / f'{name}.state').encode()), name
    meta[name] = {'frame': lib.kss_frame(), 'state_sha256': sha(FIX / f'{name}.state'),
                  'helper_tag': bw(0x2C02), 'kirby_ability': bw(0x149F), 'kirby_tag': bw(0x2802)}

def load(name, rom, mods=True, mods_dir=None):
    """Load a named fixture, or any runtime .state file (e.g. one saved with F1
    in the frontend). Arbitrary files are not hash-bound: they must come from
    the same ROM/patch and emulator build."""
    if str(name).endswith('.state'):
        open_rom(rom, mods, mods_dir)
        assert lib.kss_load_state(str(Path(name).expanduser()).encode()), name
        return
    m = json.loads((FIX / 'manifest.json').read_text())
    assert m['rom_sha256'] == sha(rom), 'fixtures were built from a different ROM; rebuild'
    assert m['core_sha256'] == sha(HERE / 'snes_runtime.c'), 'emulator core changed; rebuild fixtures'
    open_rom(rom, mods, mods_dir)
    assert lib.kss_load_state(str(FIX / f'{name}.state').encode()), name

def build(rom):
    meta = {}
    open_rom(rom)
    for _ in range(11): run(n=110); run(keys('START'), n=8)
    run(n=120); save('gameplay', meta)
    for _ in range(6):
        run(keys('RIGHT'), n=30); run(keys('Y'), n=90); run(n=20); run(keys('DOWN'), n=2); run(n=120)
        if bw(0x149F) == 2: break
    assert bw(0x149F) == 2; run(keys('LEFT'), n=30); run(n=10); save('beam', meta)
    # Blaster helper, with P2 joined.
    run(keys('SELECT', 'RIGHT'), n=2); run(n=24); assert bw(0x2802) == 1
    run(keys('A')); run(n=120); assert bw(0x2C02) == 1
    run(n=20); run(p2=keys('Y'), n=3); run(n=40); save('blaster', meta)
    # Find a natural enemy hit: Kirby flies right (B pulses), AI helper follows.
    lib.kss_save_state(str(FIX / '_scan.state').encode())
    hit = None; hp = bw(0x137E); trail = []
    for f in range(3000):
        run(keys('RIGHT', *(['B'] if (f % 10) < 4 else [])), 0, 1)
        trail.append(f)
        if bw(0x137E) < hp: hit = f; break
        hp = bw(0x137E)
    if hit is not None and hit > 40:
        lib.kss_load_state(str(FIX / '_scan.state').encode())
        for f in range(hit - 30): run(keys('RIGHT', *(['B'] if (f % 10) < 4 else [])), 0, 1)
        meta['prehurt_input'] = {'p1': 'RIGHT + B for 4 of every 10 frames', 'start_phase': hit - 30, 'hit_after': 30}
        save('prehurt', meta)
    (FIX / '_scan.state').unlink()
    # Native helper made from Magnet.
    lib.kss_load_state(str(FIX / 'beam.state').encode())
    for _ in range(2): run(keys('SELECT', 'RIGHT'), n=2); run(n=24)
    assert bw(0x2802) == 2; run(keys('A')); run(n=120); assert bw(0x2C02) == 0 and bw(0x240) in (2, 3)
    save('magnet', meta)
    out = {'rom_sha256': sha(rom), 'core_sha256': sha(HERE / 'snes_runtime.c'), 'mods': 'mods/', 'states': meta}
    (FIX / 'manifest.json').write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps({k: v for k, v in meta.items()}, indent=1))

if __name__ == '__main__':
    if sys.argv[1] == 'build': build(Path(sys.argv[2]))
