# GWAY LCD and Sound

Host-local LCD, event-sound, and GPIO/audio alert helpers for GWAY boxes.

This repository intentionally keeps these Raspberry Pi field-node features out
of the Arthexis application repository. The scripts still read a few historical
Arthexis lock paths for compatibility with deployed producers, but the runtime
surface belongs to GWAY.

## Contents

- `scripts/gway/`: standalone Python and Bash helpers for LCD rotation,
  LCD summaries, eth0 node display, event-sound polling, hotplug sounds,
  sound playback, GPIO mute control, and archived local media shortcuts.
- `config/systemd/gway/`: system and user service units copied from the live
  GWAY layout.
- `config/templates/`: non-secret environment templates.
- `config/udev/rules.d/`: redacted udev hotplug rule templates.
- `docs/`: operations notes and man pages.
- `tests/`: focused unit tests that do not require the physical LCD or audio
  hardware.

## Install and verify

Run from the repository root as the GWAY service user:

```bash
bash scripts/deploy/install.sh install
bash scripts/deploy/install.sh verify
# Restore the previous release, if needed:
bash scripts/deploy/install.sh rollback
```

The installer stages a versioned release under `~/.local/share/gway-lcd-sound/releases/`, atomically switches `current`, installs stable command links in `~/.local/bin`, and verifies installed entry points and Python imports. It restarts the user LCD lockfile service when available. Use `--no-restart` for CI or isolated tests. System-level units, udev rules, `/usr/local` helpers and their required permissions remain separate administrative setup steps documented under `docs/operations/gway/`.

OCPP-CSMS trusted self-hosted simulator CI uses this same installer and validates the installed LCD runner, status publisher, and sound monitor; passing this check does not substitute for a physical I²C/audio field test.

## Validation

```bash
PYTHONPATH=. python3 -m pytest tests
bash -n scripts/gway/codex-sound-hook scripts/gway/gway-event-sound-hotplug scripts/gway/gway-toggle-gpio-sound-mute scripts/gway/sound.sh scripts/gway/radio-play
python3 -m py_compile scripts/gway/*.py
```

Do not commit state from `/home/arthe/.local/state`, `/run`, recordings,
generated summaries, or local service drop-ins containing machine-specific
values.

## Behavioral baseline (refactor chunk 1)

The hardware-free contract suite exercises LCD formatting, rotation/event and
Actions runner lockfile priority, expiration, sound aliases, mute/disable,
playback errors, concurrent playback locking, and fake-display output.

```bash
python3 -m pip install pytest
python3 -m pytest -q tests
```

A GitHub-hosted `Behavior contracts` workflow runs this suite on PRs and
main pushes. It requires no I²C, GPIO, audio equipment or self-hosted runner.
Chunk 1 preserves all production scripts; later refactors should extend the
contracts before moving implementation code.

## S1 — Event-aware `sound`

The existing `sound ok` / `sound warning` vocabulary remains intact.
Callers can now supply events without knowing the available sounds:

```bash
sound --event SessionStart --source codex
sound --event disconnected --source wifi
sound --resolve --event Stop --source codex
```

`--resolve` prints a JSON record with `source`, `event`, `sound`
and `matched_source`, without playing audio. Unknown events are **silent**.

Mapping data is stored in SQLite at
`~/.local/state/gway-sound/events.sqlite3` by default (override with
`GWAY_SOUND_EVENT_DB` or `--event-db`). The first database creation seeds
a small set of known Codex and Wi-Fi event mappings. The schema is:

- `events(source, event, sound)` with unique (source, event)
- `aliases(source, alias, event)` with unique (source, alias)

Use source `*` for global mapping and aliases. A source-specific mapping
wins over the global mapping. Aliases are resolved before mapping; there
are no implicit aliases or heuristic guesses. SQLite changes to mappings
are deliberately outside the public sound CLI in S1. No separate
`sound-hook` command is introduced.

**Motifs and source-context cooldown** are reserved for S2. Motif playback
will precede the event sound, with a configurable context timeout and
reannouncement on source change; S1 does not play motifs yet.

## S2 — Source motifs and auditory context

Motifs announce **which source is speaking**, before the event-specific
earcon. Each source can have one motif, defined in the SQLite `motifs`
table with `source`, `notes` (JSON array of `[frequency_hz,
duration_seconds, pause_seconds]`) and `cooldown_seconds`. The initial
Codex and Wi-Fi motifs have a 45-second timeout. Existing S1 databases
receive these defaults through an idempotent migration.

The single persisted `motif_context` row holds the last audible source
and motif playback timestamp. A source motif is played when the source
changes, the timeout expires, or no prior context exists. Back-to-back
events from the same source within the timeout play only the event sound.
An intervening source without its own motif does not establish a new
motif context.

Playback of the motif followed by the event is serialized with an
exclusive `motif-play.lock`, preventing other event-aware sound
invocations from interleaving. The context is saved only after successful
motif playback; muted GPIO output and dry runs do not advance it.
`sound --event Stop --source codex --dry-run` previews whether a motif
would play without changing context. `sound --resolve` continues to
return the static event mapping without affecting playback state.

The original `sound NAME` interface remains intact. Existing direct
sound callers are unaffected by motif context and will be migrated in
S3 where appropriate.

## S3 — Producer migration (first pass)

The hotplug entry point and host event monitor now emit source/event
notifications directly to `sound` without invoking `codex-sound-hook`.
Existing legacy hook remains installed for external callers until the
compatibility migration is complete. Hotplug uses
`GWAY_SOUND_BIN` to override the default `/usr/local/bin/sound`.
The monitor accepts `GWAY_EVENT_SOUND_SOUND_BIN` (with the older
`GWAY_EVENT_SOUND_HOOK` as an override alias).

The SQLite event database is seeded idempotently on first use with existing
monitor sound-name aliases, preserving historic event distinctions while
removing the playback wrapper. Changing a mapping no longer requires changing
the producer. Codex lifecycle configuration and any remaining Actions-runner
call sites still need their own audit and migration; this first pass does not
modify the installed Codex runtime or remove its legacy hook.

## GitHub Actions runner motif

The `github-actions` source has its own ascending three-note motif (392, 587,
and 784 Hz) with a 45-second context cooldown. Existing `started` and
`stopped` event mappings use the `notice` and `warning` earcons respectively.
The motif is seeded idempotently for both new and existing event databases;
customized motif rows are never overwritten.

The repository also ships `github-actions-sound-hook`, a best-effort hook
for the official runner's **job** lifecycle. It maps `started` to
`job-started / notice` and `completed` to `job-completed / notice`.
Completion is intentionally neutral: the official completed hook alone does
not establish whether the job succeeded or failed. Audio failures are ignored.

To opt in on Gway-001, configure these two variables **in the runner process
environment**, using the installed absolute path (adapt the home directory
to the runner account):

```sh
ACTIONS_RUNNER_HOOK_JOB_STARTED=/home/arthe/.local/bin/github-actions-sound-hook
ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/home/arthe/.local/bin/github-actions-sound-hook
```

Both variables point to the same script, but it needs to know which event
occurred. Use small wrapper scripts invoking `github-actions-sound-hook started`
and `github-actions-sound-hook completed` respectively, then configure the
two runner variables to point to those wrappers. Hooks must be executable
and available to the runner OS account. Do not configure them in a repository
workflow: these are runner-side settings. Validate runner service ownership
and its environment before installing or restarting anything.

The installer does **not** activate runner hooks or modify the runner service. Playback requires a
trusted runner-side producer to emit `sound --event started --source github-actions`
and `sound --event stopped --source github-actions`. Do not claim audible
runner notifications until those hooks are installed and field-tested.
