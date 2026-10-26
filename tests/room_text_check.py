"""Room text files (.room: ASCII map + named palette) drive the real build, checked natively.

/usr/bin/python3 tests/room_text_check.py

1. Export rooms 1 and 3 with kss-deuce/source/room_text.py (palette names from
   the room-inspector captures when present). Every real room's export parses
   back to no edits. Building the unchanged files gives ROM, IPS and .kx
   byte-identical to the default build.
2. Paint by editing text, as a person would: room 1 gets two-tile pillars by
   copying the floor-top symbol upward in 12 columns. Room 3 gets a new legend
   line ("painted-floor") used at column 26 row 5.
3. The painted build must equal, byte for byte, a build from the equivalent
   JSON tile edits. Natively, both rooms load equal to the painted maps, the
   drop oracle agrees in every column and the edited columns rest higher.
Files stay in out-rooms/g3-text/ (git-ignored: exports hold the game's maps).
"""
import ctypes, json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'tools'), str(HERE)]
import room_rom as R, room_inspector as I, scenario as S
GAME = (HERE / '../../kss-deuce').resolve(); BUILD = GAME / 'build'
sys.path.insert(0, str(GAME / 'source')); import room_text as T

OUT = HERE / 'out-rooms/g3-text'
BASE = Path('/Users/markrogers/Documents/Codex/2026-10-14/task-4/originals/Kirby Super Star (USA).sfc')
PILLARS = {4: 7, 5: 7, 6: 7, 8: 6, 9: 6, 10: 6, 14: 6, 15: 6, 17: 6, 18: 6, 25: 5, 28: 5}   # column: floor row (not 31-32)
R3 = (26, 6)
FILES = ('Kirby - Seven Abilities.sfc', 'Seven-Abilities.ips', 'Seven-Abilities.kx')
rom = (BUILD / FILES[0]).read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint green-pip-created is stale'


def build(rooms_arg, out):
    run = subprocess.run([sys.executable, '-B', '-S', 'source/build_combined.py', str(BASE), '--output', str(out), '--rooms', str(rooms_arg)],
                         cwd=GAME, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-800:]
    return {f: (out / f).read_bytes() for f in FILES}, json.loads((out / 'build-manifest.json').read_text())


# 1. export, parse back, unchanged build
rooms = {}
for i in range(1024):
    try: d = R.decode_room(rom, i)
    except Exception: continue
    if 0 < d['width'] <= 1024 and 0 < d['height'] <= 256: rooms[i] = d
for i in rooms: assert not T.edits_from_text(rom, T.export_text(rom, i))['tiles'], i
texts = {}
for i in (1, 3):
    cap = HERE / f'out-rooms/s0-l0-r{i}.json'
    texts[i] = T.export_text(rom, i, T.classes_from_capture(cap) if cap.exists() else None)
plain = OUT / 'unchanged'; plain.mkdir(parents=True, exist_ok=True)
for i, t in texts.items(): (plain / f'room{i}.room').write_text(t)
got, man = build(plain, OUT / 'build-unchanged')
assert got == {f: (BUILD / f).read_bytes() for f in FILES}, 'unchanged room files changed the build'
assert man['rooms']['edits'] == []
print('PASS unchanged', json.dumps({'rooms_round_tripped': len(rooms), 'build_byte_identical': True}))


# 2. paint
def lines_of(text):
    lines = text.split('\n'); m = lines.index('map') + 1; return lines, m


lines, m = lines_of(texts[1]); grid = [list(l) for l in lines[m:m + 8]]
for c, r in PILLARS.items():
    for k in (1, 2): grid[r - k][c] = grid[r][c]
lines[m:m + 8] = [''.join(g) for g in grid]; painted1 = '\n'.join(lines)
lines, m = lines_of(texts[3]); t3 = T.parse_text(texts[3]); grid = [list(l) for l in lines[m:m + 8]]
new_sym = next(chr(o) for o in range(33, 127) if chr(o) not in t3['legend'] and chr(o) != ';')
floor = t3['layout'][R3[1]][R3[0]]
lines.insert(lines.index('objects'), f'{new_sym} {floor:04X} painted-floor'); m += 1   # legend ends where objects start
grid[R3[1] - 1][R3[0]] = new_sym
lines[m:m + 8] = [''.join(g) for g in grid]; painted3 = '\n'.join(lines)
paint = OUT / 'painted'; paint.mkdir(parents=True, exist_ok=True)
(paint / 'room1.room').write_text(painted1); (paint / 'room3.room').write_text(painted3)
want = {1: T.parse_text(painted1)['layout'], 3: T.parse_text(painted3)['layout']}
assert want[3][R3[1] - 1][R3[0]] == floor

# 3. painted build == JSON build; then native
got, man = build(paint, OUT / 'build')
placed = {e['room']: e['placed'] for e in man['rooms']['edits']}
assert placed == {1: '71:0000', 3: 'in-place'}, placed
spec = {'rooms': [{'room': i, 'tiles': [[c, r, f'{w:04X}'] for r, row in enumerate(want[i]) for c, w in enumerate(row)
                                         if w != rooms[i]['layout'][r][c]]} for i in (1, 3)]}
(OUT / 'equivalent.json').write_text(json.dumps(spec))
got_json, _ = build(OUT / 'equivalent.json', OUT / 'build-json')
assert got == got_json, 'painted build != equivalent JSON build'
img = got[FILES[0]] + got[FILES[2]]
for i, d0 in rooms.items():
    d1 = R.decode_room(img, i)
    assert d1['layout'] == want.get(i, d0['layout']) and d1['sprites'] == d0['sprites'], i
print('PASS painted build', json.dumps({'placed': placed, 'new_symbol': new_sym, 'equals_json_build': True,
                                        'tiles': {e['room']: e['tiles'] for e in man['rooms']['edits']}}))
OUT = OUT / 'build'


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
print('PASS room 1 painted (expansion), native', json.dumps(oracle(s, 'r1', 1, {c: r - 2 for c, r in PILLARS.items()})))
s = S.Session(OUT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
for n, p1_, p2 in route('green-room1-warp-star.json'): s.step(p1_, p2, n)
wait_load(s)
print('PASS room 3 painted (in place), native', json.dumps(oracle(s, 'r3', 3, {R3[0]: R3[1] - 1})))
print(json.dumps({'passed': True}))
