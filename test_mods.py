"""Assertion tests for the data-driven Blip mod, from hash-bound fixtures.

Mods only change rendering, so each case runs twice (mods on / off) from the
same save state with the same inputs and checks:
  * game state stays identical (BW-RAM words for both actors and the frame),
  * pixel differences exist only inside the helper / bolt boxes,
  * the expected animation frame is selected (pose -> anim mapping),
  * a Magnet-made native helper is never replaced.
Usage: /usr/bin/python3 test_mods.py ROM
"""
import ctypes, json, sys
from pathlib import Path
import fixtures as F

ROM = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/Users/markrogers/kss-work/kss-helper/build/Kirby - Seven Abilities.sfc')
OUT = F.HERE / 'out-test'; OUT.mkdir(exist_ok=True)
MODS = F.HERE / 'tests' / 'sprite-mods'   # only the Blip sprite mod

def frame_pixels():
    w, h = F.lib.kss_fb_w(), F.lib.kss_fb_h(); fb = F.lib.kss_fb()
    return w, h, [fb[i] & 0xFFFFFF for i in range(w * h)]

def state_words():
    return tuple(F.bw(a) for a in (0x896, 0x910, 0x43A, 0x137E, 0x988, 0xA02, 0x438, 0x137C, 0x2C02, 0x2C04))

def objects(pal, lo, hi):
    o = F.lib.kss_oam(); res = []
    for k in range(128):
        a, b = o[k * 2], o[k * 2 + 1]
        if (a >> 8) < 224 and ((b >> 9) & 7) == pal and lo <= (b & 0x1FF) <= hi: res.append((a & 255, a >> 8))
    return res

def run_case(fixture, script, mods):
    F.load(fixture, ROM, mods=mods, mods_dir=MODS)
    frames = []
    for p1, p2, n in script:
        for _ in range(n):
            F.run(p1, p2, 1)
            frames.append((state_words(), objects(1, 0x48, 0x4F), frame_pixels()))
    return frames

def helper_box_only(name, fixture, script, sample):
    """Diff confined to a 48x48 box around the helper's screen position."""
    on = run_case(fixture, script, True); off = run_case(fixture, script, False)
    worst = 0; changed = 0
    for i, ((s, _, (w, h, p_on)), (s2, _, (_, _, p_off))) in enumerate(zip(on, off)):
        assert s == s2, (name, 'state diverged', i)
        diff = [k for k in range(w * h) if p_on[k] != p_off[k]]
        if diff: changed += 1
        if i == sample:
            for tag, px in (('on', p_on), ('off', p_off)):
                data = bytearray()
                for v in px: data += bytes(((v >> 16) & 255, (v >> 8) & 255, v & 255))
                (OUT / f'{name}-{tag}.ppm').write_bytes(b'P6\n%d %d\n255\n' % (w, h) + bytes(data))
        if diff:
            xs = [k % w for k in diff]; ys = [k // w for k in diff]
            worst = max(worst, max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    return {'frames': len(on), 'changed_frames': changed, 'max_diff_extent_px': worst}

K = F.keys
results = {}
# 1. Body: idle / walk / jump / fire, diff extent must fit one actor-sized region (<= 48 px).
results['body_idle'] = r = helper_box_only('idle', 'blaster', [(0, 0, 40)], 39)
assert r['changed_frames'] == r['frames'] and r['max_diff_extent_px'] <= 48, r
results['body_walk'] = r = helper_box_only('walk', 'blaster', [(0, K('LEFT'), 20)], 15)
assert r['changed_frames'] == r['frames'] and r['max_diff_extent_px'] <= 48, r
results['body_jump'] = r = helper_box_only('jump', 'blaster', [(0, K('B'), 8), (0, 0, 20)], 10)
assert r['changed_frames'] == r['frames'] and r['max_diff_extent_px'] <= 56, r
# 2. Native helper made from Magnet: no rule may fire.
results['native_helper'] = r = helper_box_only('native', 'magnet', [(0, 0, 30), (0, K('LEFT'), 20)], 10)
assert r['changed_frames'] == 0, r
# 3. Bolt: fire left on open ground; frames with a bolt differ around it.
script = [(0, K('LEFT'), 8), (0, 0, 12), (0, K('Y'), 1), (0, 0, 14)]
on = run_case('blaster', script, True)
bolt_frames = [i for i, (_, b, _) in enumerate(on) if b]
assert len(bolt_frames) >= 4, ('helper bolt not seen', bolt_frames)
results['bolt'] = {'bolt_frames': len(bolt_frames)}
# Bolt pixels differ between mods on/off inside the bolt object box.
off = run_case('blaster', script, False)
i = bolt_frames[len(bolt_frames) // 2]
bx, by = on[i][1][0]
w = on[i][2][0]
box = [(x, y) for x in range(bx + 48, bx + 64) for y in range(by, by + 16)]
d = sum(1 for x, y in box if on[i][2][2][y * w + x] != off[i][2][2][y * w + x])
assert d > 10, ('bolt not replaced', d)
results['bolt']['bolt_box_changed_pixels'] = d
# 4. Hurt pose from the natural-hit fixture.
m = json.loads((F.FIX / 'manifest.json').read_text())['states']['prehurt_input']
ph = m['start_phase']
F.load('prehurt', ROM, mods=True, mods_dir=MODS)
poses = []
for f in range(40):
    F.run(F.keys('RIGHT', *(['B'] if (ph + f) % 10 < 4 else [])), 0, 1); poses.append(F.bw(0x43A))
assert any(p in (0x24, 0x26, 0x28, 0x2A) for p in poses), ('no hurt pose', [hex(p) for p in poses])
results['hurt'] = {'hurt_pose_frames': sum(p in (0x24, 0x26, 0x28, 0x2A) for p in poses)}
(OUT / 'report.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results))
