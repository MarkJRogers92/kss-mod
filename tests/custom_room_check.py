"""The first custom room, kss-deuce/rooms/treasure-hall.room, built and played natively.

/usr/bin/python3 tests/custom_room_check.py

Treasure Hall replaces Green Greens room 2 (the hut behind room 1's door),
widened from 11x9 to 40x9 with the hut's own blocks. The build (--rooms
rooms) must place it in the expansion with the new size and change no other
room. Natively, entering through room 1's door:
  - the room is 40x9, its live map equals the file and its live spawn list
    equals the file's objects
  - the drop oracle agrees with the map in every column (0 mismatches)
  - it is passable: holding right with hops reaches the far end
  - the entrance door leads back to room 1's door, and the exit door (col 35)
    leads to room 1 column 28 beside the Warp Star
The entrance door is used where Kirby arrives (as a player would); the exit
door from a logged Kirby position write onto its ledge. (A Kirby dropped onto
the entrance ledge drifts about 18 px left, off the door tile.)
Build output stays in out-rooms/treasure-hall/ (git-ignored).
"""
import ctypes, json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'tools'), str(HERE)]
import room_rom as R, room_inspector as I, scenario as S
GAME = (HERE / '../../kss-deuce').resolve(); BUILD = GAME / 'build'
sys.path.insert(0, str(GAME / 'source')); import room_text as T, room_codec as rc

OUT = HERE / 'out-rooms/treasure-hall'
BASE = Path('/Users/markrogers/Documents/Codex/2026-10-14/task-4/originals/Kirby Super Star (USA).sfc')
FILES = ('Kirby - Seven Abilities.sfc', 'Seven-Abilities.ips', 'Seven-Abilities.kx')
room_file = T.parse_text((GAME / 'rooms/treasure-hall.room').read_text())
rom = (BUILD / FILES[0]).read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint green-pip-created is stale'

run = subprocess.run([sys.executable, '-B', '-S', 'source/build_combined.py', str(BASE), '--output', str(OUT), '--rooms', 'rooms'],
                     cwd=GAME, capture_output=True, text=True)
assert run.returncode == 0, run.stderr[-800:]
man = json.loads((OUT / 'build-manifest.json').read_text())['rooms']['edits']
assert len(man) == 1 and man[0]['room'] == 2 and man[0]['size'] == [40, 9] and man[0]['placed'] == '71:0000', man
img = (OUT / FILES[0]).read_bytes() + (OUT / FILES[2]).read_bytes()
checked = 0
for i in range(1024):
    try: d0 = R.decode_room(rom, i)
    except Exception: continue
    if not (0 < d0['width'] <= 1024 and 0 < d0['height'] <= 256): continue
    d1 = R.decode_room(img, i); checked += 1
    if i == 2:
        assert (d1['width'], d1['height']) == (40, 9) and d1['layout'] == room_file['layout'] and d1['sprites'] == room_file['objects']
        assert rc.same_exits(d1['exits'], room_file['exits'])
    else: assert (d1['layout'], d1['sprites'], d1['exits']) == (d0['layout'], d0['sprites'], d0['exits']), i
print('PASS build', json.dumps({'manifest': man[0], 'rooms_checked': checked}))


def wait_load(s):
    gone = False
    for _ in range(1200):
        s.step(); kt = s.word(0x23E)
        if kt == 0xFFFF: gone = True
        elif gone and kt == 1: break
    s.step(n=60)


def live_layout(s):
    s.lib.kss_wram.restype = ctypes.POINTER(ctypes.c_uint8); w = s.lib.kss_wram()
    W, H = s.lib.kss_read_iram16(0x3750) >> 8, s.lib.kss_read_iram16(0x3756) >> 8
    return [[w[0x10000 + 2 * (r * W + c)] | w[0x10001 + 2 * (r * W + c)] << 8 for c in range(W)] for r in range(H)]


def enter():
    s = S.Session(OUT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
    for n, p1, p2 in json.loads((HERE / 'scenarios/routes/green-room1-door-room2.json').read_text())['tape']: s.step(p1, p2, n)
    wait_load(s); assert s.observe()['room'] == 2; return s


def put_kirby(s, x, y):
    s.lib.kss_bwram.restype = ctypes.POINTER(ctypes.c_uint8); ram = s.lib.kss_bwram()
    for off, val in ((0x894, x), (0x988, x), (0x90E, y), (0xA02, y), (0xB70, 0), (0xBEA, 0)): ram[off] = val & 255; ram[off + 1] = val >> 8


s = enter()
assert live_layout(s) == room_file['layout'], 'live map != room file'
room = I.capture(s)
assert (room['width'], room['height']) == (40, 9) and room['spawns'] == room_file['objects'], room['spawns']
settled = OUT / 'hall.state'; s.save_state(settled); s.close()


def reload():
    s = S.Session(OUT, mods=False); s.load_state(settled); return s, []


rows = I.verify(reload, room)
bad = [v for v in rows if v['verdict'].startswith('MISMATCH')]
assert not bad, bad
summary = {k: sum(1 for v in rows if v['verdict'] == k) for k in sorted({v['verdict'] for v in rows})}
print('PASS live room', json.dumps({'size': [40, 9], 'live_map_equals_file': True, 'spawns_equal_file': len(room['spawns']), 'drop_oracle': summary}))

s, _ = reload(); far = 0
for f in range(1500):
    s.step(S.BUTTONS['RIGHT'] | (S.BUTTONS['B'] if f % 40 < 10 else 0), 0, 1); far = max(far, s.word(0x988))
    if far >= 33 * 24: break
s.close(); assert far >= 33 * 24, ('hold right did not reach the far end', far)
print('PASS passable', json.dumps({'reached_x': far, 'frames': f + 1}))


def use_door(x=None):
    s, _ = reload()
    if x is None: s.step(S.BUTTONS['UP'], 0, 3); wait_load(s); res = (s.observe()['room'], s.word(0x988), s.word(0xA02)); s.close(); return res
    put_kirby(s, x, 90); s.step(n=40)
    assert abs(s.word(0x988) - x) <= 12 and s.word(0xA02) + I.KIRBY_FOOT == 5 * I.T, ('not on the ledge', s.word(0x988), s.word(0xA02))
    s.step(S.BUTTONS['UP'], 0, 3); wait_load(s); res = (s.observe()['room'], s.word(0x988), s.word(0xA02)); s.close(); return res


def arrived(res, e): return res[0] == e['dest_room'] and abs(res[1] - e['dest_x']) <= 12 and abs(res[2] - e['dest_y']) <= 24


entrance, exit_ = room_file['exits']
res_in = use_door(); assert arrived(res_in, entrance), res_in
res_out = use_door(exit_['src_x'] + 12); assert arrived(res_out, exit_), res_out
print('PASS doors', json.dumps({'entrance_door_to': res_in, 'exit_door_to': res_out}))
print(json.dumps({'passed': True}))
