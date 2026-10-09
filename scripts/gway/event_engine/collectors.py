"""Read-only host collectors. No LCD or audio dependencies."""
from __future__ import annotations
import json
import subprocess
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any
from .model import Event

Run = Callable[[list[str]], str]


def _run(argv: list[str]) -> str:
    result = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=10)
    return result.stdout


def systemd_states(units: Iterable[str], *, run: Run = _run) -> list[Event]:
    """Snapshot configured units. Unknown/inaccessible states are not failures."""
    events = []
    for unit in units:
        if not unit or unit.startswith("-"):
            raise ValueError("Invalid systemd unit")
        raw = run(["systemctl", "show", unit, "--property=ActiveState", "--property=SubState", "--no-pager"])
        props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        active = props.get("ActiveState", "unknown")
        sub = props.get("SubState", "unknown")
        events.append(Event.now("systemd", unit, active, substate=sub))
    return events


def journal_entries(*, cursor: str | None, units: Iterable[str], run: Run = _run, limit: int = 100) -> list[tuple[Event, str]]:
    """Fetch journal records after a persisted cursor, in journal order.

    A bounded batch requires repeated calls until drained. No cursor means a
    silent tail baseline rather than replaying the entire historical journal.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    argv = ["journalctl", "--no-pager", "--output=json", "--reverse=no"]
    if cursor:
        argv.append("--after-cursor=" + cursor)
    else:
        argv.extend(["--lines", str(limit)])
    for unit in units:
        if not unit or unit.startswith("-"):
            raise ValueError("Invalid journal unit")
        argv.extend(["--unit", unit])
    output = run(argv)
    records: list[tuple[Event, str]] = []
    for line in output.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        mark = entry.get("__CURSOR")
        if not isinstance(mark, str) or not mark:
            continue
        ts = entry.get("__REALTIME_TIMESTAMP")
        try:
            timestamp = datetime.fromtimestamp(int(ts) / 1_000_000, timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError, OSError):
            timestamp = datetime.now(timezone.utc).isoformat()
        subject = str(entry.get("_SYSTEMD_UNIT") or entry.get("SYSLOG_IDENTIFIER") or "unknown")
        message = entry.get("MESSAGE", "")
        if not isinstance(message, str):
            message = str(message)
        event = Event("journald", subject, "message", timestamp,
                      {"message": message, "priority": str(entry.get("PRIORITY", ""))}, event_id=mark)
        records.append((event, mark))
    return records[:limit]
