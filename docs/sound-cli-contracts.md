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

## Explicit user-link migration (not part of install)

`scripts/deploy/migrate-sound-command.sh inspect|adopt|verify|rollback` provides a separate opt-in migration for `~/.local/bin/sound` only. Adoption requires the existing symlink to point at `/usr/local/bin/sound`, checks the new release executable, records the original destination in a private manifest and atomically replaces the user-level link. Repeated adoption is idempotent; rollback atomically restores the original user-level symlink and refuses unexpected edits. The script never writes `/usr/local/bin/sound` or `/usr/local/libexec/gway-home-tools/sound.sh`.

**Activation caveat:** absolute callers of `/usr/local/bin/sound` remain on the original implementation. Before production activation, audit every consumer and ensure feature parity; the migration script must be run only with explicit separate authorization. Normal install, verify, rollback and CI never call it.
