# Sound CLI A1–A3 contracts

- `sound NAME`, `sound list`, `sound test`, `sound --event ... --source ...`, `sound --resolve` unchanged.
- `sound status [--json]` read-only and silent; JSON: `muted`, `runtime_muted`, `legacy_codex_muted`.
- `sound mute|unmute|toggle [--json]`: runtime-only mute, with lock-serialized toggle. The mute marker is `/run/user/<uid>/gway-sound/gpio-muted` (or configured `GWAY_SOUND_GPIO_MUTE_FILE`).
- `gway-lcd-sound mute toggle [--status]` and `gway-toggle-gpio-sound-mute [--status]` remain supported and use the same runtime marker.
- Sound is **enabled after reboot**, because the runtime marker is removed. The historical persistent Codex `silent` marker is reported for diagnostics but is no longer an effective mute source.
- State-changing CLI calls preserve the legacy LCD notification and event audit log; status is read-only.
- The installer refuses to overwrite an unmanaged `~/.local/bin/sound`. A deliberate ownership migration is required before field deployment.
- Tests must cover CLI entrypoints, LCD notification, concurrent toggles, legacy markers and reboot simulation. No deployment in PR #53.
