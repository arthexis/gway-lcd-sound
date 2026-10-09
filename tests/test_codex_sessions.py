import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "gway"))
from event_engine.app_observer import poll_codex_sessions
from event_engine.state import CheckpointStore

def record(kind):
    return json.dumps({"type": "event_msg", "timestamp": "2026-10-09T10:00:00Z",
                       "payload": {"type": kind}}).encode() + bytes([10])

def test_lifecycle_baseline_and_restart(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    path = root / "session.jsonl"
    path.write_bytes(record("task_started"))
    store = CheckpointStore(tmp_path / "state.json")
    seen = []
    assert poll_codex_sessions(store, root, deliver=seen.append) == 0
    with path.open("ab") as stream:
        stream.write(record("task_complete"))
    assert poll_codex_sessions(CheckpointStore(store.path), root, deliver=seen.append) == 1
    assert seen[0].state == "completed"
    assert poll_codex_sessions(CheckpointStore(store.path), root, deliver=seen.append) == 0

def test_partial_and_new_session(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    store = CheckpointStore(tmp_path / "state.json")
    seen = []
    poll_codex_sessions(store, root, deliver=seen.append)
    path = root / "new.jsonl"
    data = record("turn_aborted")
    path.write_bytes(data[:-1])
    assert poll_codex_sessions(store, root, deliver=seen.append) == 0
    with path.open("ab") as stream:
        stream.write(data[-1:])
    assert poll_codex_sessions(store, root, deliver=seen.append) == 1
    assert seen[0].state == "interrupted"

def test_delivery_failure_keeps_cursor(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    store = CheckpointStore(tmp_path / "state.json")
    poll_codex_sessions(store, root, deliver=lambda event: None)
    path = root / "new.jsonl"
    path.write_bytes(record("task_started"))
    import pytest
    with pytest.raises(RuntimeError):
        poll_codex_sessions(store, root, deliver=lambda event: (_ for _ in ()).throw(RuntimeError()))
    seen = []
    assert poll_codex_sessions(CheckpointStore(store.path), root, deliver=seen.append) == 1
    assert seen[0].state == "started"
