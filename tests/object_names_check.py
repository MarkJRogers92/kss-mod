"""Object names (kss-deuce/source/object_types.json) mean what they say, checked natively.

/usr/bin/python3 tests/object_names_check.py

Static: every real room's object list exports (names where known) and parses
back unchanged; each name is unique; every name justified by "ability X (only
giver)" is the only species in the table that gives X (the table holds every
ability the inhale survey in research/object-survey/ saw).
Native, per named species: a Treasure Hall .room text whose object list uses
the NAME is parsed and built into the expansion (as build_combined does), and
in the game:
  - the spawned actor's species word (BW-RAM 0xD58 + 2*slot) is that species
  - names with an ability: Kirby inhales and swallows it and gets that ability
  - maxim-tomato: swallowing it heals Kirby
Builds stay in out-rooms/object-names/ (git-ignored).
"""
import ctypes, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'tools'), str(HERE)]
import room_rom as R, scenario as S
GAME = (HERE / '../../kss-deuce').resolve(); BUILD = GAME / 'build'
sys.path.insert(0, str(GAME / 'source')); import room_text as T, room_codec as rc

OUT = HERE / 'out-rooms/object-names'
TABLE = json.loads((GAME / 'source/object_types.json').read_text())
ABIL = {v: int(k) for k, v in TABLE['abilities'].items()}
rom = (BUILD / 'Kirby - Seven Abilities.sfc').read_bytes(); kx = (BUILD / 'Seven-Abilities.kx').read_bytes()
side = json.loads((S.CHECK / 'green-pip-created.json').read_text())
assert side['identity'] == S.identity(BUILD), 'checkpoint green-pip-created is stale'

# static
names = [v['name'] for v in TABLE['species'].values() if 'name' in v]
assert len(names) == len(set(names)), 'duplicate names'
rooms = 0
for i in range(1024):
    try: d = R.decode_room(rom, i)
    except Exception: continue
    if not (0 < d['width'] <= 1024 and 0 < d['height'] <= 256): continue
    assert T.parse_text(T.export_text(rom, i))['objects'] == d['sprites'], i; rooms += 1
givers = {}
for h, v in TABLE['species'].items():
    if 'ability' in v: givers.setdefault(ABIL[v['ability']], []).append(h)
for h, v in TABLE['species'].items():
    if 'only giver' in v.get('evidence', ''):
        assert givers[ABIL[v['ability']]] == [h], (v['name'], givers[ABIL[v['ability']]])
print('PASS static', json.dumps({'rooms_round_tripped': rooms, 'names': len(names)}))

hall = (GAME / 'rooms/treasure-hall.room').read_text()
head, rest = hall.split('\nobjects\n'); _, tail = rest.split('\nexits\n')
TAPE = json.loads((HERE / 'scenarios/routes/green-room1-door-room2.json').read_text())['tape']
K = S.BUTTONS


def wait_load(s):
    gone = False
    for _ in range(1200):
        s.step(); kt = s.word(0x23E)
        if kt == 0xFFFF: gone = True
        elif gone and kt == 1: break


def session_with(token):
    text = f'{head}\nobjects\ndoor-star 156 108\ndoor-star 852 108\n{token} 262 148\nexits\n{tail}'
    t = T.parse_text(text)
    r, k = rc.relocate_room(rom, kx, 2, t['layout'], sprites=t['objects'], exits=t['exits'], size=(t['width'], t['height']))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'Kirby - Seven Abilities.sfc').write_bytes(r); (OUT / 'Seven-Abilities.kx').write_bytes(k)
    s = S.Session(OUT, mods=False); s.load_state(S.CHECK / 'green-pip-created.state')
    for n, p1, p2 in TAPE: s.step(p1, p2, n)
    wait_load(s); return s, t['objects'][2]['type']


def put(s, pairs):
    s.lib.kss_bwram.restype = ctypes.POINTER(ctypes.c_uint8); ram = s.lib.kss_bwram()
    for off, val in pairs: ram[off] = val & 255; ram[off + 1] = val >> 8


rows = []
for h, v in sorted(TABLE['species'].items()):
    if 'name' not in v: continue
    low = int(v.get('tested_word', h + '00')[2:], 16)
    token = v['name'] + (f':{low:02X}' if low else '')
    s, word = session_with(token); assert int(word, 16) == int(h, 16) << 8 | low
    s.step(n=20)
    slots = [k for k in range(2, 61) if s.word(0x23E + 2 * k) == 9 and s.word(0xD58 + 2 * k) == int(word, 16)]
    assert slots, (v['name'], 'no actor with that species word')
    row = {'name': token, 'word': word}
    if 'ability' in v or v['name'] == 'maxim-tomato':
        put(s, ((0x894, 220), (0x988, 220), (0x90E, 150), (0xA02, 150), (0xB70, 0), (0xBEA, 0),
                (0x896, 880), (0x98A, 880), (0x910, 150), (0xA04, 150), (0x137C, 40)))   # Kirby beside it, helper away, HP 40
        s.step(K['RIGHT'], 0, 2); s.step(K['Y'], 0, 90); s.step(K['DOWN'], 0, 2); s.step(n=150)
        if 'ability' in v:
            row['ability'] = s.word(0x149F); assert row['ability'] == ABIL[v['ability']], (v['name'], row)
        else:
            row['hp'] = s.word(0x137C); assert row['hp'] > 40, (v['name'], row)
    s.close(); rows.append(row)
    print('PASS', json.dumps(row), flush=True)
print(json.dumps({'passed': True, 'names_checked': len(rows)}))
