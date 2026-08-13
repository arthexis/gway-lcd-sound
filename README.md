# GWAY LCD and Sound

Host-local LCD, event-sound, and GPIO/audio alert helpers for GWAY boxes.

This repository intentionally keeps these Raspberry Pi field-node features out
of the Arthexis application repository. The scripts still read a few historical
Arthexis lock paths for compatibility with deployed producers, but the runtime
surface belongs to GWAY.

## Contents

- `scripts/gway/`: standalone Python and Bash helpers for LCD rotation,
  LCD summaries, eth0 node display, event-sound polling, hotplug sounds,
  sound playback, and GPIO mute control.
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
bash -n scripts/gway/codex-sound-hook scripts/gway/gway-event-sound-hotplug scripts/gway/gway-toggle-gpio-sound-mute scripts/gway/sound.sh
python3 -m py_compile scripts/gway/*.py
```

Do not commit state from `/home/arthe/.local/state`, `/run`, recordings,
generated summaries, or local service drop-ins containing machine-specific
values.
