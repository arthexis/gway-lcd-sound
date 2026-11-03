"""Host-event monitoring lifecycle separated from hardware observation.

Pure runtime initialization and injected polling allow testing event detection,
logging, and persistence without GPIO, I2C, network or a running systemd unit.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


def initial_runtime(snapshot: dict[str, Any], *, monotonic: float) -> dict[str, Any]:
    """Preserve the baseline and alert-repeat state used by existing rules."""
    thermal = (snapshot.get("thermal") or {}).get("level", "unknown")
    return {
        "last_thermal_level": thermal,
        "last_thermal_played_level": thermal,
        "last_thermal_at": monotonic,
        "last_undervoltage_active": False,
        "last_undervoltage_at": 0.0,
    }


def run_monitor(*, observe: Callable[[], dict[str, Any]],
                process: Callable[..., None],
                persist: Callable[[dict[str, Any]], None],
                log: Callable[..., None],
                should_stop: Callable[[], bool],
                poll_seconds: float, dry_run: bool,
                sleep: Callable[[float], None] = time.sleep,
                monotonic: Callable[[], float] = time.monotonic,
                epoch: Callable[[], float] = time.time) -> None:
    """Keep original snapshot/transition ordering and isolation on rule failure."""
    previous = observe()
    runtime = initial_runtime(previous, monotonic=monotonic())
    persist({"started_at": epoch(), "snapshot": previous})
    log("baseline", summary="event sound monitor started")

    while not should_stop():
        sleep(max(1.0, poll_seconds))
        current = observe()
        try:
            process(previous, current, runtime, dry_run=dry_run)
        except Exception as exc:
            log("error", error=repr(exc))
        previous = current
        persist({"updated_at": epoch(), "snapshot": current, "runtime": runtime})

    log("stopped", summary="event sound monitor stopped")
