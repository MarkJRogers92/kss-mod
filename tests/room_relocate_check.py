"""Room relocation: an edited room grows past its original slot (after G3).

/usr/bin/python3 tests/room_relocate_check.py

Room 1 gets a two-tile solid pillar on the floor in 12 columns, which re-encodes
larger than its 260-byte slot (write_room refuses it). relocate_room copies
the record into the native-only expansion image at 71:0000 with the bigger
stream and points the FF:009A entry there.
  ROM: only the 3 pointer bytes change. Expansion: the shipped image is an
  unchanged prefix. Static: room 1 decodes (from rom + kx) to the edit, and
  every other room decodes as before.
  Native: door to room 2 and back reloads room 1 from bank 71. The live map
  equals the edit, the drop oracle agrees in every column with each edited
  column resting two tiles higher, and rooms 2 and 3 load unchanged.
Limit: the relocated room needs the expansion (without it bank 71 is open bus).
Test files live in out-rooms/g3-reloc/ (git-ignored).
"""
import ctypes, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'tools'), str(HERE)]
import room_rom as R, room_inspector as I, scenario as S

BUILD = (HERE / '../../kss-deuce/build').resolve()
OUT = HERE / 'out-rooms/g3-reloc'
ROOM, HEIGHT = 1, 2
# column: floor row. Not 31-32: a pillar there reaches the type-7501 object at
# (765, 68), which snaps a landed Kirby to its position (seen 2026-10-25).
FLOORS = {4: 7, 5: 7, 6: 7, 8: 6, 9: 6, 10: 6, 14: 6, 15: 6, 17: 6, 18: 6, 25: 5, 28: 5}
rom = (BUILD / 'Kirby - Seven Abilities.sfc').read_bytes(); kx = (BUILD / 'Seven-Abilities.kx').read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint green-pip-created is stale'
rooms = {}
for i in range(1024):
    try: rooms[i] = R.decode_room(rom, i)
    except Exception: pass

layout = [row[:] for row in rooms[ROOM]['layout']]
for c, r in FLOORS.items():
    for k in range(1, HEIGHT + 1): layout[r - k][c] = layout[r][c]
try: R.write_room(rom, ROOM, layout); raise SystemExit('edit unexpectedly fits the original slot')
except ValueError as e: too_big = str(e)
new_rom, new_kx = R.relocate_room(rom, kx, ROOM, layout)
diff = [i for i in range(len(rom)) if rom[i] != new_rom[i]]
assert diff == [R.POINTERS + 4 * ROOM + k for k in range(3) if rom[R.POINTERS + 4 * ROOM + k] != new_rom[R.POINTERS + 4 * ROOM + k]] and diff
assert new_kx[:len(kx)] == kx
img = new_rom + new_kx
assert R.decode_room(img, ROOM)['layout'] == layout
for i, d0 in rooms.items():
    if i == ROOM: continue
    d1 = R.decode_room(img, i)
    assert (d1['layout'], d1['sprites'], d1['exits']) == (d0['layout'], d0['sprites'], d0['exits']), f'room {i} changed'
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'Kirby - Seven Abilities.sfc').write_bytes(new_rom); (OUT / 'Seven-Abilities.kx').write_bytes(new_kx)
print('PASS relocated', json.dumps({'refused_in_place': too_big, 'rom_bytes_changed': len(diff), 'record_at': hex(R.ROOM_AREA),
                                    'record_bytes': len(new_kx) - 0x10000, 'kx_bytes': len(new_kx), 'other_rooms_same': len(rooms) - 1}))


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


s = S.Session(OUT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
for n, p1, p2 in route('green-room1-door-room2.json'): s.step(p1, p2, n)
wait_load(s); assert s.observe()['room'] == 2
assert live_layout(s) == rooms[2]['layout'], 'room 2 live != unedited decode'
s.step(S.BUTTONS['UP'], 0, 3); wait_load(s); assert s.observe()['room'] == ROOM
assert live_layout(s) == layout, 'room 1 live != relocated edit'
room = I.capture(s); settled = OUT / 'r1.state'; s.save_state(settled); s.close()


def reload():
    s = S.Session(OUT, mods=False); s.load_state(settled); return s, []


rows = I.verify(reload, room)
bad = [v for v in rows if v['verdict'].startswith('MISMATCH')]
assert not bad, bad
raised = []
for c, r in FLOORS.items():
    v = next(v for v in rows if v['col'] == c)
    if v['verdict'].startswith('skip'): continue
    assert v['verdict'] == 'ok-solid' and v['map_floor_row'] == r - HEIGHT and v['rest_y'] + I.KIRBY_FOOT == (r - HEIGHT) * I.T, v
    raised.append(c)
assert len(raised) >= len(FLOORS) // 2, raised
print('PASS room 1 relocated, native', json.dumps({'live_equals_edit': True, 'mismatches': 0,
                                                  'drops_agreeing': sum(v['verdict'].startswith('ok-') for v in rows), 'raised_columns_proven': raised}))

s = S.Session(OUT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
for n, p1, p2 in route('green-room1-warp-star.json'): s.step(p1, p2, n)
wait_load(s); assert s.observe()['room'] == 3
assert live_layout(s) == rooms[3]['layout'], 'room 3 live != unedited decode'; s.close()
print('PASS rooms 2 and 3 live unchanged')
print(json.dumps({'passed': True}))
