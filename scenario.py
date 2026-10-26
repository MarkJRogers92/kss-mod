"""Developer-only named-scenario runner for the native runtime (system python3).

  /usr/bin/python3 scenario.py list
  /usr/bin/python3 scenario.py build-checkpoint ID   # replay the route from power-on
  /usr/bin/python3 scenario.py run ID [ID ...]       # one fresh process per scenario
  /usr/bin/python3 scenario.py repeat ID             # run twice, compare trajectories

A scenario (scenarios/ID.json) names a checkpoint, an input tape per port,
optional logged setup writes (which make it synthetic), limits and assertions.
A checkpoint (scenarios/checkpoints/NAME.state + .json sidecar) is rebuilt from
power-on by replaying its recorded route tape, never by memory writes, and is
bound to the exact identity of everything that affects play: ROM, expansion,
runtime core, the built library and the installed mods. Any mismatch is
rejected before the state is restored. Battery saves are never read or written.

Exit codes: 0 pass, 1 assertion failure, 2 invalid setup (identity, schema,
missing checkpoint, failed precondition), 3 timeout, 4 harness error (crash).
A crash is never reported as a game failure or a pass.

For an external agent, `Session` is the observe/act surface: step(p1, p2)
records every input on the session tape, observe() returns allowlisted fields,
capture() writes a PNG, and save_tape() lets any run be replayed exactly.
"""
import ctypes, hashlib, json, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCEN = HERE / 'scenarios'
CHECK = SCEN / 'checkpoints'
OUTS = SCEN / 'out'
SCHEMA = 1
BUTTONS = {'B': 0x8000, 'Y': 0x4000, 'SELECT': 0x2000, 'START': 0x1000, 'UP': 0x0800, 'DOWN': 0x0400,
           'LEFT': 0x0200, 'RIGHT': 0x0100, 'A': 0x0080, 'X': 0x0040, 'L': 0x0020, 'R': 0x0010}
# Allowlisted observations: name -> BW-RAM word offset (from $40:0000).
FIELDS = {'frame': None, 'kirby_ability': 0x149F, 'kirby_tag': 0x2802, 'kirby_hp': 0x137C,
          'helper_type': 0x0240, 'helper_ability': 0x14A1, 'helper_hp': 0x137E, 'helper_x': 0x0896,
          'helper_y': 0x0910, 'helper_pose': 0x043A, 'helper_form': 0x2C02, 'helper_gen': 0x2C04,
          'helper_magic': 0x2C00}
IRAM_FIELDS = {'subgame': 0x32EA, 'level': 0x32EE, 'room': 0x32F2}   # SA-1 I-RAM room selectors
WRITABLE = {0x137E: 'helper HP', 0x137C: 'Kirby HP'}   # setup writes allowed by manifests


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def buttons(names): return sum(BUTTONS[n] for n in names)


def identity(build):
    """Everything that affects play or rendering, by content hash."""
    build = Path(build)
    mods = HERE / 'mods'; listed = [l.split('#')[0].strip() for l in (mods / 'mods.list').read_text().splitlines()]
    h = hashlib.sha256((mods / 'mods.list').read_bytes())
    for name in filter(None, listed):
        for f in sorted((mods / name).iterdir()): h.update(f.name.encode()); h.update(f.read_bytes())
    ident = {'rom': sha(build / 'Kirby - Seven Abilities.sfc'), 'core_source': sha(HERE / 'snes_runtime.c'),
             'library': sha(HERE / 'libkssmod.dylib'), 'mods': h.hexdigest(), 'schema': SCHEMA}
    x = build / 'Seven-Abilities.kx'
    ident['expansion'] = sha(x) if x.exists() else None
    return ident


class Session:
    """One native runtime in this process: restore, act, observe, capture."""
    def __init__(self, build, mods=True, expansion=True):
        self.build = Path(build); self.lib = lib = ctypes.CDLL(str(HERE / 'libkssmod.dylib'))
        lib.kss_read_bwram16.restype = ctypes.c_uint16; lib.kss_read_bwram16.argtypes = [ctypes.c_uint32]
        lib.kss_step.argtypes = [ctypes.c_uint16, ctypes.c_uint16]; lib.kss_fb.restype = ctypes.POINTER(ctypes.c_uint32)
        lib.kss_bwram.restype = ctypes.POINTER(ctypes.c_uint8); lib.kss_oam.restype = ctypes.POINTER(ctypes.c_uint16)
        lib.kss_load_expansion.argtypes = [ctypes.c_char_p]
        lib.kss_read_iram16.restype = ctypes.c_uint16; lib.kss_read_iram16.argtypes = [ctypes.c_uint16]
        x = self.build / 'Seven-Abilities.kx'
        assert lib.kss_load_expansion(str(x).encode() if expansion and x.exists() else None)
        assert lib.kss_open(str(self.build / 'Kirby - Seven Abilities.sfc').encode()), 'ROM load failed'
        lib.kss_mods_init(str(HERE / 'mods').encode() if mods else b'/nonexistent')
        self.tape, self.writes = [], []

    def word(self, off): return self.lib.kss_read_bwram16(off)
    def observe(self):
        return ({k: (self.lib.kss_frame() if off is None else self.word(off)) for k, off in FIELDS.items()}
                | {k: self.lib.kss_read_iram16(a) for k, a in IRAM_FIELDS.items()} | {'helper_shots': self.helper_shots()})
    def helper_shots(self):
        out = []
        for s in range(0, 0x80, 2):
            if self.word(0x23C + s) == 5 and self.word(0xE4A + s) == 4:
                out.append({'slot': s, 'x': self.word(0x986 + s), 'y': self.word(0xA00 + s), 'form': self.word(0x2D00 + s)})
        return out
    def step(self, p1=0, p2=0, n=1):
        for _ in range(n):
            self.lib.kss_step(p1, p2)
            if self.tape and self.tape[-1][1:] == [p1, p2]: self.tape[-1][0] += 1
            else: self.tape.append([1, p1, p2])
    def write(self, off, value, reason):
        assert off in WRITABLE, f'setup write to {off:#x} is not allowlisted'
        before = self.word(off); ram = self.lib.kss_bwram(); ram[off] = value & 255; ram[off + 1] = value >> 8 & 255
        self.writes.append({'addr': f'40:{off:04X}', 'width': 16, 'before': before, 'after': value,
                            'frame': self.lib.kss_frame(), 'reason': reason})
    def save_state(self, path): assert self.lib.kss_save_state(str(path).encode()), path
    def load_state(self, path): assert self.lib.kss_load_state(str(path).encode()), path
    def capture(self, path):
        from PIL import Image
        w, h = self.lib.kss_fb_w(), self.lib.kss_fb_h(); fb = self.lib.kss_fb()
        im = Image.new('RGB', (w, h)); im.putdata([((fb[i] >> 16) & 255, (fb[i] >> 8) & 255, fb[i] & 255) for i in range(w * h)])
        im.save(path)
    def save_tape(self, path): Path(path).write_text(json.dumps({'tape': self.tape}) + '\n')
    def close(self): self.lib.kss_close()


def load_json(path, kind):
    data = json.loads(Path(path).read_text())
    if data.get('schema') != SCHEMA: raise SystemExit(invalid(f'{kind} {path.name}: schema {data.get("schema")} != {SCHEMA}'))
    return data

def invalid(msg): print(json.dumps({'result': 'invalid', 'reason': msg})); return 2

def build_dir(spec): return (HERE / spec).resolve()

def tape_frames(tape):
    for row in tape:
        n, p1, p2 = row[0], buttons(row[1]) if isinstance(row[1], list) else row[1], buttons(row[2]) if isinstance(row[2], list) else row[2]
        yield n, p1, p2


def build_checkpoint(name):
    """Replay a checkpoint's route from power-on (no writes) and bind it."""
    spec = load_json(CHECK / f'{name}.route.json', 'route')
    s = Session(build_dir(spec['build']), mods=False, expansion=spec.get('expansion', True))
    for n, p1, p2 in tape_frames(spec['route']): s.step(p1, p2, n)
    obs = s.observe()
    bad = {k: (obs[k], v) for k, v in spec.get('expect', {}).items() if obs[k] != v}
    if bad: s.close(); return invalid(f'route {name} did not reach its checkpoint: {bad}')
    CHECK.mkdir(exist_ok=True); s.save_state(CHECK / f'{name}.state')
    side = {'schema': SCHEMA, 'name': name, 'provenance': 'natural', 'route': f'{name}.route.json',
            'route_sha256': sha(CHECK / f'{name}.route.json'), 'state_sha256': sha(CHECK / f'{name}.state'),
            'identity': identity(build_dir(spec['build'])), 'observed': obs}
    (CHECK / f'{name}.json').write_text(json.dumps(side, indent=2) + '\n'); s.close()
    print(json.dumps({'result': 'built', 'checkpoint': name, 'frame': obs['frame']})); return 0


def check(cond, obs):
    f = cond['field']
    v = (len(obs['helper_shots']) if f == 'helper_shot_count' else
         sorted({s['form'] for s in obs['helper_shots']}) if f == 'helper_shot_forms' else obs[f])
    ops = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a < b, '>': lambda a, b: a > b,
           '>=': lambda a, b: a >= b, '<=': lambda a, b: a <= b, 'in': lambda a, b: a in b,
           'not in': lambda a, b: a not in b, 'contains': lambda a, b: b in a}
    return ops[cond['op']](v, cond['value']), v


def run_one(sid, out_root):
    """Run one scenario in this process; returns an exit code."""
    t0 = time.time(); m = load_json(SCEN / f'{sid}.json', 'scenario')
    cp = CHECK / f"{m['checkpoint']}.json"
    if not cp.exists() or not (CHECK / f"{m['checkpoint']}.state").exists(): return invalid(f'checkpoint {m["checkpoint"]} missing: run build-checkpoint')
    side = load_json(cp, 'checkpoint'); build = build_dir(m['build'])
    now = identity(build)
    diff = {k: (side['identity'].get(k), v) for k, v in now.items() if side['identity'].get(k) != v}
    if diff: return invalid(f'identity mismatch, not restored: {sorted(diff)}')
    if sha(CHECK / f"{m['checkpoint']}.state") != side['state_sha256']: return invalid('checkpoint state hash mismatch, not restored')
    bad_writes = [w['addr'] for w in m.get('setup_writes', []) if int(w['addr'], 16) not in WRITABLE]
    if bad_writes: return invalid(f'setup writes not allowlisted, not restored: {bad_writes}')
    out = out_root / sid; out.mkdir(parents=True, exist_ok=True)
    s = Session(build, mods=m.get('mods', True), expansion=m.get('expansion', True))
    s.load_state(CHECK / f"{m['checkpoint']}.state")
    for w in m.get('setup_writes', []): s.write(int(w['addr'], 16), w['value'], w['reason'])
    provenance = 'synthetic' if s.writes or side['provenance'] != 'natural' else 'natural'
    if m.get('provenance') and m['provenance'] != provenance:
        return invalid(f"manifest says {m['provenance']} but run is {provenance}")
    obs = s.observe()
    for cond in m.get('preconditions', []):
        ok, v = check(cond, obs)
        if not ok: s.close(); return invalid(f'precondition {cond} failed (observed {v})')
    limits = m['limits']; traj = hashlib.sha256(); results = {i: None for i in range(len(m['assertions']))}
    frame, status, first_fail = 0, None, None
    for n, p1, p2 in tape_frames(m['input']):
        for _ in range(n):
            s.step(p1, p2); frame += 1; obs = s.observe()
            traj.update(json.dumps(obs, sort_keys=True).encode())
            for i, a in enumerate(m['assertions']):
                ok, v = check(a, obs); kind = a.get('when', 'ever')
                if kind == 'ever' and ok and results[i] is None: results[i] = {'pass': True, 'frame': frame, 'observed': v}
                if kind == 'always' and not ok and results[i] is None:
                    results[i] = {'pass': False, 'frame': frame, 'observed': v}; first_fail = first_fail or frame
                    s.capture(out / f'first-failure-{frame}.png')
            for f in m.get('captures', []):
                if f == frame: s.capture(out / f'frame-{frame}.png')
            if frame >= limits['max_frames'] or time.time() - t0 > limits['wall_seconds']:
                status = 'timeout'; break
        if status: break
    final = s.observe()
    for i, a in enumerate(m['assertions']):
        if results[i] is None:
            if a.get('when', 'ever') == 'always': results[i] = {'pass': True, 'frame': None, 'observed': check(a, final)[1]}
            elif a.get('when') == 'end':
                ok, v = check(a, final); results[i] = {'pass': ok, 'frame': frame, 'observed': v}
            else: results[i] = {'pass': False, 'frame': None, 'observed': check(a, final)[1]}
            if not results[i]['pass'] and first_fail is None: first_fail = frame; s.capture(out / f'first-failure-{frame}.png')
    s.capture(out / 'final.png'); s.save_tape(out / 'tape.json')
    passed = all(r['pass'] for r in results.values())
    result = status or ('pass' if passed else 'fail')
    report = {'scenario': sid, 'title': m['title'], 'result': result, 'provenance': provenance, 'identity': now,
              'checkpoint': {'name': m['checkpoint'], 'state_sha256': side['state_sha256'], 'route_sha256': side.get('route_sha256')},
              'setup_writes': s.writes, 'frames': frame, 'first_failure_frame': first_fail,
              'trajectory_sha256': traj.hexdigest(),
              'assertions': [dict(m['assertions'][i], **r) for i, r in results.items()], 'final': final}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n'); s.close()
    print(json.dumps({k: report[k] for k in ('scenario', 'result', 'provenance', 'frames', 'first_failure_frame', 'trajectory_sha256')}))
    return {'pass': 0, 'fail': 1, 'timeout': 3}[result]


def main(argv):
    cmd = argv[0] if argv else 'list'
    if cmd == 'list':
        for p in sorted(SCEN.glob('*.json')):
            m = json.loads(p.read_text()); print(f"{p.stem:28} {m.get('provenance', '?'):9} {m['title']}")
        return 0
    if cmd == 'build-checkpoint': return build_checkpoint(argv[1])
    if cmd == '_run':
        try: return run_one(argv[1], Path(argv[2]))
        except SystemExit: raise
        except Exception as e:
            print(json.dumps({'scenario': argv[1], 'result': 'error', 'reason': f'{type(e).__name__}: {e}'})); return 4
    if cmd in ('run', 'repeat'):
        ids = argv[1:] if cmd == 'run' else [argv[1], argv[1]]
        stamp = time.strftime('%Y%m%d-%H%M%S'); worst, trajs = 0, []
        for k, sid in enumerate(ids):
            out = OUTS / stamp / (f'run{k}' if cmd == 'repeat' else '')
            r = subprocess.run([sys.executable, __file__, '_run', sid, str(out)], capture_output=True, text=True)
            lines = [l for l in r.stdout.strip().splitlines() if l.startswith('{')]
            line = lines[-1] if lines else json.dumps({'scenario': sid, 'result': 'error', 'reason': (r.stderr.strip().splitlines() or ['no output'])[-1]})
            print(line); worst = max(worst, r.returncode if lines else 4)
            if cmd == 'repeat':
                try: trajs.append(json.loads(line).get('trajectory_sha256'))
                except json.JSONDecodeError: trajs.append(None)
        if cmd == 'repeat':
            same = len(set(trajs)) == 1 and trajs[0] is not None
            print(json.dumps({'repeat': argv[1], 'deterministic': same})); worst = max(worst, 0 if same else 1)
        return worst
    raise SystemExit(f'unknown command {cmd}')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
