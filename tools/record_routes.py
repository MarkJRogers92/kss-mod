"""Record natural checkpoint routes (power-on -> checkpoint, real pad input only).

/usr/bin/python3 tools/record_routes.py
Drives the same scripted boot as fixtures.py through scenario.Session, so every
input lands on the session tape, then saves that tape as
scenarios/checkpoints/NAME.route.json. `scenario.py build-checkpoint NAME`
replays only the tape. No memory writes are made.
"""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import scenario as S
BUILD = '../../kss-deuce/build'
K = S.buttons

def boot_to_beam(s):
    for _ in range(11): s.step(n=110); s.step(K(['START']), n=8)
    s.step(n=120)
    for _ in range(6):
        s.step(K(['RIGHT']), n=30); s.step(K(['Y']), n=90); s.step(n=20); s.step(K(['DOWN']), n=2); s.step(n=120)
        if s.word(0x149F) == 2: break
    assert s.word(0x149F) == 2; s.step(K(['LEFT']), n=30); s.step(n=10)

def helper_from(s, tag):
    for _ in range(9):
        if s.word(0x2802) == tag: break
        s.step(K(['SELECT', 'LEFT' if tag == 7 else 'RIGHT']), n=2); s.step(n=24)
    assert s.word(0x2802) == tag; s.step(K(['A'])); s.step(n=120)

ROUTES = {  # name: (Kirby dial tag, expected observations at the checkpoint)
    'green-deuce-created': (7, {'helper_form': 2, 'kirby_ability': 0}),
    'green-wick-created': (4, {'helper_form': 3, 'kirby_ability': 0}),
    'green-pip-created': (5, {'helper_form': 4, 'kirby_ability': 0}),
    'green-blaster-created': (1, {'helper_form': 1, 'kirby_ability': 0}),
    'green-chewy-created': (3, {'helper_form': 5, 'kirby_ability': 0}),
    'green-bolt-created': (2, {'helper_form': 6, 'kirby_ability': 0}),
    'green-knotty-created': (6, {'helper_form': 7, 'kirby_ability': 0}),
}
for name, (tag, expect) in ROUTES.items():
    s = S.Session((HERE / BUILD).resolve(), mods=False)
    boot_to_beam(s); helper_from(s, tag); obs = s.observe()
    assert all(obs[k] == v for k, v in expect.items()), (name, obs)
    route = {'schema': S.SCHEMA, 'name': name, 'build': BUILD, 'expansion': True, 'expect': expect,
             'note': 'Power-on to helper creation with ordinary pad input; recorded by tools/record_routes.py',
             'route': s.tape}
    (S.CHECK / f'{name}.route.json').write_text(json.dumps(route) + '\n'); s.close()
    print(name, 'frames', sum(r[0] for r in s.tape), 'tape rows', len(s.tape))
