# Sound CLI A1–A3 contracts

- `sound NAME`, `sound list`, `sound test`, `sound --event ... --source ...`, `sound --resolve` unchanged.
- `sound status [--json]` read-only and silent; JSON: `muted`, `runtime_muted`, `legacy_codex_muted`.
- `sound mute|unmute|toggle [--json]`: runtime-only mute, with lock-serialized toggle. The mute marker is `/run/user/<uid>/gway-sound/gpio-muted` (or configured `GWAY_SOUND_GPIO_MUTE_FILE`).
- `gway-lcd-sound mute toggle [--status]` and `gway-toggle-gpio-sound-mute [--status]` remain supported and use the same runtime marker.
- Sound is **enabled after reboot**, because the runtime marker is removed. The historical persistent Codex `silent` marker is reported for diagnostics but is no longer an effective mute source.
- State-changing CLI calls preserve the legacy LCD notification and event audit log; status is read-only.
- The installer **does not install or replace** `~/.local/bin/sound`. A separate, explicitly approved ownership migration is required before the new `sound` CLI can be activated on gway-001.
- Tests must cover CLI entrypoints, LCD notification, concurrent toggles, legacy markers and reboot simulation. No deployment in PR #53.

## gway-001 ownership audit (read-only)
`~/.local/bin/sound -> /usr/local/bin/sound -> /usr/local/libexec/gway-home-tools/sound.sh`.
Current `gway-lcd-sound/current` points at release `4a908110fc31`.
The release installer must not replace this externally owned symlink. Before deployment, plan a separate approved migration of producers and the absolute `/usr/local/bin/sound` entrypoint; verify checksums/rollback and do not assume a new `~/.local/bin/sound` link takes precedence for all producers.
