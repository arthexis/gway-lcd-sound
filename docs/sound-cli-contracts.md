# Sound CLI A1–A3 contracts

## Existing interfaces
- `sound NAME`, `sound list`, `sound test`, `sound --event ... --source ...`, `sound --resolve` remain unchanged.
- `gway-lcd-sound mute toggle [--status]` delegates to the legacy GPIO mute helper.
- LCD lockfile services, hotplug and runner hooks remain unchanged.

## New interface
- `sound status [--json]`: read-only, never plays sound or creates state.
- `sound mute [--json]`: idempotently set persistent mute.
- `sound unmute [--json]`: idempotently clear persistent and legacy mute markers.
- `sound toggle [--json]`: serialize toggles with flock and invert effective mute state.

JSON status fields: `muted`, `persistent_muted`, `legacy_gpio_muted`, `legacy_codex_muted`.
Persistent marker defaults to `~/.local/state/gway-sound/muted`, override with `GWAY_SOUND_MUTE_STATE_FILE`.
No hardware changes are needed for state/status operations.

## Compatibility caveat before deployment
The legacy `gway-toggle-gpio-sound-mute` still modifies its runtime marker independently. Its behavior must be unified with the persistent state controller before field activation. The installed standalone `sound` binary is not managed by the existing release installer, so its ownership and activation must be audited before rollout.
