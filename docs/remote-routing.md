# Remote hardware event routing (Draft — issues #66 and gway-remote #685)

Remote routing is **not automatically enabled or production approved**.
Two Draft PRs must pass security, CI and controlled field acceptance:
- LCD/Sound PR #67
- GWay Remote PR #686

## Model

- The local `gway-lcd-sound` dispatcher reads a private, per-user route
  configuration. Without a route, it invokes the original local LCD lockfile
  control and sound.sh backend.
- `gway-lcd-sound route set gway-001` probes the central Watchtower
  enrollment and pinned SSH limits path through the *installed* GWay Remote
  bridge. It atomically saves the selected destination only after success.
- A remote command creates a short-lived structured envelope and sends it
  through `gway-remote --lcd-sound-bridge send` via stdin. It does not contain
  credentials or arbitrary shell command text.
- The bridge is available only to the Watchtower OS identity already able
  to use the root-pinned authorized SSH transport. It checks the fresh
  enrollment inventory and binds the origin to Watchtower.
- The receiver uses a dedicated allowlisted `lcd_sound_event` operation in
  the existing ForceCommand protocol. Its private SQLite journal claims an
  event ID before touching the hardware. Duplicates do not replay playback;
  an interrupted or ambiguous operation remains `uncertain`.
- Only the receiver resolves sound-event mappings, motifs, cooldown, mute,
  sequence playback, LCD priority and overlay expiry. It forces local mode
  for the underlying command, so a receiver cannot forward the event again.

## Commands (available in Draft source only)

```sh
gway-lcd-sound route set gway-001
gway-lcd-sound route set gway-001 --sound
gway-lcd-sound route set gway-001 --lcd
gway-lcd-sound route status --json
gway-lcd-sound route test
gway-lcd-sound route local
```

A configured route is per-user. The same account must be authorized to
invoke the GWay Remote bridge; this is intentionally **not** an unprivileged
universal socket or unauthenticated forwarding service. If the pinned
transport, remote receiver, runtime identity, or enrollment grant is
unavailable, remote operations fail. They never play on the sender instead.

Only one destination per device is configured. LCD and sound destinations
may differ. Periodic monitors and the piano compositor remain local.

## Legacy migration

The package installs **additional** `gway-sound-route` and
`gway-lcd-route` entrypoints. It does not overwrite existing `sound`,
`lcd` or /usr/local/bin commands. An operator must inventory, stage,
back up and explicitly switch audited consumers before calling the migration
transparent. Existing independent event producers are not automatically
migrated by this Draft branch.

## Risks, limits and rollout gates

- The bridge is currently bound to Watchtower's existing pinned SSH
  credentials and execution eligibility; there is no direct arbitrary
  server-to-server trust model or new WireGuard peer.
- Source motifs are interpreted exclusively by the receiver, using the
  receiver's current event database. The sender cannot configure them.
- The sender has a bounded 16-second subprocess timeout; the bridge retries
  a transient transport failure once using the same ID, never a new ID.
  When the outcome is uncertain, the sender returns an error.
- Unknown remote sound argument combinations fail closed. Existing
  single-host commands are preserved in local mode.
- Verify service account, HOME, route config ownership, receiver state
  directory, pinned identity and ForceCommand installation before field use.
- Compare the current main and PR #681 enrollment/eligibility behavior.
- Hermetic CI must cover identity, ID binding, expired events, retry,
  concurrent claims, mutations, and command compatibility.
- Only after controlled canary acceptance, test Watchtower to gway-001
  read/status then a benign sound/display, with rollback prepared.
- No branch merge, production deploy, SSH/ForceCommand or WireGuard
  change is authorized by this documentation.

## Authenticated server source routing (issue gway-remote #687)

An **optional** per-user source configuration extends the existing route
selection to send from the audited producer account on `ocpp-abb-1` or
`gelectriic.com` through Watchtower. Source routing is not activated by
package installation. The ordinary local/default and Watchtower pinned-SSH
routes stay as before.

For the actual service account on **each host**, an operator separately
provisions two private files (never commit these files or credentials):

- `~/.config/gway-lcd-sound/server-source.json` owned by that account, mode
  `0600`, in a mode `0700` owned directory:
  `{"schema":1,"origin":"ocpp-abb-1","url":"https://remote.arthexis.com/v1/lcd-sound/event","token_file":"/home/<service-user>/.config/gway-lcd-sound/server-source.token"}`.
  For the website service use `"origin":"gelectriic.com"`.
- `~/.config/gway-lcd-sound/server-source.token`, same owner, mode `0600`,
  containing **only the separately issued, revocable** `gway:lcd-sound`
  bearer for this specific source. The token path must be exactly adjacent to
  the configuration, not a symlink. Never copy Watchtower's SSH identity.

The HTTPS URL is fixed in the client implementation; redirects, environment
HTTP proxies and non-TLS URLs are forbidden. System CA trust validates TLS;
do not disable verification. Both hosts must be approved explicitly in the
operator-owned Watchtower grants for `gway-001` and their exact event classes.
The HTTPS endpoint is not published or activated by this PR.

After verifying the live event-producer user and obtaining a real,
authorized **read-only** status acknowledgment, run under that **same** user:

```sh
gway-lcd-sound route set gway-001 --sound
gway-lcd-sound route status --json
gway-lcd-sound route test
```

Use `--lcd` for a separately accepted LCD route. Every setting is per user;
setting `ubuntu`'s route does not change a systemd producer running as another
account. `route set` probes an authenticated sound status before writing.
Remote failed/uncertain events **never** run on local sender hardware.
`route local --sound` and `route local --lcd` restore that user's local
route; source credentials are revoked separately at Watchtower.

Do not assume that `sound`, `lcd`, application notification hooks, existing
systemd units or shell aliases call `gway-lcd-sound`. Audit actual
`ExecStart`, `User`, `HOME`, `PATH` and callsites, then migrate only an
approved set of producers explicitly to the release-owned
`gway-sound-route` and `gway-lcd-route` shims. Other local-only controls
such as the ethernet monitor and interactive piano remain local.
Receiver sound motifs, mute, priority and cooldown stay owned by gway-001.

A 200/JSON succeeded receipt proves Watchtower acknowledged the pinned relay
result, **not** human-observed audio/LCD effects. A 202, refused TLS,
revoked source, invalid response or timeout is an error and must not replay a
new event after uncertainty. Record exact installed revision, prior release,
service health and account ownership before controlled activation. Deactivate
the route and revoke its source grant before rollback of the versioned release.
