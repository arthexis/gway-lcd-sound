# M4 validation and field acceptance

M4 has one source PR, but **GitHub CI cannot establish live Gway-001 state**.
Use the M3 cutover procedure at `docs/operations/gway/m3-field-cutover.md`.
Do not mark the host migration complete until field evidence is attached.

## Automated acceptance

- Dispatcher help, invalid arguments, monitor help, mute status, notification help.
- Installer clean install, verification, release switch and rollback.
- Stale regular-file helpers remain untouched and produce diagnostics.
- Broken/divergent command links are detected and repaired.
- Staging and partial activation errors do not publish a new `current` pointer.
- CI does not exercise GPIO, I²C, udev, live notifications or system services.

## Remote integration acceptance

Use the **existing** Gway Remote LCD Sound deploy workflow, not a new job.
For the selected repository SHA, record the attempted SHA, installed release
SHA, installer result and the output of:

```bash
bash scripts/deploy/install.sh verify
readlink -f /home/arthe/.local/share/gway-lcd-sound/current
readlink -f /home/arthe/.local/bin/gway-lcd-sound
/home/arthe/.local/bin/gway-lcd-sound --help
```

A healthy status must not be inferred from installer exit code alone: an absent
or divergent dispatcher link, missing active release, or SHA mismatch is an
unhealthy installation. Validate Remote's actual diagnosis against these
conditions before claiming Remote integration complete. No new deployment
trigger or workflow is required.

## Field evidence to attach

Record host, UTC timestamp, active SHA, prior helper paths/modes/checksums,
backup location, effective monitor/hotplug ExecStart values, service status,
consumer audit, physical LCD and hotplug/audio observations, and operator
approval for privileged changes. Retire a legacy helper only when its
remaining consumer count is zero. Keep `/usr/local/bin/sound` and Codex
hooks outside this migration.

**M4 is not field-complete until this evidence exists.**
