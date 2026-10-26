"""Room-inspector regression: three Green Greens rooms must match native physics.

/usr/bin/python3 tests/room_inspector_check.py
Rooms 1 (checkpoint), 2 (room-1 door) and 3 (Warp Star). For each: the map
must predict every Kirby drop (0 mismatches), every door tile must have the
door-star spawn (type 0x72) on it, and no behavior may be unclassified.
"""
import json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
ROOMS = [('s0-l0-r1', []), ('s0-l0-r2', ['--route', 'scenarios/routes/green-room1-door-room2.json']),
         ('s0-l0-r3', ['--route', 'scenarios/routes/green-room1-warp-star.json'])]
rows = []
for name, extra in ROOMS:
    r = subprocess.run([sys.executable, str(HERE / 'tools/room_inspector.py'), 'green-pip-created', '--verify', '--name', name] + extra,
                       cwd=HERE, capture_output=True, text=True)
    assert r.returncode == 0, (name, r.stdout[-400:], r.stderr[-400:])
    room = json.loads((HERE / 'out-rooms' / f'{name}.json').read_text())
    assert room['verify_summary']['mismatches'] == 0 and not room['unclassified_behaviors'], name
    ok = sum(v for k, v in room['verify_summary'].items() if k.startswith('ok-'))
    for d in room['doors']:
        assert any(sp['type'].startswith('72') and abs(sp['x'] - d['x']) <= 12 for sp in room['spawns']), (name, d)
    rows.append({'room': name, 'size': [room['width'], room['height']], 'drops_agreeing': ok, 'doors': len(room['doors'])})
    print('PASS', json.dumps(rows[-1]))
print(json.dumps({'passed': True, 'rooms': len(rows)}))
