# LCD/Sound refactoring roadmap

## Goal

Reduce maintenance cost without changing the behavior of the long-running
GWay-001 appliance. Preserve installed entrypoints, sound event names,
sound patterns, GPIO mute and source motifs, LCD priority and lockfile
formats, service and udev contracts, and existing event journals.

## Current architectural boundaries

| Area | Source of truth | Recommendation |
| --- | --- | --- |
| LCD I2C and display output | `lcd_engine/hardware/` | Keep hardware adapters isolated from deterministic scheduling |
| LCD priority / rotation | `lcd_engine/scheduler.py` | Preserve runner > event > normal priorities |
| LCD lockfile compatibility | `lcd_engine/lockfiles.py` | Do not change formats or expiration semantics as part of cleanup |
| Host event observation | `sound_engine/observations.py` | Keep it read-only and injectable |
| Sound event decisions | `sound_engine/events.py` | Refactor smaller event families with contract tests |
| Sound monitor lifecycle | `sound_engine/monitor_runtime.py` | Extracted this increment; test with fake observation, clocks and persistence |
| Sound dispatch and mapping | `sound_engine/playback.py` + `sound.sh` | Maintain one sound vocabulary / event mapper; keep current installed shell ABI until packaging is verified |
| Local CLI dispatch | `gway-lcd-sound` | Keep backwards-compatible commands during refactor |
| Sound mute | `sound.sh`, `gway-toggle-gpio-sound-mute` | Preserve working mute; cross-UID runtime file differences deserve explicit independent validation |

## Completed in first increment

Extracted monitor lifecycle from `gway_event_sound_monitor.py` into
`sound_engine/monitor_runtime.py`; removed wildcards and obsolete imports.
The CLI retains `--once`, `--json`, `--dry-run`,
`--poll-seconds`, SIGINT/SIGTERM handling, event names, state-file format,
and event logging. Tests characterize baseline, transition, failure and stop
behavior without touching physical hardware.

## Proposed follow-up increments (separate PRs)

1. Decompose `sound_engine/events.py` by event family (interfaces,
   peripherals, alerts and upgrades). Snapshot exact event decisions before
   relocating code; no changing thresholds or alert intervals.
2. Isolate the monolithic embedded Python in `sound.sh` **only after**
   validating release packaging, `/usr/local/bin/sound` compatibility,
   motif SQLite migrations and all installed producers. Avoid a big-bang
   rewrite; preserve default sound and backend selection.
3. Split `gway_eth0_node_lcd_monitor.py` into discovery, peer probes, LCD
   formatting and state persistence, retaining `eth0` CLI behavior.
4. Add read-only event-to-sound trace tooling if needed to identify stray
   chirps from source/event logs without creating new routine notifications.

## Required validation

- `python3 -m pytest -q tests` (hardware-free), shell syntax and Python
  compilation checks.
- Existing installer/deploy tests and CI.
- On-device checks are **not** part of a code-only PR. After merge, a
  separately authorized field validation should verify LCD rotation,
  event preemption, source motifs, GPIO mute, event/thermal/voltage alerts
  and service restart. Never alter I2C configuration or restart live OCPP
  workloads merely to validate a refactor.
