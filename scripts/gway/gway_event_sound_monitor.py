#!/usr/bin/env python3
"""Monitor host events and request sound playback through the installed hook."""
from __future__ import annotations
import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sound_engine.config import *
from sound_engine.observations import *
from sound_engine.playback import SOUND_ALIASES, play
from sound_engine.state import log, save_state
from sound_engine.events import (
    added_removed, process_changes, handle_upgrade, handle_thermal, handle_undervoltage,
)

STOP = False


def handle_stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host-local GWAY event sound monitor.")
    parser.add_argument("--poll-seconds", type=float, default=float(os.environ.get("GWAY_EVENT_SOUND_POLL_SECONDS", "4")))
    parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
    parser.add_argument("--json", action="store_true", help="emit JSON for --once")
    parser.add_argument("--dry-run", action="store_true", help="log/print sound decisions without playback")
    args = parser.parse_args(argv)

    if args.once:
        payload = snapshot()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(payload)
        return 0

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    previous = snapshot()
    initial_thermal_level = (previous.get("thermal") or {}).get("level", "unknown")
    runtime: dict[str, Any] = {
        "last_thermal_level": initial_thermal_level,
        "last_thermal_played_level": initial_thermal_level,
        "last_thermal_at": time.monotonic(),
        "last_undervoltage_active": bool((previous.get("undervoltage") or {}).get("active")),
        "last_undervoltage_at": 0.0,
    }
    save_state({"started_at": time.time(), "snapshot": previous})
    log("baseline", summary="event sound monitor started")

    while not STOP:
        time.sleep(max(1.0, args.poll_seconds))
        current = snapshot()
        try:
            process_changes(previous, current, runtime, dry_run=args.dry_run)
        except Exception as exc:
            log("error", error=repr(exc))
        previous = current
        save_state({"updated_at": time.time(), "snapshot": current, "runtime": runtime})

    log("stopped", summary="event sound monitor stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
