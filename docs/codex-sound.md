# Codex lifecycle sounds (optional)

LCD Sound owns the playback and event adapters; Agent Ops is not involved.

The installed `~/.local/bin/codex-lifecycle-sound EVENT` accepts:
`SessionStart`, `UserPromptSubmit`, `PermissionRequest`, `PreCompact`,
`PostCompact`, `SubagentStart`, `SubagentStop`, and `Stop`.
It forwards to `sound --event EVENT --source codex`, retaining the
existing SQLite mappings and Codex motif cooldown.

The adapter is best effort: missing sound binary, failed playback and timeout
do not interrupt Codex. Override the executable with `GWAY_CODEX_SOUND_BIN`
for testing. It does not modify `~/.codex/config.toml`.

Preview without playing audio:

```sh
sound --resolve --event PermissionRequest --source codex
sound --event SessionStart --source codex --dry-run
bash scripts/deploy/install.sh verify --no-restart
```

**Codex configuration:** Only register a hook after verifying that the
installed Codex version supports that lifecycle event and its hook command
arguments. The adapter requires one event-name argument; if the host invokes
no-argument commands, a separate release-owned wrapper is required.
Do not copy unmanaged `codex-hook-*` or mode wrappers into `~/.local/bin`.
No automatic config mutation is performed.

To disable notifications, remove the optional hook registrations from
`~/.codex/config.toml`; LCD Sound's existing mute/disable settings continue
to apply. To restore a previous installed release use
`bash scripts/deploy/install.sh rollback`.
Physical GPIO preview and acceptance are separate manual steps.
