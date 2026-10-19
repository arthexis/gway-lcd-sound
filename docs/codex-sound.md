# Codex lifecycle sounds

Codex CLI 0.163.0 supports eight lifecycle events. LCD Sound's existing
`sound --event EVENT --source codex` is the only playback interface.
No Codex-specific executables or Agent Ops dependency are required.

Codex command hooks receive event JSON on stdin, **not** an appended
event-name argument. Configure each event with a static command that names
its event. The following is a reviewable **command mapping**, not a complete
Codex configuration file (the exact hooks schema must be validated against
the installed Codex before activation):

| Codex event | Command |
| --- | --- |
| SessionStart | `/usr/local/bin/sound --event SessionStart --source codex` |
| UserPromptSubmit | `/usr/local/bin/sound --event UserPromptSubmit --source codex` |
| PermissionRequest | `/usr/local/bin/sound --event PermissionRequest --source codex` |
| PreCompact | `/usr/local/bin/sound --event PreCompact --source codex` |
| PostCompact | `/usr/local/bin/sound --event PostCompact --source codex` |
| SubagentStart | `/usr/local/bin/sound --event SubagentStart --source codex` |
| SubagentStop | `/usr/local/bin/sound --event SubagentStop --source codex` |
| Stop | `/usr/local/bin/sound --event Stop --source codex` |

The `/usr/local/bin/sound` path must point to the active LCD Sound release.
No installer changes `~/.codex/config.toml` or enables hooks. Existing
Codex hook trust/review applies. See #30 for the Gway-001 local contract
inspection and physical acceptance. Do not create unmanaged `codex-hook-*`
wrappers.

Hardware-free preview:

```sh
sound --resolve --event SessionStart --source codex
sound --resolve --event PermissionRequest --source codex
sound --event Stop --source codex --dry-run
```

Mute, event mapping, source motifs, cooldown, locking and playback error
behavior are inherited from the shared `sound` engine. A release rollback
uses `bash scripts/deploy/install.sh rollback`; Codex hook configuration
remains operator-managed. Physical audio preview requires separate approval.
