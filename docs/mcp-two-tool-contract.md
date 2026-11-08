# MCP federation contract: two execute-only tools

The node exposes exactly two MCP tools, `lcd` and `sound`. Both declare `annotations.readOnlyHint: false`. The existing gway-remote gateway classifies each entire tool as execute-required and enforces authenticated `gway:execute` before forwarding through the authenticated node transport. All actions, including `status`, require execute permission. No action-specific scope extension or change to gway-remote is required.

## Actions

- `lcd`: `status`, `show(line1, line2?, seconds?)`, `clear`. Overlay is bounded to 1–300 seconds and uses only its owned lockfile.
- `sound`: `status`, `play(name)`, `mute`, `unmute`, `toggle`. Named cues are an enumerated allowlist.

The provider validates arguments, rejects unknown keys and actions, invokes the release-owned CLI via argument arrays (no shell interpolation), and does not trust scopes supplied by MCP arguments. **Security boundary:** the stdio provider is only safe when launched by the existing trusted node-owned MCP relay; it must not be exposed directly to unauthenticated clients. The relay and gateway enforce authorization before the provider receives a call. Do not advertise this provider outside the authenticated federation.

## Deployment gates

The provider is source-only in this PR: no root-owned manifest is published. Before enabling, verify the installed release executable, root-owned manifest pinned to an immutable SHA, node relay execute-scope checks, gateway routing scope classification, and positive/negative end-to-end tests. Historical `/usr/local/bin/sound` and `~/.local/bin/sound` belong to gway-home-tools and must not be overwritten. Direct `lcd` wrapper is present but not installed.

## Opt-in full-SHA release and manifest publication

Two separate Ansible playbooks exist; neither is included in the default installer/deploy script:

1. `ansible/playbooks/stage-mcp-release.yml` runs as the non-root node owner with `lcd_sound_revision=<full 40-hex SHA>`. It invokes `scripts/deploy/install-mcp-release.py`, archives the committed `scripts/gway` tree (including `sound_engine` and `lcd_engine` dependencies), validates the pinned entrypoints, computes a complete-file digest, and atomically renames staging to `mcp-releases/<SHA>`. Re-running an intact release is a no-op; a changed release is rejected. A failure before promotion leaves the previous release intact.

2. `ansible/playbooks/publish-mcp.yml` runs separately as root with the same SHA. It verifies a pinned executable `lcd-sound-mcp`, rejects symlinked manifest and registry paths, atomically publishes the root-owned `/etc/gway-mcp-providers/lcd_sound.json`, reads it back and restores the previous manifest (or removes the new one) on verification failure.

The existing default installer uses short SHA releases and is deliberately unchanged. The historical `sound` symlinks are not touched. **Neither playbook has been run against a node.** Execute-only authorization is enforced by the existing authenticated federation before dispatch, not by client-provided MCP parameters.

Offline tests exercise release idempotence, modified-release rejection, SHA mismatch, staging failure, runtime dependencies and manifest publication contract. Full live authorization negative tests and current-head CI are required before deployment or merge.
