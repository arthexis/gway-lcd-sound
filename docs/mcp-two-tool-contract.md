# Federated MCP contract — LCD/Sound (A2)

Node owns the catalog; Watchtower forwards without maintaining a second allowlist. Exactly two public tools: `lcd` and `sound` (provider prefix may be applied by the existing federation transport).

| Tool | action | Scope | Parameters |
|---|---|---|---|
| lcd | status | gway:remote | none |
| lcd | show | gway:execute | line1 (1..160 printable), line2 (0..160), seconds (1..300) |
| lcd | clear | gway:execute | none |
| sound | status | gway:remote | json=true |
| sound | play | gway:execute | name (enumerated sound cue, not shell) |
| sound | mute / unmute / toggle | gway:execute | none |

Strictly reject unknown actions, extra parameters, control characters, arbitrary shell strings and unapproved paths. Dispatch only to the release-owned executables with argument arrays (never shell interpolation). Errors must retain exit status and structured output; read-only operations must have no sound or LCD side effects. Tests must exercise unauthorized writes, unknown operations, read/write parity and catalog count (two tools, not a fixed count of all federated tools).

The historical `/usr/local/bin/sound` and `~/.local/bin/sound` ownership remains unchanged until a separately approved migration. Direct CLI `lcd` may be installed only after a collision audit. No provider manifest is published by A1, and no production node is changed.

## Current fail-closed implementation

`lcd_sound_mcp.py` advertises exactly two tools and validates command arrays. Because each tool mixes read and write actions, tool-level `readOnlyHint` cannot express per-action OAuth requirements. The provider deliberately rejects every `tools/call` over stdio until an authenticated, trusted action-scope envelope or gateway action-policy integration exists. The `execute()` function enforces scopes for trusted internal calls and is tested offline; it is not reachable through stdio. Do not register or deploy this provider yet. The `lcd` direct wrapper exists in source but is not installed as a link. Historical `sound` remains externally owned.

## Verified gateway contract (2026-11-08)

`arthexis/gway-remote/gway_remote/mcp_tool_scope.py` classifies an **entire tool** as read only when `annotations.readOnlyHint=true`; otherwise execute. `mcp_federated_catalog.catalog_from_nodes` stores one required scope per tool, and `route_provider_call` checks that scope before forwarding. Therefore no existing gateway API can safely enforce `status` as read and `show/play` as execute *inside the same tool*.

**Integration prerequisite:** introduce an audited, node-declared per-action scope policy in gway-remote (or a trusted gateway-side classifier bound to provider revision). Validate action against the provider schema **before** dispatch; do not accept scope claims in client arguments. Pass only the gateway-authenticated scope over the existing trusted transport, and enforce the action-specific scope again on the node. Until then this prototype intentionally denies stdio tools/call and must not be registered. A tool-level execute-only policy would be secure but would make `status` unavailable to read-only users, violating the agreed contract.
