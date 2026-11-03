#!/usr/bin/env python3
"""Monitor host events and request sound playback through the installed hook."""
from __future__ import annotations
import argparse
import json
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sound_engine.observations import snapshot, thermal_level
from sound_engine.playback import SOUND_ALIASES
from sound_engine.state import log, save_state
from sound_engine.events import process_changes
from sound_engine.monitor_runtime import run_monitor

STOP = False


def handle_stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host-local GWAY event sound monitor.")
    parser.add_argument("--poll-seconds", type=float, default=float(os.environ.get("GWAY_EVENT_SOUND_POLL_SECONDS", "1")))
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

    run_monitor(
        observe=snapshot,
        process=process_changes,
        persist=save_state,
        log=log,
        should_stop=lambda: STOP,
        poll_seconds=args.poll_seconds,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
