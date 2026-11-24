# Typed operational LCD notices (gway-notification/v1)

The LCD is not a log viewer. The renderer receives one validated, bounded
notification describing **who**, **where**, **what** and **the verified
lifecycle state**. Only its display representation is shortened. The
underlying event retains full repository, issue, node and invocation identity.

## Notation and priorities

- `AGT@001` = AgentOps **executor** is gway-001.
- `FLT>ABB1` = affected **node** is ocpp-abb-1.
- `DEP>ABB1` = **deployment destination** is ocpp-abb-1, not the
  dispatching Watchtower or gway-001.
- `WT` = gelectriic.com Watchtower. `004` = gway-004.
- Every notice displays a pair of identity / evidence pages. A long subject
  adds paginated `REPO n/N` or `SERVICE n/N` pages, showing the **complete**
  identity rather than relying on non-unique 16-character truncation.
- Hardware undervoltage > critical notices > operational error notices >
  action runner / transient overlays > important notices > Reports charging
  carousel > normal display. Nonurgent notices never block high-priority
  operational overlays. All notices have bounded TTL (5..300 seconds).
- Pages within the same episode rotate every 5 seconds. Notices of the same
  severity rotate fairly; a critical active incident may preempt normal
  displays until recovered/expired. No frame rotation triggers sound.
- One sound only per genuine durable producer state transition, never by LCD
  refresh, page change, network retry or recovery from an overlay.

## Data contract

The exact `lcd notice '<JSON>'` command accepts these fields only:

```json
{
  "schema": "gway-notification/v1",
  "system": "agentops",
  "origin_node": "gway-001",
  "target_node": "gway-001",
  "subject": {
    "type": "github_issue",
    "repository": "arthexis/gway-agent-ops",
    "number": 107
  },
  "state": "codex_failed",
  "severity": "error",
  "reason_code": "CODEX_FAILED",
  "episode_id": "example-invocation",
  "expires_in": 120
}
```

Other allowed subjects: `service` with fixed `name` for fleet, and
`repository` with full `repository` for deploy. States and severity are
strictly enumerated for each system; incorrect combinations fail closed.
The renderer writes atomic 0600 per-episode `lcd-notice-*.json` files in its
existing lock directory, max 32 active episodes. It never executes JSON text,
makes network calls or plays sound on its own.

## Authentication and deployment

Local gway-001 producers use their installed `lcd` public command. Remote
producer calls pass the same JSON through the existing authenticated GWay
Remote `lcd.notice` action (not a generic command). Watchtower's trusted
source grant must explicitly allow `lcd.notice`, and the internal
`origin_node` **must equal** the Watchtower-verified source identity.
A sender that only has `lcd.show` or `lcd.reports` does not gain notice
authority. Receiver source remains Watchtower via pinned transport.

Deploy GWay Remote's validator/receiver first, then the LCD Sound renderer,
then opt-in the producer. Never ship tokens or install new SSH identities.
Rollback: disable producers first, leave notice TTL to expire, then switch
LCD Sound to the previously verified release. Remotely delivered uncertain
effects are not replayed.

## Event semantics

- AgentOps `finished` = Codex process ended only, **not** verified
  fulfillment of issue or external administrative work. `codex_failed`
  and `interrupted` are genuine executor states.
- Fleet `down` = a reachable node confirms the service is inactive;
  `unreachable` means its pinned SSH probe cannot reach the node, **not**
  a claim the service itself is down. Recovery requires independent good
  observations.
- Deploy `deploy-activated` = recipe returned success; independent
  revision + health evidence is required for `deploy-verified`.
  Unknown/uncertain output is never reported as success or failure.

Tracking: https://github.com/arthexis/gway-lcd-sound/issues/74
