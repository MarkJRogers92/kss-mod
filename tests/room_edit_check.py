"""Room round trip and one-tile edit (plan gate G2 -> G3).

/usr/bin/python3 tests/room_edit_check.py

1. Unchanged round trip: writing every decodable room back unchanged gives a
   byte-identical ROM, and hal_pack re-encodes rooms 1-5 losslessly.
2. One edit: room 1 column 14 gets a solid block at row 5 (a copy of the
   floor-top block below it, so the floor rises one tile). The re-encoded
   stream must fit the original slot, and only bytes inside that slot change.
3. Other rooms unaffected: every other decodable room decodes the same.
4. Native: from green-pip-created, through the door to room 2 and back (the
   game reloads room 1 from the edited ROM). The live map must equal the
   edited decode, and the drop oracle must agree with the edited map in every
   column, with column 14 resting one tile higher. Room 2 (live) and room 3
   (Warp Star route) must equal the unedited decode.
The edited ROM lives in out-rooms/g3-edit/ (git-ignored), never in commits.
"""
import ctypes, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'tools'), str(HERE)]
import room_rom as R, room_inspector as I, scenario as S

BUILD = (HERE / '../../kss-deuce/build').resolve()
EDIT = HERE / 'out-rooms/g3-edit'
ROOM, COL, ROW = 1, 14, 5          # new solid tile; the old floor top is ROW + 1
rom = (BUILD / 'Kirby - Seven Abilities.sfc').read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint green-pip-created is stale'

# 1. unchanged round trip
rooms = {}
for i in range(1024):
    try: rooms[i] = R.decode_room(rom, i)
    except Exception: pass
for i, d in rooms.items():
    assert R.write_room(rom, i, d['layout']) == rom, f'room {i}: unchanged write is not byte-identical'
for i in range(1, 6):
    start, _ = R.room_stream(rom, i); data = R.hal_unpack(rom, start)[0]
    assert R.hal_unpack(R.hal_pack(data), 0)[0] == data, f'room {i}: hal_pack round trip'
print('PASS unchanged round trip', json.dumps({'rooms_written_back': len(rooms), 'byte_identical': True}))

# 2. one edit
d = rooms[ROOM]; layout = [row[:] for row in d['layout']]
before = layout[ROW][COL]; layout[ROW][COL] = layout[ROW + 1][COL]
edited = R.write_room(rom, ROOM, layout)
start, slot = R.room_stream(rom, ROOM)
diff = [i for i in range(len(rom)) if rom[i] != edited[i]]
assert diff and start <= diff[0] and diff[-1] < start + slot, 'edit escaped its slot'
assert R.decode_room(edited, ROOM)['layout'] == layout
EDIT.mkdir(parents=True, exist_ok=True)
(EDIT / 'Kirby - Seven Abilities.sfc').write_bytes(edited)
(EDIT / 'Seven-Abilities.kx').write_bytes((BUILD / 'Seven-Abilities.kx').read_bytes())
print('PASS edit fits', json.dumps({'room': ROOM, 'tile': [COL, ROW], 'word': f'{before:04X}->{layout[ROW][COL]:04X}',
                                    'bytes_changed': len(diff), 'slot': [hex(start), slot], 'new_stream': R.room_stream(edited, ROOM)[1]}))

# 3. other rooms unaffected (static)
for i, d0 in rooms.items():
    if i == ROOM: continue
    d1 = R.decode_room(edited, i)
    assert (d1['layout'], d1['sprites'], d1['exits']) == (d0['layout'], d0['sprites'], d0['exits']), f'room {i} changed'
print('PASS other rooms unchanged', json.dumps({'rooms_compared': len(rooms) - 1}))


# 4. native
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


s = S.Session(EDIT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
for n, p1, p2 in route('green-room1-door-room2.json'): s.step(p1, p2, n)
wait_load(s); assert s.observe()['room'] == 2
assert live_layout(s) == rooms[2]['layout'], 'room 2 live != unedited decode'
s.step(S.BUTTONS['UP'], 0, 3); wait_load(s); assert s.observe()['room'] == ROOM
assert live_layout(s) == layout, 'room 1 live != edited decode'
room = I.capture(s); settled = EDIT / 'r1.state'; s.save_state(settled); s.close()


def reload():
    s = S.Session(EDIT, mods=False); s.load_state(settled); return s, []


rows = I.verify(reload, room)
bad = [v for v in rows if v['verdict'].startswith('MISMATCH')]
assert not bad, bad
c14 = next(v for v in rows if v['col'] == COL)
assert c14['verdict'] == 'ok-solid' and c14['map_floor_row'] == ROW and c14['rest_y'] + I.KIRBY_FOOT == ROW * I.T, c14
print('PASS room 1 edited, native', json.dumps({'live_equals_edit': True, 'drops_agreeing': sum(v['verdict'].startswith('ok-') for v in rows),
                                               'mismatches': 0, 'col14_rest_y': c14['rest_y'], 'col14_floor_top': ROW * I.T,
                                               'was': (ROW + 1) * I.T}))

s = S.Session(EDIT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
for n, p1, p2 in route('green-room1-warp-star.json'): s.step(p1, p2, n)
wait_load(s); assert s.observe()['room'] == 3
assert live_layout(s) == rooms[3]['layout'], 'room 3 live != unedited decode'; s.close()
print('PASS rooms 2 and 3 live unchanged')
print(json.dumps({'passed': True}))
