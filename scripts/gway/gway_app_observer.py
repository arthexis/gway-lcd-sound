#!/usr/bin/env python3
"""Application event observer. Live delivery requires explicit ownership opt-in."""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import time
from pathlib import Path

from event_engine.app_observer import poll_csms, poll_codex, poll_codex_sessions
from event_engine.state import CheckpointStore
from event_engine.notification_rules import evaluate
from event_engine.notification_outputs import deliver_shadow
from event_engine.notification_live import deliver_live
from event_engine.notification_journal import NotificationJournal
from event_engine.observer_lock import ObserverLock, ObserverAlreadyRunning

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
    parser.add_argument("--notification-mode", choices=("legacy", "shadow", "observer"), default="legacy",
                        help="legacy: no output; shadow: plans only; observer: gated live delivery")
    parser.add_argument("--notification-journal", type=Path, default=None)
    parser.add_argument("--lcd-dir", type=Path, default=None, help="existing LCD event lockfile directory")
    parser.add_argument("--sound-command", type=Path, default=None, help="explicit executable accepting one sound name argument")
    parser.add_argument("--ownership-file", type=Path, default=None, help="file containing exact acknowledgement: observer-owns-notifications")
    parser.add_argument("--poll-seconds", type=float, default=4.0)
    args = parser.parse_args(argv)
    if args.poll_seconds < 1:
        parser.error("--poll-seconds must be at least 1")
    if args.shadow and args.notification_mode == "observer":
        parser.error("--shadow conflicts with --notification-mode observer")
    if args.notification_mode == "observer":
        if not all((args.lcd_dir, args.sound_command, args.ownership_file)):
            parser.error("observer mode requires --lcd-dir, --sound-command and --ownership-file")
        try:
            acknowledgement = args.ownership_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            parser.error(f"cannot read ownership acknowledgement: {exc}")
        if acknowledgement != "observer-owns-notifications":
            parser.error("ownership acknowledgement does not match")
        if not args.lcd_dir.is_dir():
            parser.error("--lcd-dir must be an existing directory")
        if not args.sound_command.is_file() or not args.sound_command.stat().st_mode & 0o111:
            parser.error("--sound-command must be an executable file")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        with ObserverLock(args.state.with_suffix(args.state.suffix + ".lock")):
            return run_observer(args)
    except ObserverAlreadyRunning as exc:
        print(json.dumps({"observer_error": "already-running", "error": str(exc)}), flush=True)
        return 2


def run_observer(args):
    store = CheckpointStore(args.state)
    mode = "shadow" if args.shadow else args.notification_mode
    journal = NotificationJournal(args.notification_journal or args.state.with_name("notification-journal.json")) if mode in {"shadow", "observer"} else None
    def emit(event):
        print(json.dumps(event.to_dict(), sort_keys=True), flush=True)
        if mode == "shadow":
            notification = evaluate(event)
            if notification is not None:
                if journal.status(event) not in {"shadowed", "delivered"}:
                    deliver_shadow(notification)
                    journal.record(event, "shadowed")
        elif mode == "observer":
            notification = evaluate(event)
            if notification is not None and journal.status(event) != "delivered":
                deliver_live(event, notification, journal, lcd_dir=args.lcd_dir,
                             play_sound=lambda sound: subprocess.run(
                                 [str(args.sound_command), sound], check=True, timeout=20))
    while not _STOP:
        if mode == "observer":
            try:
                if args.ownership_file.read_text(encoding="utf-8").strip() != "observer-owns-notifications":
                    raise ValueError("ownership acknowledgement revoked")
            except (OSError, ValueError) as exc:
                print(json.dumps({"observer_error": "ownership", "error": str(exc)}), flush=True)
                return 3
        # Source failures are isolated; one broken source cannot stop others.
        sources = [("sessions", lambda: poll_codex_sessions(store, args.codex_sessions, deliver=emit))]
        if not args.no_processes:
            sources.append(("processes", lambda: poll_codex(store, deliver=emit)))
        if args.csms_data is not None:
            sources.append(("csms", lambda: poll_csms(store, args.csms_data, deliver=emit)))
        for name, poll in sources:
            try:
                poll()
            except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
                print(json.dumps({"observer_error": name, "error": str(exc)}), flush=True)
        if args.once:
            break
        time.sleep(args.poll_seconds)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
