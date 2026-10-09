#!/usr/bin/env python3
"""Read-only application event observer. No sound, LCD or producer hooks."""
from __future__ import annotations

import argparse
import json
import signal
import time
from pathlib import Path

from event_engine.app_observer import poll_csms, poll_codex, poll_codex_sessions
from event_engine.state import CheckpointStore
from event_engine.notification_rules import evaluate
from event_engine.notification_outputs import deliver_shadow
from event_engine.notification_journal import NotificationJournal

_STOP = False

def stop(_signum, _frame):
    global _STOP
    _STOP = True

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/state/gway-lcd-sound/app-observer.json")
    parser.add_argument("--codex-sessions", type=Path, default=Path.home() / ".codex/sessions")
    parser.add_argument("--csms-data", type=Path, default=None)
    parser.add_argument("--no-processes", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--shadow", action="store_true", help="alias for --notification-mode shadow")
    parser.add_argument("--notification-mode", choices=("legacy", "shadow"), default="legacy",
                        help="legacy: no observer output; shadow: record notification plans")
    parser.add_argument("--notification-journal", type=Path, default=None)
    parser.add_argument("--poll-seconds", type=float, default=4.0)
    args = parser.parse_args(argv)
    if args.poll_seconds < 1:
        parser.error("--poll-seconds must be at least 1")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    store = CheckpointStore(args.state)
    mode = "shadow" if args.shadow else args.notification_mode
    journal = NotificationJournal(args.notification_journal or args.state.with_name("notification-journal.json")) if mode == "shadow" else None
    def emit(event):
        print(json.dumps(event.to_dict(), sort_keys=True), flush=True)
        if mode == "shadow":
            notification = evaluate(event)
            if notification is not None:
                if journal.status(event) != "shadowed":
                    deliver_shadow(notification)
                    journal.record(event, "shadowed")
    while not _STOP:
        # Source failures are isolated; one broken source cannot stop others.
        sources = [("sessions", lambda: poll_codex_sessions(store, args.codex_sessions, deliver=emit))]
        if not args.no_processes:
            sources.append(("processes", lambda: poll_codex(store, deliver=emit)))
        if args.csms_data is not None:
            sources.append(("csms", lambda: poll_csms(store, args.csms_data, deliver=emit)))
        for name, poll in sources:
            try:
                poll()
            except (OSError, ValueError, RuntimeError, ImportError) as exc:
                print(json.dumps({"observer_error": name, "error": str(exc)}), flush=True)
        if args.once:
            break
        time.sleep(args.poll_seconds)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
