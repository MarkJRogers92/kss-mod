"""Package six-helper kit art as native-runtime helper mods (Deuce, Wick, ...).

Usage: /usr/bin/python3 tools/make_helper_mod.py deuce|wick|all
Run with a Python that has Pillow. Writes mods/<name>/{mod.txt,body.bin,<fx>.bin};
it never touches mods/mods.list. Art comes unchanged from the six-helper ability
kit: locked baseline helper frames, the helper's throw clip, its shot effect
and the common landing/dash reactions. Bodies are 48x48 with the kit's ground
pivot [24,40]; shot effects are 16x16.

Each mod is gated on its expansion helper form (H_TAG 40:2C02), which only the
native expansion ROM sets. Pose words are the measured native helper poses Blip
uses (blip-attack-polish); 0x8A is the pose every helper ground-throw script sets.
"""
import json, sys
from pathlib import Path
from PIL import Image

KIT = Path('/Users/markrogers/kss-work/helper-art/six-helper-ability-kit-20261025')
MODS = Path(__file__).resolve().parents[1] / 'mods'

# Blip's anchor (16,17) puts the actor origin 15 px above the ground row its
# feet touch (row 32 of 32). Kit bodies touch row 40 (pivot [24,40]).
ANCHOR = (24, 40 - 15)

# Per-shot art states: the helper's shot state word (expansion W_MODE at
# 40:2F00+slot, low byte) picks the clip; see kss_mods.c 'shot_state'.
SHOT_STATE = (0x2F00, 0x00FF)
STATES = {
    'wick': [(0, 'wax_flight', 'drip'), (1, 'settled_wax', 'settle')],
    'pip': [(0, 'standing', 'stand'), (1, 'standing', 'stand'), (2, 'flight', 'fly')],
    'chewy': [(0, 'gum_blob_travel', 'travel'), (1, 'gum_stationary_slow_field', 'hold')],
    'bolt': [(0, 'magnet_orbit_metal_bolt', 'spin'), (1, 'magnet_released_metal_bolt', 'fly')],
    'knotty': [(0, 'doll_hover', 'bob'), (2, 'doll_strike', 'lunge'), (3, 'doll_strike', 'lunge')],
}

HELPERS = {
    # mod name: kit key, helper form, title, throw clip, (fx name, fx clip, fx anim)
    'deuce': dict(key='jackpot', form=2, title='Deuce: Jackpot helper art for the expansion-ROM Deuce helper (form 2).',
                  throw='card_throw', fx=('card', 'card_flight', 'spin'),
                  fx_note='Deuce\'s own colours'),
    'wick': dict(key='candle', form=3, title='Wick: Candle helper art for the expansion-ROM Wick helper (form 3).',
                 throw='wax_throw', fx=('wax', 'wax_flight', 'drip'),
                 fx_note='Wick\'s own colours. Airborne wax drips, landed\n# wax settles (per-shot state; ignition art stays unbound)'),
    'chewy': dict(key='gum', form=5, title='Chewy: Gum helper art for the expansion-ROM Chewy helper (form 5).',
                  throw='gum_spit', fx=('field', 'gum_stationary_slow_field', 'hold'),
                  fx_note='Chewy\'s own colours. Sliding field = blob travel, holding\n# field = stationary field (per-shot state; bubble art stays unbound)'),
    'bolt': dict(key='magnet', form=6, title='Bolt: Magnet helper art for the expansion-ROM Bolt helper (form 6).',
                 throw='magnet_create_orbit', fx=('bolt', 'magnet_orbit_metal_bolt', 'spin'),
                 fx_note='Bolt\'s own colours. Orbiting and released bolts by\n# per-shot state (catch art stays unbound)'),
    'knotty': dict(key='puppeteer', form=7, title='Knotty: Puppeteer helper art for the expansion-ROM Knotty helper (form 7).',
                   throw='deploy', fx=('doll', 'doll_hover', 'bob'),
                   fx_note='Knotty\'s own colours. Hovering doll bobs; strike and run\n# lunge (per-shot state; return/recall art stays unbound)'),
    'pip': dict(key='domino', form=4, title='Pip: Domino helper art for the expansion-ROM Pip helper (form 4).',
                throw='tile_toss', fx=('tile', 'standing', 'stand'),
                fx_note='Pip\'s own colours. Sliding/standing tiles stand,\n# launched tiles fly (per-shot state; rank art stays unbound)'),
}


def frames(h):
    base = KIT / f"baseline/helpers/{h['key']}/frames/helper"
    abil = KIT / f"abilities/{h['key']}/frames"
    common = KIT / 'common-reactions/frames/body'
    k = h['key']
    body = {**{f'idle{i}': base / f'idle_0{i + 1}.png' for i in range(4)},
            **{f'walk{i}': base / f'walk_0{i + 1}.png' for i in range(6)},
            **{f'jump{i}': base / f'jump_0{i + 1}.png' for i in range(4)},
            **{f'attack{i}': base / f'attack_0{i + 1}.png' for i in range(6)},
            **{f'hurt{i}': base / f'hurt_0{i + 1}.png' for i in range(2)},
            **{f'throw{i}': p for i, p in enumerate(sorted(abil.glob(f"body/{h['throw']}_0*.png")))},
            'land0': common / f'{k}_landing_compress.png', 'land1': common / f'{k}_landing_recover.png',
            'land2': common / f'{k}_landing_settle.png',
            'dash0': common / f'{k}_dash_start.png', 'dash1': common / f'{k}_dash_skid.png',
            'dash2': common / f'{k}_dash_brake.png'}
    name, clip, _ = h['fx']
    fx = {}
    clips = list(dict.fromkeys([clip] + [st[1] for st in STATES.get(h['mod'], [])]))
    for k, c in enumerate(clips):
        for i, path in enumerate(sorted(abil.glob(f'fx/{c}_0*.png'))):
            fx.setdefault(f'{name}_s{k}_{i}' if c != clip else f'{name}{i}', path)
    # kss_mods.c keeps 23 characters of a frame name; longer names fail the mod.
    assert all(len(n) <= 23 for n in list(body) + list(fx)), [n for n in fx if len(n) > 23]
    return body, fx


def raw(frames, size, palette):
    blob = bytearray()
    for name, path in frames.items():
        im = Image.open(path)
        assert im.mode == 'P' and im.size == (size, size) and im.info.get('transparency') == 0, (name, im.mode, im.size)
        assert im.getpalette()[:len(palette)] == palette, (name, 'palette differs from the helper palette')
        data = bytes(im.getdata())
        assert max(data) < len(palette) // 3, (name, max(data))
        blob += data
    return bytes(blob)


def make(mod):
    h = dict(HELPERS[mod], mod=mod); out = MODS / mod
    body, fx = frames(h); fx_name, _, fx_anim = h['fx']
    # The art is the palette source: every frame must carry the same 16
    # entries (index 0 transparent), so refined PNGs bring their own colours.
    rgb = Image.open(next(iter(body.values()))).getpalette()[:48]
    words = [(rgb[i] >> 3) | (rgb[i + 1] >> 3) << 5 | (rgb[i + 2] >> 3) << 10 for i in range(3, 48, 3)]
    out.mkdir(parents=True, exist_ok=True)
    (out / 'body.bin').write_bytes(raw(body, 48, rgb))
    (out / f'{fx_name}.bin').write_bytes(raw(fx, 16, rgb))
    title = h['title'].split(':')[0]
    clip0 = h['fx'][1]
    lines = [f'anim {fx_anim} 4:{fx_name}0 4:{fx_name}1', f'play {fx_anim}']
    if mod in STATES:
        seen = {fx_anim}
        for v, c, an in STATES[mod]:
            if an in seen: continue
            k = list(dict.fromkeys([clip0] + [st[1] for st in STATES[mod]])).index(c)
            seen.add(an); names = [n for n in fx if n.startswith(f'{fx_name}_s{k}_')] if c != clip0 else [f'{fx_name}0', f'{fx_name}1']
            lines.append(f'anim {an} ' + ' '.join(f'4:{n}' for n in names))
        lines.append(f'shot_state 4 0x{SHOT_STATE[0]:04X} 0x{SHOT_STATE[1]:04X} 0x135E 0x1360   # helper-owned shot under the sprite')
        lines += [f'state {v} {an}' for v, c, an in STATES[mod]]
    fx_anims = '\n'.join(lines)
    n = sum(k.startswith('throw') for k in body)          # kit throw clips have 3 or 4 frames
    throw_anim = ' '.join(f'{d}:throw{i}' for i, d in enumerate([3, 2, 3][:n - 1] + [0]))
    live = f"""when 0x2C00 == 0x4B48      # helper form state valid (ROM hack BW-RAM)
when 0x2C02 == {h['form']}           # helper form = {title} (native expansion ROM only)
when 0x0240 in 2 3         # slot 04 is a live helper"""
    text = f"""# {h['title']}
# Generated by tools/make_helper_mod.py from helper-art/six-helper-ability-kit-20261025.

rule actor {mod}-body
{live}
match palette 2 tiles 0x20 0x3F    # native helper body objects
art body.bin 48 48 {' '.join(body)}
palette 2 {' '.join(f'{w:04X}' for w in words)}
actor 0x0896 0x0910 0x135E 0x1360 0x043A   # helper X, Y, camera X, Y, pose
anchor {ANCHOR[0]} {ANCHOR[1]}
anim idle 15:idle0 15:idle1 15:idle2 15:idle3
anim walk 6:walk0 6:walk1 6:walk2 6:walk3 6:walk4 6:walk5
anim jump 4:jump0 0:jump1
anim fall 4:jump2 0:jump3
anim attack 4:attack0 4:attack1 4:attack2 4:attack3 4:attack4 0:attack5
anim aim 0:attack0
anim hurt 4:hurt0 4:hurt1
anim land 3:land0 2:land1 0:land2
anim dash 4:dash0 3:dash1 4:dash2
anim throw {throw_anim}
pose idle 0x58 0x3A 0x5E
pose walk 0x64 0x66 0x68 0x6A
pose jump 0x6C
pose fall 0x6E 0x48
pose attack 0x86 0x88 0x8C 0x8E 0x96 0x98 0x9E
pose aim 0x90 0xA2
pose hurt 0x24 0x26 0x28 0x2A
pose land 0x36
pose dash 0x4C
pose throw 0x8A
default idle

rule object {mod}-{fx_name}
{live}
match palette 1 tiles 0x48 0x4F    # helper FX page (helper-owned shots)
art {fx_name}.bin 16 16 {' '.join(fx)}
draw_palette 2                     # {h['fx_note']}; palette 1 is never written
{fx_anims}
"""
    (out / 'mod.txt').write_text(text)
    return text
    print(json.dumps({'dir': str(out), 'body_frames': len(body), 'fx_frames': len(fx), 'anchor': ANCHOR}))


if __name__ == '__main__':
    for mod in (HELPERS if sys.argv[1:] == ['all'] else sys.argv[1:]):
        make(mod)
