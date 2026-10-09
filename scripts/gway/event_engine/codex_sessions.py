"""Read-only Codex session JSONL lifecycle observation.

Only explicit lifecycle records are interpreted. Assistant messages and process
exits are not evidence of task completion.
"""
from __future__ import annotations

import json
from pathlib import Path
from .model import Event

LIFECYCLE = {
    "task_started": "started",
    "task_complete": "completed",
    "turn_aborted": "interrupted",
}

def session_files(root: Path) -> list[Path]:
    root = Path(root).expanduser()
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.jsonl"))

def session_records(path: Path, *, offset: int = 0, limit: int = 100):
    """Return complete records and their next byte offsets; retain partial lines."""
    if offset < 0 or limit < 1:
        raise ValueError("Invalid offset or limit")
    records = []
    with Path(path).open("rb") as stream:
        stream.seek(offset)
        while len(records) < limit:
            line = stream.readline()
            if not line:
                break
            end = stream.tell()
            if not line.endswith(b"\n"):
                break
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                records.append((None, end))
                continue
            records.append((record, end))
    return records

def lifecycle_event(record: object, path: Path) -> Event | None:
    if not isinstance(record, dict) or record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    state = LIFECYCLE.get(kind)
    if state is None:
        return None
    timestamp = record.get("timestamp")
    if not isinstance(timestamp, str):
        return None
    # One session file can contain multiple turns. Every start/completion is
    # a distinct occurrence, not a change to the process state.
    return Event("codex-turn", str(path), state, timestamp,
                 {"record_type": kind})
