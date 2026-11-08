# MCP federation contract: two execute-only tools

The node exposes exactly two MCP tools, `lcd` and `sound`. Both declare `annotations.readOnlyHint: false`. The existing gway-remote gateway classifies each entire tool as execute-required and enforces authenticated `gway:execute` before forwarding through the authenticated node transport. All actions, including `status`, require execute permission. No action-specific scope extension or change to gway-remote is required.

## Actions

- `lcd`: `status`, `show(line1, line2?, seconds?)`, `clear`. Overlay is bounded to 1–300 seconds and uses only its owned lockfile.
- `sound`: `status`, `play(name)`, `mute`, `unmute`, `toggle`. Named cues are an enumerated allowlist.

The provider validates arguments, rejects unknown keys and actions, invokes the release-owned CLI via argument arrays (no shell interpolation), and does not trust scopes supplied by MCP arguments. **Security boundary:** the stdio provider is only safe when launched by the existing trusted node-owned MCP relay; it must not be exposed directly to unauthenticated clients. The relay and gateway enforce authorization before the provider receives a call. Do not advertise this provider outside the authenticated federation.

## Deployment gates

The provider is source-only in this PR: no root-owned manifest is published. Before enabling, verify the installed release executable, root-owned manifest pinned to an immutable SHA, node relay execute-scope checks, gateway routing scope classification, and positive/negative end-to-end tests. Historical `/usr/local/bin/sound` and `~/.local/bin/sound` belong to gway-home-tools and must not be overwritten. Direct `lcd` wrapper is present but not installed.

## Opt-in publication and remaining release prerequisite

`ansible/playbooks/publish-mcp.yml` is deliberately not called by the existing install/deploy flows. It only publishes a manifest when a preinstalled `mcp-releases/<full-40-character-SHA>` release exists. The current general LCD Sound Ansible installer uses a **12-character SHA** in `releases/`, so that installer **does not satisfy** the MCP release prerequisite. A separate full-SHA immutable release staging/promotion flow and rollback/convergence tests are still required before deployment. Do not point the manifest at `current` or a short-SHA release.
