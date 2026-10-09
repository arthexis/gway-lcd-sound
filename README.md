# GWAY LCD and Sound

Host-local LCD, event-sound, and GPIO/audio alert helpers for GWAY boxes.

This repository intentionally keeps these Raspberry Pi field-node features out
of the Arthexis application repository. The scripts still read a few historical
Arthexis lock paths for compatibility with deployed producers, but the runtime
surface belongs to GWAY.

## Contents

- `scripts/gway/`: standalone Python and Bash helpers for LCD rotation,
  LCD summaries, eth0 node display, event-sound polling, hotplug sounds,
  sound playback, GPIO mute control, and archived local media shortcuts.
- `config/systemd/gway/`: system and user service units copied from the live
  GWAY layout.
- `config/templates/`: non-secret environment templates.
- `config/udev/rules.d/`: redacted udev hotplug rule templates.
- `docs/`: operations notes and man pages.
- `tests/`: focused unit tests that do not require the physical LCD or audio
  hardware.

## Validation

```bash
PYTHONPATH=. python3 -m pytest tests
bash -n scripts/gway/codex-sound-hook scripts/gway/gway-event-sound-hotplug scripts/gway/gway-toggle-gpio-sound-mute scripts/gway/sound.sh scripts/gway/radio-play
python3 -m py_compile scripts/gway/*.py
```

Do not commit state from `/home/arthe/.local/state`, `/run`, recordings,
generated summaries, or local service drop-ins containing machine-specific
values.

## Behavioral baseline (refactor chunk 1)

The hardware-free contract suite exercises LCD formatting, rotation/event and
Actions runner lockfile priority, expiration, sound aliases, mute/disable,
playback errors, concurrent playback locking, and fake-display output.

```bash
python3 -m pip install pytest
python3 -m pytest -q tests
```

A GitHub-hosted `Behavior contracts` workflow runs this suite on PRs and
main pushes. It requires no I²C, GPIO, audio equipment or self-hosted runner.
Chunk 1 preserves all production scripts; later refactors should extend the
contracts before moving implementation code.
