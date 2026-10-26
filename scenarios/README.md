# Named scenarios (developer-only)

`scenario.py` starts the native game at an exact saved moment, plays an input tape, checks assertions, writes a report and stops. It is meant to replace replaying the whole game to test one moment. A scripted controller or an external AI agent drives the same thing. Nothing here ships with the game, and it never reads or writes battery saves.

```sh
/usr/bin/python3 scenario.py list
/usr/bin/python3 scenario.py run green-deuce-coop-throw wick-helper-death-synthetic
/usr/bin/python3 scenario.py repeat green-deuce-coop-throw      # same trajectory twice?
/usr/bin/python3 scenario.py build-checkpoint green-deuce-created
/usr/bin/python3 tests/scenario_selftest.py                     # runner acceptance (16 cases)
```

Exit codes: 0 pass, 1 an assertion failed, 2 invalid setup (rejected before anything is restored), 3 timeout, 4 harness error. Reports, captures and the replayable tape go to `scenarios/out/<time>/<id>/`.

## Checkpoints: natural only
A checkpoint is `checkpoints/NAME.state` plus a `NAME.json` sidecar. It is rebuilt from power-on by replaying `NAME.route.json`, a recorded pad-input tape with no memory writes (`tools/record_routes.py` records new routes). The sidecar binds the state to SHA-256 identities: the ROM, the expansion `.kx`, `snes_runtime.c`, `libkssmod.dylib`, and the installed mods (`mods.list` plus every listed mod's files). Change any of them and `run` refuses with the exact field, so you rebuild the checkpoint from its route. Never relabel an old state.

| Checkpoint | Reached by | Frames |
|---|---|---|
| `green-deuce-created` | power-on → Beam → dial to Jackpot → A (Deuce, form 2) | 2391 |
| `green-wick-created` | power-on → Beam → dial to Candle → A (Wick, form 3) | 2469 |

## Scenarios
A scenario file (`scenarios/ID.json`, schema 1) contains:
- the checkpoint and `provenance`;
- `preconditions`;
- `input`: rows of `[frames, P1 buttons, P2 buttons]`;
- optional `setup_writes`. These are allowlisted (helper or Kirby HP only), and each is logged with its before and after values and the frame. Any write makes the run **synthetic**.
- `limits`: `max_frames` and `wall_seconds`; `max_frames` must be larger than the tape;
- `captures` (frame numbers);
- `assertions`, each with a field, an operator, and a `when` of `ever`, `always` or `end`.

Fields are allowlisted: `kirby_ability`, `kirby_tag`, `kirby_hp`, `helper_type`, `helper_ability`, `helper_hp`, `helper_x`, `helper_y`, `helper_pose`, `helper_form`, `helper_gen`, `helper_magic`, `helper_shot_count`, `helper_shot_forms`.

| Scenario | Provenance | What it proves |
|---|---|---|
| `green-deuce-coop-throw` | natural | P2 joins and throws a Deuce card; the helper stays Deuce while Kirby's dial moves; no other form's shots |
| `wick-helper-death-synthetic` | synthetic (helper HP 1) | a natural enemy hit kills Wick; the slot frees (frame 882) and the form drops to native (883) |

## For an AI playtester
Use `scenario.Session` directly, one per process:

```python
import scenario as S
s = S.Session(S.HERE / '../../kss-deuce/build')             # mods + expansion on
s.load_state(S.CHECK / 'green-wick-created.state')           # check identity first, as run_one does
obs = s.observe()                                            # allowlisted fields + helper shots
s.step(S.buttons(['RIGHT']), S.buttons(['Y']), n=3)          # P1, P2 pads; every frame is taped
s.capture('frame.png'); s.save_tape('tape.json')             # the tape replays the session exactly
```

Label a run "pixels-only" or "state-assisted" according to what the agent actually looked at. An agent's discovered failure becomes a regression by turning its saved tape into a scenario's `input`. The game's own helper AI is part of what's under test, not the tester: say in each scenario whether P2 is idle or driven.
