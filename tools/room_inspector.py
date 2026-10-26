"""Read-only room inspector for the native runtime (system python3).

  /usr/bin/python3 tools/room_inspector.py ROUTE_OR_CHECKPOINT [--route TAPE.json] [--name NAME]

Loads a checkpoint (scenarios/checkpoints/NAME.state, identity-checked like
scenario.py), optionally replays a recorded route tape to reach another room,
then reads the room the game has loaded:

  room key      I-RAM $32EA/$32EE/$32F2 (subgame/level/room)
  size          I-RAM $3751 width (tiles), $3753 row stride (bytes),
                $3757 height (tiles); 24 x 24 px metatiles
  layout        WRAM 7F:0000, one u16 per tile, block = entry & 0x3FF
  behavior      WRAM 7F:62A0 + block (one byte per block)
  spawns        WRAM 7E:09A8 type/param, 7E:0BA8 x, 7E:0DA8 y, FFFF-terminated
  doors         behavior 0x0F tiles (Up on one enters the door; proven in rooms 1 and 3)
  classes       0x50 solid, 0x46-0x4B slope (surface inside the tile), 0x3F one-way
                platform, 0x70 block (solid from above; star blocks, breaking
                unverified), 0x27 pass-through decoration, 0x0F door; all
                established against Kirby drops on 2026-10-25

Writes out-rooms/NAME.json and NAME.png (git-ignored: derived game data stays
local). --verify drops Kirby (logged writes, disposable run) above every
column and checks the map: solid (0x50) columns must predict his rest to the
pixel, slope columns must land inside their tile, pits must be pits.
Nothing is written to the game except those logged test drops.
"""
import argparse, colorsys, ctypes, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import scenario as S

# Behavior classes established against Kirby drops (2026-10-25).
CLASSES = {0x00: 'empty', 0x50: 'solid', 0x27: 'pass', 0x0F: 'door', 0x3F: 'platform', 0x70: 'block',
           0x46: 'slope', 0x47: 'slope', 0x48: 'slope', 0x49: 'slope', 0x4A: 'slope', 0x4B: 'slope'}
COLORS = {'empty': (18, 18, 34), 'solid': (150, 200, 90), 'slope': (90, 160, 220), 'pass': (70, 70, 100), 'platform': (230, 150, 70), 'block': (220, 200, 120),
          'door': (255, 210, 60), 'other': (200, 110, 200)}
KIRBY_FOOT = 14   # Kirby's origin is 14 px above his feet
DROP_Y = 40       # drops start in row 1: below a one-row ceiling, above the play area
T = 24


def klass(b): return CLASSES.get(b, 'other')


def capture(s):
    s.lib.kss_wram.restype = ctypes.POINTER(ctypes.c_uint8)
    w = s.lib.kss_wram(); ir = s.lib.kss_read_iram16
    W, stride, H = ir(0x3750) >> 8, ir(0x3752) >> 8 | (ir(0x3754) & 0xFF) << 8, ir(0x3756) >> 8
    word = lambda a: w[a] | w[a + 1] << 8
    assert stride == W * 2, ('row stride is not width*2', W, stride)
    tiles = [[word(0x10000 + 2 * (r * W + c)) for c in range(W)] for r in range(H)]
    beh = [w[0x162A0 + i] for i in range(1024)]
    spawns = []
    for i in range(0, 0x100, 2):
        t = word(0x09A8 + i)
        if t == 0xFFFF: break
        spawns.append({'type': f'{t:04X}', 'x': word(0x0BA8 + i), 'y': word(0x0DA8 + i)})
    o = s.observe()
    cls = [[klass(beh[e & 0x3FF]) for e in row] for row in tiles]
    return {'key': {'subgame': o['subgame'], 'level': o['level'], 'room': o['room']}, 'width': W, 'height': H,
            'blocks': [[e & 0x3FF for e in row] for row in tiles], 'behavior': [[beh[e & 0x3FF] for e in row] for row in tiles],
            'class': cls, 'doors': [{'col': c, 'row': r, 'x': c * T + T // 2, 'y': r * T} for r in range(H) for c in range(W) if cls[r][c] == 'door'],
            'spawns': spawns, 'unclassified_behaviors': sorted({f'{b:02X}' for row in tiles for b in [beh[e & 0x3FF] for e in row] if b not in CLASSES})}


def render(room, path, scale=2):
    from PIL import Image, ImageDraw
    W, H = room['width'], room['height']
    im = Image.new('RGB', (W * T * scale // 2, H * T * scale // 2)); d = ImageDraw.Draw(im); k = scale / 2
    for r in range(H):
        for c in range(W):
            col = COLORS[room['class'][r][c]]
            d.rectangle([c * T * k, r * T * k, (c + 1) * T * k - 1, (r + 1) * T * k - 1], fill=col)
    for door in room['doors']:
        d.rectangle([door['col'] * T * k - 1, door['row'] * T * k - 1, (door['col'] + 1) * T * k, (door['row'] + 1) * T * k], outline=(255, 255, 255), width=2)
    for sp in room['spawns']:
        x, y = sp['x'] * k, sp['y'] * k
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 80, 80)); d.text((x + 4, y - 6), sp['type'][:2], fill=(255, 255, 255))
    im.save(path)


def verify(state_loader, room):
    """Drop Kirby above each column (logged writes) and compare with the map."""
    W, H = room['width'], room['height']; rows = []
    for c in range(W):
        x = c * T + T // 2
        s, writes = state_loader()
        s.lib.kss_bwram.restype = ctypes.POINTER(ctypes.c_uint8); ram = s.lib.kss_bwram(); hp = s.word(0x137C)
        for off, val in ((0x894, x), (0x988, x), (0x90E, DROP_Y), (0xA02, DROP_Y), (0xB70, 0), (0xBEA, 0)):
            ram[off] = val & 255; ram[off + 1] = val >> 8
        writes.append({'drop_x': x, 'y': 40, 'note': 'Kirby x/y and velocity, logged test drop'})
        s.step(n=80); rx, ry, hurt = s.word(0x988), s.word(0xA02), s.word(0x137C) != hp; s.close()
        col = [room['class'][r][rx // T] if 0 <= rx // T < W else 'empty' for r in range(H)]
        first = next((r for r in range(DROP_Y // T, H) if col[r] in ('solid', 'slope', 'platform', 'block')), None)   # below the drop point
        if col[DROP_Y // T] in ('solid', 'block'): verdict = 'skip (drop point inside a wall)'
        elif hurt or abs(rx - x) > 12: verdict = 'skip (pushed or hurt)'
        elif first is None: verdict = 'ok-pit' if ry > H * T else 'MISMATCH (map pit, Kirby stood)'
        elif col[first] in ('solid', 'platform', 'block'):
            verdict = f'ok-{col[first]}' if ry + KIRBY_FOOT == first * T else 'MISMATCH'
        else: verdict = 'ok-slope' if first * T <= ry + KIRBY_FOOT < (first + 1) * T else 'MISMATCH (slope)'
        rows.append({'col': c, 'x': x, 'rest_x': rx, 'rest_y': ry, 'map_floor_row': first,
                     'map_class': col[first] if first is not None else 'pit', 'verdict': verdict})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('checkpoint'); ap.add_argument('--route'); ap.add_argument('--name'); ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()
    build = (HERE / '../../kss-deuce/build').resolve()
    side = json.loads((S.CHECK / f'{a.checkpoint}.json').read_text())
    if side['identity'] != S.identity(build): raise SystemExit(f'checkpoint {a.checkpoint} is stale: rebuild it from its route')
    tape = json.loads(Path(a.route).read_text())['tape'] if a.route else []
    def load():
        s = S.Session(build, mods=False); s.load_state(S.CHECK / f'{a.checkpoint}.state')
        for n, p1, p2 in tape: s.step(p1, p2, n)
        if tape:      # wait for the load itself: Kirby vanishes and comes back (doors, warps)
            gone = False
            for _ in range(1200):
                s.step(); kt = s.word(0x23E)
                if kt == 0xFFFF: gone = True
                elif gone and kt == 1: break
            s.step(n=60)  # the room settles
        return s, []
    s, _ = load(); room = capture(s)
    k = room['key']; name = a.name or f"s{k['subgame']}-l{k['level']}-r{k['room']}"
    out = HERE / 'out-rooms'; out.mkdir(exist_ok=True)
    settled = out / f'{name}.state'; s.save_state(settled); s.close()     # local only (*.state is git-ignored)
    def reload():
        s = S.Session(build, mods=False); s.load_state(settled); return s, []
    if a.verify:
        room['verify'] = verify(reload, room)
        bad = [v for v in room['verify'] if v['verdict'].startswith('MISMATCH')]
        room['verify_summary'] = {v: sum(1 for r in room['verify'] if r['verdict'] == v) for v in {r['verdict'] for r in room['verify']}}
        room['verify_summary']['mismatches'] = len(bad)
    (out / f'{name}.json').write_text(json.dumps(room, indent=1) + '\n'); render(room, out / f'{name}.png')
    print(json.dumps({'room': name, 'size': [room['width'], room['height']], 'doors': room['doors'], 'spawns': len(room['spawns']),
                      'unclassified': room['unclassified_behaviors'], 'verify': room.get('verify_summary')}))
    return 1 if a.verify and room['verify_summary']['mismatches'] else 0


if __name__ == '__main__':
    sys.exit(main())
