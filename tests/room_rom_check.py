"""ROM room decoding must equal what the game loads (plan gate G1 -> G2).

/usr/bin/python3 tests/room_rom_check.py
For Green Greens rooms 1, 2 (room-1 door) and 3 (Warp Star): decode the room
from the ROM (tools/room_rom.py; pointer-table index = room number) and
require the full 16-bit layout words and the sprite records to equal the live
map at 7F:0000 and the spawn list at 7E:09A8/0BA8/0DA8 after the real load.
Live rooms are reached from the natural green-pip-created checkpoint.
"""
import ctypes, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE / 'tools')]
import scenario as S, room_rom as R
BUILD = (HERE / '../../kss-deuce/build').resolve()
BASE = Path('/Users/markrogers/Documents/Codex/2026-10-14/task-4/originals/Kirby Super Star (USA).sfc')
rom = BASE.read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint stale: rebuild it from its route'

def live(route):
    s = S.Session(BUILD, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
    s.lib.kss_wram.restype = ctypes.POINTER(ctypes.c_uint8)
    if route:
        for n, p1, p2 in json.loads((HERE / route).read_text())['tape']: s.step(p1, p2, n)
        gone = False
        for _ in range(1200):
            s.step(); kt = s.word(0x23E)
            if kt == 0xFFFF: gone = True
            elif gone and kt == 1: break
        s.step(n=60)
    ir = s.lib.kss_read_iram16; W, H = ir(0x3750) >> 8, ir(0x3756) >> 8; w = s.lib.kss_wram()
    wd = lambda a: w[a] | w[a + 1] << 8
    L = [[wd(0x10000 + 2 * (r * W + c)) for c in range(W)] for r in range(H)]
    sp = []
    for i in range(0, 0x100, 2):
        if wd(0x09A8 + i) == 0xFFFF: break
        sp.append({'type': f'{wd(0x09A8 + i):04X}', 'x': wd(0x0BA8 + i), 'y': wd(0x0DA8 + i)})
    room = s.observe()['room']; arrived = (s.word(0x894), s.word(0x90E)); s.close(); return room, W, H, L, sp, arrived

rows = []
for route in (None, 'scenarios/routes/green-room1-door-room2.json', 'scenarios/routes/green-room1-warp-star.json'):
    room, W, H, L, sp, arrived = live(route)
    d = R.decode_room(rom, room)
    assert (d['width'], d['height']) == (W, H), (room, d['width'], d['height'], W, H)
    diff = [(r, c) for r in range(H) for c in range(W) if d['layout'][r][c] != L[r][c]]
    assert not diff, (room, len(diff), diff[:5])
    assert d['sprites'] == sp, (room, d['sprites'], sp)
    # Every door tile (behavior 0x0F, from the inspector capture) has an exit
    # record whose source is that tile; non-door exits use source x FF00.
    insp = json.loads((HERE / 'out-rooms' / f's0-l0-r{room}.json').read_text())
    for door in insp['doors']:
        assert any(e['door'] and e['src_x'] // 24 == door['col'] and e['src_y'] // 24 == door['row'] for e in d['exits']), (room, door, d['exits'])
    # Arriving through an exit puts Kirby at its destination (the route's own exit).
    # (Doors only: a Warp Star flies Kirby in after the load, so his position
    # then is part of the landing animation, not the record's destination.)
    src = R.decode_room(rom, 1)['exits']; ex = next((e for e in src if e['dest_room'] == room), None)
    if route and ex and ex['door']:
        assert abs(arrived[0] - ex['dest_x']) <= 12 and abs(arrived[1] - ex['dest_y']) <= 24, (room, arrived, ex)
    rows.append({'room': room, 'size': [W, H], 'tiles_equal': W * H, 'sprites_equal': len(sp), 'packed_bytes': d['packed_bytes'],
                 'exits': [(e['dest_room'], 'door' if e['door'] else 'non-door') for e in d['exits']], 'arrived': arrived if route else None})
    print('PASS', json.dumps(rows[-1]))
print(json.dumps({'passed': True, 'rooms': len(rows)}))
