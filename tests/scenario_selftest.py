"""Acceptance self-test for scenario.py (system python3).

/usr/bin/python3 tests/scenario_selftest.py
Uses temporary scenario/checkpoint copies (removed afterwards) to prove:
identity and state-hash mismatches and bad setup are rejected before restore
(exit 2); a false assertion fails (1); a frame limit inside the tape times out
(3); a harness crash is an error (4); each real scenario replays to the same
trajectory twice in fresh processes; and the frontend's battery-save folder is
untouched.
"""
import hashlib, json, shutil, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
SCEN, CHECK = HERE / 'scenarios', HERE / 'scenarios' / 'checkpoints'
SAVES = Path.home() / 'Library/Application Support/KSSNative'
PY = sys.executable

def tree_hash(d):
    h = hashlib.sha256()
    for p in sorted(d.rglob('*')) if d.exists() else []:
        if p.is_file(): h.update(str(p).encode()); h.update(p.read_bytes())
    return h.hexdigest()

def run(*args):
    r = subprocess.run([PY, str(HERE / 'scenario.py'), *args], capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith('{')]
    return r.returncode, [json.loads(l) for l in lines]

saves_before = tree_hash(SAVES); tmp = []; rows = []
def temp(path, data): path.write_text(json.dumps(data, indent=2)); tmp.append(path)
base = json.loads((SCEN / 'green-deuce-coop-throw.json').read_text())
side = json.loads((CHECK / 'green-deuce-created.json').read_text())
try:
    # Identity / state mismatches: a copied checkpoint with one field changed.
    for field in ['rom', 'expansion', 'core_source', 'library', 'mods', 'schema', 'state_sha256']:
        bad = json.loads(json.dumps(side)); name = f'_selftest-{field}'
        if field == 'state_sha256': bad['state_sha256'] = '0' * 64
        else: bad['identity'][field] = 'stale'
        temp(CHECK / f'{name}.json', bad); shutil.copy(CHECK / 'green-deuce-created.state', CHECK / f'{name}.state'); tmp.append(CHECK / f'{name}.state')
        temp(SCEN / f'{name}.json', dict(base, checkpoint=name))
        code, out = run('_run', name, str(HERE / 'scenarios/out/_selftest'))
        assert code == 2 and 'not restored' in out[-1]['reason'], (field, code, out)
        rows.append(f'rejected before restore: changed {field}')
    cases = [('_selftest-missing', dict(base, checkpoint='_nope'), 2, 'missing checkpoint'),
             ('_selftest-precondition', dict(base, preconditions=[{'field': 'helper_form', 'op': '==', 'value': 3}]), 2, 'failed precondition'),
             ('_selftest-badwrite', dict(base, setup_writes=[{'addr': '0x2C02', 'value': 3, 'reason': 'not allowed'}]), 2, 'non-allowlisted write'),
             ('_selftest-fail', dict(base, assertions=[{'name': 'impossible', 'field': 'helper_form', 'op': '==', 'value': 9, 'when': 'ever'}]), 1, 'false assertion fails'),
             ('_selftest-timeout', dict(base, limits={'max_frames': 30, 'wall_seconds': 60}), 3, 'frame limit inside the tape times out'),
             ('_selftest-crash', dict(base, assertions=[{'name': 'bad field', 'field': 'no_such_field', 'op': '==', 'value': 1}]), 4, 'harness crash is an error')]
    for name, m, want, label in cases:
        temp(SCEN / f'{name}.json', m); code, out = run('_run', name, str(HERE / 'scenarios/out/_selftest'))
        assert code == want, (label, code, out); rows.append(f'{label}: exit {code}')
    for sid in ['green-deuce-coop-throw', 'wick-helper-death-synthetic']:
        code, out = run('repeat', sid)
        assert code == 0 and out[-1]['deterministic'], (sid, out); rows.append(f'{sid}: identical trajectory on two fresh runs')
finally:
    for p in tmp: p.unlink(missing_ok=True)
    shutil.rmtree(HERE / 'scenarios/out/_selftest', ignore_errors=True)
assert tree_hash(SAVES) == saves_before, 'frontend battery saves changed'; rows.append('frontend battery-save folder unchanged')
for r in rows: print('PASS', r)
print(json.dumps({'passed': True, 'cases': len(rows)}))
