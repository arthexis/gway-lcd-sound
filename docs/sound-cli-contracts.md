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
The release installer must not replace this externally owned symlink. Before deployment, plan a separate approved migration of producers and the absolute `/usr/local/bin/sound` entrypoint; verify ownership and compatibility and do not assume a new `~/.local/bin/sound` link takes precedence for all producers.

## Explicit fail-forward user-link adoption

`scripts/deploy/migrate-sound-command.sh inspect|adopt|verify` supports an opt-in, idempotent replacement of the user-level `~/.local/bin/sound` link only. It refuses unexpected ownership and never writes `/usr/local/bin/sound` or its `gway-home-tools` target. No rollback manifest or automatic restoration is maintained. Failures are fixed forward and the corrected release is revalidated. Absolute callers of `/usr/local/bin/sound` continue using the old implementation until separately migrated. Normal installation does not run adoption; host activation requires explicit authorization.

## Field consumer audit (gway-001, read-only, 2026-11-08)

Verified symlink chain: `/home/arthe/.local/bin/sound -> /usr/local/bin/sound -> /usr/local/libexec/gway-home-tools/sound.sh`.

Observed absolute-path consumers:
- `codex-sound-hook`: `CODEX_SOUND_HOOK_SOUND_BIN` defaults to `/usr/local/bin/sound`, calls named cue with `--volume`.
- `github-actions-sound-hook`: `GWAY_RUNNER_SOUND_BIN` defaults to `/usr/local/bin/sound`, calls `--event ... --source github-actions`.
- `examine`: `SOUND_PATH=/usr/local/bin/sound`, calls named cue with `--backend gpio --volume`.
- `gway-jabra-rolling-recorder`: `DEFAULT_NOISE_SOUND_COMMAND=/usr/local/libexec/gway-home-tools/sound.sh`, configurable via `JABRA_ROLLING_NOISE_SOUND_COMMAND`.

The opt-in adoption only changes the user symlink and does **not** redirect these absolute-path consumers. Their existing command implementation stays in place, preserving call-path compatibility. Both old and new sound implementations check the same GPIO runtime mute marker, but their complete behavior has not been field-tested together. Migrating these producers to the new executable is out of scope and requires separate approval. No host files were modified.
