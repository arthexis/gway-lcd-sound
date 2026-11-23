# Issue gway-remote#687 — transparent public sound and lcd commands

## Contract and scope

The **public commands** are `sound ...` and `lcd ...`; callers do not
choose a transport or provide a bearer. The installed, per-OS-user private
`gway-lcd-sound route` state selects local hardware (default) or the
already-authorized `gway-001` destination. The existing `route_send.py`
retains HTTPS authentication, grant enforcement, source binding, deduplication
and *no local fallback on a remote failure*. This change does not create,
transfer, expand, rotate, or revoke credentials.

The versioned installer now publishes `~/.local/bin/sound` and
`~/.local/bin/lcd` as links to its existing routed shims **only when those
names are absent or already managed by this release**. It refuses to
overwrite independently installed commands. An existing
`/home/arthe/.local/bin/sound -> /usr/local/bin/sound` on `gway-001`
therefore remains local and untouched. `lcd`, when available under the
account, uses the same bounded local overlay engine by default. The names
are resolved in the user's environment; service units must have an explicit
audited PATH or absolute command path. Do not edit system-wide PATH or
`/usr/local/bin` implicitly.

These supported public invocations share the same routing pipeline:

```shell
sound notice
sound play notice
sound status --json
sound --event deploy-verified --source gway-remote
lcd status
lcd show "Deploy" "Ready" --seconds 15
lcd clear
```

Advanced playback options are accepted through the **same public syntax**
both before and after the sound name (and with `--event/--source`):
`--volume` (finite 0..1), `--repeat` (integer 1..20 subject to an
8-second bounded playback budget for built-in sounds), `--pause` (0..3),
`--backend` (auto/gpio/audio), `--within` (0..3600), `--dry-run`
(safe preview, result text returned), `--resolve` (event read-only resolution),
`--motif` (bounded receiver-local name), `--pin` (ONLY the receiver's
configured sound pin) and `--device` (ONLY receiver-configured sink, and
only with `--backend audio`). `--sequence` supports safe playback modifiers
and `--dry-run`, but is never repeated. The receiver independently validates
all values; an authorized source does not inherit arbitrary GPIO, audio sink,
or filesystem access. Unrecognized modifiers, overly long multi-repeat jobs,
unsafe combinations, internal `--pattern-json`/`--event-db`, and hardware
monitor/piano controls are explicitly denied for forwarded events. Such a
refusal is **not** a remote retry or a local fallback.

For example, all of the following preserve identical caller syntax on the
three hosts:

```sh
sound --volume 0.30 notice --repeat 2 --pause 0.10
sound notice --backend gpio --pin 18
sound --event deploy-verified --source gway-remote --within 30
sound notice --dry-run
sound --sequence '{"format":"gway-piano-v1","notes":[[440,0.1,0]]}' --dry-run
```

The remote receiver executes each physical request at most once; `--repeat`
is an explicitly approved repetition **within one request**, never an
automatic network retry. Invalid or uncertain outcomes do not replay.

## Verified pre-rollout source inventory (2026-11-23)

- `ocpp-abb-1`: Ubuntu UID 1000 owns the versioned
  `gway-lcd-sound` installation and configured per-user authenticated
  route. `ocpp-csms.service` runs as Ubuntu; Reports collector and ingest
  are active under `ocpp-reports`, which has **no** provisioned sender route.
- `gelectriic.com` (Watchtower): Ubuntu UID 1000 owns the authenticated
  sender route and the Odoo process. `gway-mcp-gateway.service` runs as
  `gway-mcp-gateway`; Actions has a separate `github-actions` account.
  Neither account has a proven sender route or approved event class.
- `gway-001`: `sound` is an existing local system command;
  `gway-lcd-sound` is installed, but public `lcd` was absent on the
  inspected executor PATH.
- On both servers `~/.local/bin` is on Ubuntu's login-shell PATH, but not
  the non-login Bastion SSH PATH. Do not infer command availability in
  unattended units from interactive shell tests.

The existing `DeploymentSound` hook in gway-remote emits bounded deployment
events, but its actual invocation account must be checked for every deploy
path. Its local LCD lockfile is not transparently forwarded. There is no
evidence that Reports collector, the MCP gateway or the Actions runner should
receive a new credential. Do not modify unrelated consumers or their service
accounts.

## Authentication boundary

The existing enrollment ledger says `ocpp-abb-1` is an attested node, but
that fact alone does **not** authenticate an arbitrary HTTPS request from its
Ubuntu processes to Watchtower. The reverse hop Watchtower→gway-001 already
uses pinned SSH and cannot authenticate the source→Watchtower hop. A verified
machine-principal adapter for the latter hop has **not** been demonstrated.
Keep the two working, separate `gway:lcd-sound` source bearers and
root-owned per-source/target/operation grants. They expire approximately
**2026-12-22 23:49 UTC**; renewal remains an explicit operational task.
No token is passed to, or logged by, a consumer of the public commands.

## Controlled rollout gates

1. Record `main` and PR HEAD and green required checks; record service
   health separately. Do not mistake a merged PR/CI for deployment.
2. Record the installed release and prior release and
   `~/.local/bin/{sound,lcd,gway-lcd-sound}` ownership/symlinks for the
   exact user on each host. Refuse an unexpected public command collision.
3. For the audited user, verify the existing private route and preflight
   with `gway-lcd-sound route test`; do not print credentials.
4. Install the pinned exact clean commit with
   `scripts/deploy/install.sh install --no-restart`. Verify before changing
   any PATH. For Ubuntu login shells, check `command -v sound` and
   `command -v lcd`. No service migration is included.
5. Read-only public `sound status --json` and `lcd status` first; then
   one distinct approved `sound notice` and one bounded `lcd show` per
   source. Capture unique source, Watchtower and receiver IDs and their
   statuses. A transport receipt alone does not prove physical output;
   distinguish independently observed output from reported output.
6. Test failure and negative authorization with **separate canary credentials**
   or hermetic fixtures, never by revoking live business identities. Do not
   retry ambiguous physical events, even with a new ID.
7. Check customer CSMS/Reports, Watchtower MCP/nginx/Odoo and gway-001
   receiver health after each rollout. Keep #687 open until both server
   public commands have a real accepted route and rollback evidence.

## Reversible rollback

The current release's `scripts/deploy/install.sh rollback --no-restart`
restores `previous` and, when it lacks the explicit public-command manifest,
**removes only aliases created by this installer**. Pre-existing commands,
including `gway-001`'s local sound symlink, are preserved. If rollback of
the entire remote feature becomes necessary, first disable the affected
per-account route using `gway-lcd-sound route local` and coordinate separate
source-grant revocation; preserve the Watchtower ingress rollback documents.
Do not remove a functioning credential until a verified alternative exists.
Never roll back a receiver while an event outcome is uncertain.

## Opt-in acceptance receipts

An operator can set `GWAY_LCD_SOUND_AUDIT_RECEIPTS=1` in the **test
session** (not in the consumer command arguments). This enables two
structured `stderr` records, each prefixed `gway-lcd-sound-receipt`:
`phase=submitted` records the client request ID before the network
operation, and `phase=confirmed` records Watchtower's
`receiver_request_id`, `source_event_sha256`, status and duplicate flag
after verified success. No bearer, HTTP authorization header, SSH key,
private file path or caller-controlled response extras are included.
Absent the environment switch, normal stdout, stderr and exit semantics
remain unchanged.

A `submitted` record without `confirmed` is an **unknown outcome**;
never issue another physical event to retry it. Correlate the receiver ID
with the existing gway-001 private SQLite journal and the recorded
Watchtower HTTPS response. The HTTPS receipt is Watchtower's acknowledgment,
not an independently retained Watchtower server-side audit log or proof
of human-observed output.
