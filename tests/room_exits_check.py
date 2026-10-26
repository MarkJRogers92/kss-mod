"""Room exits (where doors lead) edited in a .room file, built and checked natively.

/usr/bin/python3 tests/room_exits_check.py

A. Retarget, in place: room 1's door exit now leads to room 3, arriving at
   (636, 132) (room 3 column 26, on the floor). Same exit count, so only
   section 0 of the record changes in the ROM. Walking through the door (the
   recorded door route) must land Kirby in room 3 at that spot.
B. A new door, relocated: room 1 gets a door tile (its own '@') at column 18
   row 5, a door star (7200) on it and a third exit line "3 432 120 636 132".
   The exit count changes, so the build moves the record into the expansion.
   Room 1 is reloaded from the edited ROM (door to room 2 and back, arriving
   at column 16); walking right to column 18 and pressing Up must land Kirby
   in room 3 at (636, 132);
   the old door must still lead to room 2 at its recorded spot.
Every real room's exits round-trip; other rooms stay unchanged.
Files stay in out-rooms/g3-exits/ (git-ignored).
"""
import json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'tools'), str(HERE)]
import room_rom as R, scenario as S
GAME = (HERE / '../../kss-deuce').resolve(); BUILD = GAME / 'build'
sys.path.insert(0, str(GAME / 'source')); import room_text as T, room_codec as rc

OUT = HERE / 'out-rooms/g3-exits'
BASE = Path('/Users/markrogers/Documents/Codex/2026-10-14/task-4/originals/Kirby Super Star (USA).sfc')
DEST = (3, 636, 132)                    # room 3, column 26 on the floor (rest y 130)
NEW_DOOR = (18, 5)                       # column, row
FILES = ('Kirby - Seven Abilities.sfc', 'Seven-Abilities.ips', 'Seven-Abilities.kx')
rom = (BUILD / FILES[0]).read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint green-pip-created is stale'
rooms = {}
for i in range(1024):
    try: d = R.decode_room(rom, i)
    except Exception: continue
    if 0 < d['width'] <= 1024 and 0 < d['height'] <= 256: rooms[i] = d
for i, d in rooms.items(): assert rc.same_exits(T.parse_text(T.export_text(rom, i))['exits'], d['exits']), i


def build(name, text):
    src = OUT / name; src.mkdir(parents=True, exist_ok=True); (src / 'room1.room').write_text(text)
    run = subprocess.run([sys.executable, '-B', '-S', 'source/build_combined.py', str(BASE), '--output', str(src / 'build'), '--rooms', str(src)],
                         cwd=GAME, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-800:]
    got = {f: (src / 'build' / f).read_bytes() for f in FILES}
    man = json.loads((src / 'build/build-manifest.json').read_text())['rooms']['edits'][0]
    want = T.parse_text(text); img = got[FILES[0]] + got[FILES[2]]
    for i, d0 in rooms.items():
        d1 = R.decode_room(img, i)
        if i == 1: assert d1['layout'] == want['layout'] and d1['sprites'] == want['objects'] and rc.same_exits(d1['exits'], want['exits'])
        else: assert (d1['layout'], d1['sprites'], d1['exits']) == (d0['layout'], d0['sprites'], d0['exits']), i
    return src / 'build', got, man


def exit_line(e): return f"{e['dest_room']} {e['src_x']} {e['src_y']} {e['dest_x']} {e['dest_y']}"


text = T.export_text(rom, 1); door = rooms[1]['exits'][0]; assert door['door'] and door['dest_room'] == 2
retarget = text.replace(exit_line(door), f"{DEST[0]} {door['src_x']} {door['src_y']} {DEST[1]} {DEST[2]}")
assert retarget != text
out_a, got_a, man_a = build('retarget', retarget)
assert man_a['placed'] == 'in-place' and man_a['exits'] == 2, man_a
p = rc.room_record(rom, 1) + 0x3A
diff = [i for i in range(len(rom)) if rom[i] != got_a[FILES[0]][i]]
assert all(p <= i < p + 24 or 0x7FDC <= i < 0x7FE0 for i in diff) and got_a[FILES[2]] == (BUILD / FILES[2]).read_bytes(), [hex(i) for i in diff]
print('PASS A build', json.dumps({'manifest': man_a, 'rom_bytes_changed': len(diff)}))

lines = text.split('\n'); c, r = NEW_DOOR
legend = T.parse_text(text)['legend']; door_sym = next(s for s, w in legend.items() if w == rooms[1]['layout'][door['src_y'] // 24][door['src_x'] // 24])
m = lines.index('map') + 1; row = list(lines[m + r]); row[c] = door_sym; lines[m + r] = ''.join(row)
lines.insert(lines.index('exits'), f'7200 {c * 24 + 12} 132 door-star ; new door')
lines.insert(lines.index('map'), f'{DEST[0]} {c * 24} {r * 24} {DEST[1]} {DEST[2]} ; new door col {c} row {r}')
newdoor = '\n'.join(lines)
out_b, got_b, man_b = build('newdoor', newdoor)
assert man_b['placed'] == '71:0000' and man_b['exits'] == 3 and man_b['objects'] == 9 and man_b['tiles'] == 1, man_b
print('PASS B build', json.dumps({'manifest': man_b}))


def wait_load(s):
    gone = False
    for _ in range(1200):
        s.step(); kt = s.word(0x23E)
        if kt == 0xFFFF: gone = True
        elif gone and kt == 1: break
    s.step(n=60)


def start(build):
    s = S.Session(build, mods=False); s.load_state(S.CHECK / 'green-pip-created.state'); return s


def door_route(build):
    s = start(build)
    for n, p1, p2 in json.loads((HERE / 'scenarios/routes/green-room1-door-room2.json').read_text())['tape']: s.step(p1, p2, n)
    wait_load(s); res = (s.observe()['room'], s.word(0x988), s.word(0xA02)); s.close(); return res


def new_door_route(build):
    s = start(build); x0 = c * 24
    for n, p1, p2 in json.loads((HERE / 'scenarios/routes/green-room1-door-room2.json').read_text())['tape']: s.step(p1, p2, n)
    wait_load(s); assert s.observe()['room'] == 2
    s.step(S.BUTTONS['UP'], 0, 3); wait_load(s); assert s.observe()['room'] == 1     # room 1 reloaded from this build
    for _ in range(600):
        if s.word(0x988) >= x0 + 6: break
        s.step(S.BUTTONS['RIGHT'], 0, 1)
    s.step(n=20); x = s.word(0x988); assert x0 <= x < x0 + 24, ('not on the new door', x)
    s.step(S.BUTTONS['UP'], 0, 3); wait_load(s)
    res = (s.observe()['room'], s.word(0x988), s.word(0xA02)); s.close(); return res


def arrived(res, room, x, y): return res[0] == room and abs(res[1] - x) <= 12 and abs(res[2] - y) <= 24


base_res = door_route(BUILD)
assert arrived(base_res, 2, door['dest_x'], door['dest_y']), base_res
res_a = door_route(out_a); assert arrived(res_a, *DEST), res_a
print('PASS A native', json.dumps({'unedited_door_to': base_res, 'retargeted_door_to': res_a}))
old_b = door_route(out_b); assert arrived(old_b, 2, door['dest_x'], door['dest_y']), old_b
new_b = new_door_route(out_b); assert arrived(new_b, *DEST), new_b
ctrl = new_door_route(BUILD); assert ctrl[0] == 1, ('Up at column 18 left room 1 without the new door', ctrl)
print('PASS B native', json.dumps({'old_door_to': old_b, 'new_door_to': new_b, 'unedited_build_col18_up_stays_in': ctrl[0]}))
print(json.dumps({'passed': True}))
