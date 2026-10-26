"""Room objects (the sprite list) edited in a .room file, built and checked natively.

/usr/bin/python3 tests/room_objects_check.py

Room 1, edited as text:
  - delete the type-7501 object at (765, 68) (it snaps a landed Kirby to
    itself, which is why pillars at columns 31-32 failed the drop oracle before)
  - add pillars at columns 31-32 (two tiles on the floor at row 5)
  - add an enemy line "0200 444 125" (the type of the room's own enemy at
    (248, 77)), two columns right of the door Kirby comes back through
Checks: every real room's objects round-trip; the build applies the list
(manifest counts it); the room decodes to the edited map and list, others
unchanged. Natively (door to room 2 and back): the live spawn list equals the
edited list; an object actor (kind 9) appears at the added spot, which never
happens in the unedited build; the drop oracle agrees in every column and the
pillar columns 31-32 rest on top (the 7501 snap is gone).
Files stay in out-rooms/g3-objects/ (git-ignored).
"""
import ctypes, json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'tools'), str(HERE)]
import room_rom as R, room_inspector as I, scenario as S
GAME = (HERE / '../../kss-deuce').resolve(); BUILD = GAME / 'build'
sys.path.insert(0, str(GAME / 'source')); import room_text as T

OUT = HERE / 'out-rooms/g3-objects'
BASE = Path('/Users/markrogers/Documents/Codex/2026-10-14/task-4/originals/Kirby Super Star (USA).sfc')
PILLARS = {31: 5, 32: 5}            # column: floor row
ADDED = {'type': '0200', 'x': 444, 'y': 125}
FILES = ('Kirby - Seven Abilities.sfc', 'Seven-Abilities.ips', 'Seven-Abilities.kx')
rom = (BUILD / FILES[0]).read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint green-pip-created is stale'
rooms = {}
for i in range(1024):
    try: d = R.decode_room(rom, i)
    except Exception: continue
    if 0 < d['width'] <= 1024 and 0 < d['height'] <= 256: rooms[i] = d
for i, d in rooms.items():
    t = T.parse_text(T.export_text(rom, i)); assert t['objects'] == d['sprites'], i

# paint room 1 as text
text = T.export_text(rom, 1); lines = text.split('\n')
o0, o1 = lines.index('objects'), lines.index('exits')   # drop the 7501 line however it is written (hex or name)
lines = lines[:o0 + 1] + [l for l in lines[o0 + 1:o1] if T.type_word(l.split()[0]) != 0x7501] + lines[o1:]
lines.insert(lines.index('exits'), f"{ADDED['type']} {ADDED['x']} {ADDED['y']} added-enemy ; col {ADDED['x'] // 24}")
m = lines.index('map') + 1; grid = [list(l) for l in lines[m:m + 8]]
for c, r in PILLARS.items():
    for k in (1, 2): grid[r - k][c] = grid[r][c]
lines[m:m + 8] = [''.join(g) for g in grid]
painted = '\n'.join(lines); want = T.parse_text(painted)
want_objs = [sp for sp in rooms[1]['sprites'] if sp['type'] != '7501'] + [ADDED]
assert want['objects'] == want_objs
src = OUT / 'rooms'; src.mkdir(parents=True, exist_ok=True); (src / 'room1.room').write_text(painted)
run = subprocess.run([sys.executable, '-B', '-S', 'source/build_combined.py', str(BASE), '--output', str(OUT / 'build'), '--rooms', str(src)],
                     cwd=GAME, capture_output=True, text=True)
assert run.returncode == 0, run.stderr[-800:]
got = {f: (OUT / 'build' / f).read_bytes() for f in FILES}
man = json.loads((OUT / 'build/build-manifest.json').read_text()); entry = man['rooms']['edits'][0]
assert entry['room'] == 1 and entry['objects'] == len(want_objs) and entry['tiles'] == 4, entry
img = got[FILES[0]] + got[FILES[2]]
for i, d0 in rooms.items():
    d1 = R.decode_room(img, i)
    if i == 1: assert d1['layout'] == want['layout'] and d1['sprites'] == want_objs and d1['exits'] == d0['exits']
    else: assert (d1['layout'], d1['sprites'], d1['exits']) == (d0['layout'], d0['sprites'], d0['exits']), i
print('PASS build', json.dumps({'objects_round_tripped_rooms': len(rooms), 'manifest': entry}))
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


def enter_room1(build):
    """Door to room 2 and back; return the session and object actors seen in the first 60 frames back."""
    s = S.Session(build, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
    for n, p1_, p2 in route('green-room1-door-room2.json'): s.step(p1_, p2, n)
    wait_load(s); assert s.observe()['room'] == 2 and live_layout(s) == rooms[2]['layout'], 'room 2 changed'
    s.step(S.BUTTONS['UP'], 0, 3); gone, seen = False, []
    for _ in range(1200):
        s.step(); kt = s.word(0x23E)
        if kt == 0xFFFF: gone = True
        elif gone and kt == 1: break
    for _ in range(60):
        s.step()
        seen += [(s.word(0x988 + 2 * k), s.word(0xA02 + 2 * k)) for k in range(2, 61) if s.word(0x23E + 2 * k) == 9]
    return s, seen


near = lambda seen: [p for p in seen if abs(p[0] - ADDED['x']) <= 12 and abs(p[1] - ADDED['y']) <= 24]
s, seen = enter_room1(BUILD); assert s.observe()['room'] == 1; s.close()
assert not near(seen), ('unedited build already has an object there', near(seen)[:3])
s, seen = enter_room1(OUT)
assert near(seen), 'added object never appeared'
spawns = I.capture(s)['spawns']
assert spawns == want_objs, ('live spawn list != edited objects', spawns)
want = {1: want['layout']}
res = oracle(s, 'r1', 1, {c: r - 2 for c, r in PILLARS.items()})
assert 31 in res['raised_columns_proven'], res
print('PASS room 1 objects, native', json.dumps({'live_spawns_equal_edit': True, 'added_actor_at': near(seen)[0], **res}))
print(json.dumps({'passed': True}))
