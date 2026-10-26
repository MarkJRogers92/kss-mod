"""The real build carries room edits (build_combined.py --rooms), checked natively.

/usr/bin/python3 tests/room_build_check.py

Edit file (generated here from the build's own decode, kept in out-rooms/):
  room 1: two-tile solid pillars in 12 columns -> too big for its slot, so the
          build moves the record into the expansion at 71:0000
  room 3: one solid tile at column 26 row 5 -> fits, written in place
Checks: the edited build's ROM differs from the default build only in room
1's pointer, room 3's slot and the header checksum; its expansion starts with
the default image; the IPS reproduces the ROM; rooms decode to the edits and
every other room is unchanged. Natively: room 1 (door to room 2 and back) and
room 3 (Warp Star route) load live equal to the edits and the drop oracle
agrees in every column, with edited columns resting higher; room 2 unchanged.
"""
import ctypes, json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'tools'), str(HERE)]
import room_rom as R, room_inspector as I, scenario as S

GAME = (HERE / '../../kss-deuce').resolve(); BUILD = GAME / 'build'
OUT = HERE / 'out-rooms/g3-build'
BASE = Path('/Users/markrogers/Documents/Codex/2026-10-14/task-4/originals/Kirby Super Star (USA).sfc')
# column: floor row. Not 31-32 (type-7501 object, see room_relocate_check.py).
PILLARS = {4: 7, 5: 7, 6: 7, 8: 6, 9: 6, 10: 6, 14: 6, 15: 6, 17: 6, 18: 6, 25: 5, 28: 5}
R3 = (26, 6)
rom = (BUILD / 'Kirby - Seven Abilities.sfc').read_bytes(); kx = (BUILD / 'Seven-Abilities.kx').read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint green-pip-created is stale'
rooms = {}
for i in range(1024):
    try: rooms[i] = R.decode_room(rom, i)
    except Exception: pass

want = {1: [r[:] for r in rooms[1]['layout']], 3: [r[:] for r in rooms[3]['layout']]}
tiles = {1: [], 3: []}
for c, r in PILLARS.items():
    for k in (1, 2): want[1][r - k][c] = want[1][r][c]; tiles[1].append([c, r - k, f'{want[1][r][c]:04X}'])
c, r = R3; want[3][r - 1][c] = want[3][r][c]; tiles[3].append([c, r - 1, f'{want[3][r][c]:04X}'])
OUT.mkdir(parents=True, exist_ok=True)
spec = OUT / 'rooms.json'
spec.write_text(json.dumps({'rooms': [{'room': i, 'tiles': t} for i, t in tiles.items()]}, indent=1) + '\n')
run = subprocess.run([sys.executable, '-B', '-S', 'source/build_combined.py', str(BASE), '--output', str(OUT), '--rooms', str(spec)],
                     cwd=GAME, capture_output=True, text=True)
assert run.returncode == 0, run.stderr[-800:]

new_rom = (OUT / 'Kirby - Seven Abilities.sfc').read_bytes(); new_kx = (OUT / 'Seven-Abilities.kx').read_bytes()
man = json.loads((OUT / 'build-manifest.json').read_text())
placed = {e['room']: e['placed'] for e in man['rooms']['edits']}
assert placed == {1: '71:0000', 3: 'in-place'}, placed
s3, slot3 = R.room_stream(rom, 3)
p1 = R.POINTERS + 4
for i in (j for j in range(len(rom)) if rom[j] != new_rom[j]):
    assert p1 <= i < p1 + 3 or s3 <= i < s3 + slot3 or 0x7FDC <= i < 0x7FE0, hex(i)
assert new_kx[:len(kx)] == kx and len(new_kx) > 0x10000
base = BASE.read_bytes(); ips = (OUT / 'Seven-Abilities.ips').read_bytes()
out = bytearray(base); q = 5
while ips[q:q + 3] != b'EOF':
    o = int.from_bytes(ips[q:q + 3], 'big'); n = int.from_bytes(ips[q + 3:q + 5], 'big'); q += 5
    if n: out[o:o + n] = ips[q:q + n]; q += n
    else: n = int.from_bytes(ips[q:q + 2], 'big'); out[o:o + n] = bytes([ips[q + 2]]) * n; q += 3
assert bytes(out) == new_rom, 'IPS does not reproduce the edited ROM'
img = new_rom + new_kx
for i, d0 in rooms.items():
    d1 = R.decode_room(img, i)
    if i in want: assert d1['layout'] == want[i] and d1['sprites'] == d0['sprites'] and d1['exits'] == d0['exits'], i
    else: assert (d1['layout'], d1['sprites'], d1['exits']) == (d0['layout'], d0['sprites'], d0['exits']), f'room {i} changed'
print('PASS build', json.dumps({'placed': placed, 'manifest_rooms': man['rooms']['edits'], 'kx_bytes': len(new_kx),
                                'rom_sha256': man['rom_sha256'][:12], 'other_rooms_same': len(rooms) - 2}))


def live_layout(s):
    s.lib.kss_wram.restype = ctypes.POINTER(ctypes.c_uint8); w = s.lib.kss_wram()
    W, H = s.lib.kss_read_iram16(0x3750) >> 8, s.lib.kss_read_iram16(0x3756) >> 8
    return [[w[0x10000 + 2 * (r * W + c)] | w[0x10001 + 2 * (r * W + c)] << 8 for c in range(W)] for r in range(H)]


def wait_load(s):
    gone = False
    for _ in range(1200):
        s.step(); kt = s.word(0x23E)
        if kt == 0xFFFF: gone = True
        elif gone and kt == 1: break
    s.step(n=60)


def route(name):
    return json.loads((HERE / 'scenarios/routes' / name).read_text())['tape']


def oracle(s, name, room_no, raised):
    """Live map must equal the edit; drops agree; raised columns rest higher."""
    assert s.observe()['room'] == room_no and live_layout(s) == want[room_no], f'room {room_no} live != edit'
    room = I.capture(s); settled = OUT / f'{name}.state'; s.save_state(settled); s.close()
    rows = I.verify(lambda: _load(settled), room)
    bad = [v for v in rows if v['verdict'].startswith('MISMATCH')]
    assert not bad, bad
    proven = []
    for c, top in raised.items():
        v = next(v for v in rows if v['col'] == c)
        if v['verdict'].startswith('skip'): continue
        assert v['verdict'] == 'ok-solid' and v['map_floor_row'] == top and v['rest_y'] + I.KIRBY_FOOT == top * I.T, v
        proven.append(c)
    assert proven, f'room {room_no}: no edited column proven'
    return {'drops_agreeing': sum(v['verdict'].startswith('ok-') for v in rows), 'mismatches': 0, 'raised_columns_proven': proven}


def _load(path):
    s = S.Session(OUT, mods=False); s.load_state(path); return s, []


s = S.Session(OUT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
for n, p1_, p2 in route('green-room1-door-room2.json'): s.step(p1_, p2, n)
wait_load(s); assert s.observe()['room'] == 2 and live_layout(s) == rooms[2]['layout'], 'room 2 changed'
s.step(S.BUTTONS['UP'], 0, 3); wait_load(s)
print('PASS room 1 (expansion), native', json.dumps(oracle(s, 'r1', 1, {c: r - 2 for c, r in PILLARS.items()})))

s = S.Session(OUT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
for n, p1_, p2 in route('green-room1-warp-star.json'): s.step(p1_, p2, n)
wait_load(s)
print('PASS room 3 (in place), native', json.dumps(oracle(s, 'r3', 3, {R3[0]: R3[1] - 1})))
print(json.dumps({'passed': True}))
