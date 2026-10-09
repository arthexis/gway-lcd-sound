import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "gway"))
from event_engine.collectors import systemd_states, journal_entries
from event_engine.observer import poll_systemd, poll_journal
from event_engine.state import CheckpointStore
from event_engine.model import Event


def test_systemd_transition_and_restart(tmp_path):
    state = {"active": "active"}
    def collect(units):
        return [Event.now("systemd", "charger.service", state["active"])]
    path = tmp_path / "state.json"
    store = CheckpointStore(path)
    assert poll_systemd(store, ["charger.service"], collect=collect) == []
    state["active"] = "failed"
    changes = poll_systemd(store, ["charger.service"], collect=collect)
    assert len(changes) == 1 and changes[0].previous_state == "active"
    store.save()
    assert poll_systemd(CheckpointStore(path), ["charger.service"], collect=collect) == []


def test_systemd_parses_show():
    events = systemd_states(["charger.service"], run=lambda argv: "ActiveState=failed\\nSubState=failed\\n".replace("\\n", "\n"))
    assert events[0].state == "failed"
    assert events[0].metadata["substate"] == "failed"


def test_journal_cursor_resume(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.json")
    calls = []
    def collect(*, cursor, units, limit):
        calls.append(cursor)
        if cursor is None:
            return [(Event.now("journald", "charger.service", "message"), "c1")]
        if cursor == "c1":
            return [(Event.now("journald", "charger.service", "message"), "c2")]
        return []
    assert poll_journal(store, ["charger.service"], collect=collect) == []
    assert len(poll_journal(store, ["charger.service"], collect=collect)) == 1
    store.save()
    assert poll_journal(CheckpointStore(store.path), ["charger.service"], collect=collect) == []
    assert calls == [None, "c1", "c2"]


def test_journal_delivery_failure_does_not_advance_cursor(tmp_path):
    store = CheckpointStore(tmp_path / "state.json")
    store.set_cursor("journald:a.service", "c1")
    store.save()
    def collect(*, cursor, units, limit):
        if cursor == "c1":
            return [(Event.now("journald", "a.service", "message"), "c2")]
        return []
    def fail(event):
        raise RuntimeError("output unavailable")
    import pytest
    with pytest.raises(RuntimeError, match="output unavailable"):
        poll_journal(store, ["a.service"], collect=collect, deliver=fail)
    assert CheckpointStore(store.path).cursor("journald:a.service") == "c1"
    received = []
    assert len(poll_journal(store, ["a.service"], collect=collect, deliver=received.append)) == 1
    assert CheckpointStore(store.path).cursor("journald:a.service") == "c2"


def test_one_broken_unit_does_not_block_other_units(tmp_path):
    store = CheckpointStore(tmp_path / "state.json")
    errors = []
    def collect(units):
        if units == ["broken.service"]:
            raise OSError("unavailable")
        return [Event.now("systemd", "good.service", "active")]
    assert poll_systemd(store, ["broken.service", "good.service"], collect=collect,
                        on_error=lambda unit, error: errors.append(unit)) == []
    assert errors == ["broken.service"]
    assert store._data["subjects"]["systemd:good.service"] == "active"


def test_journal_parsing_and_invalid_records():
    payload = json.dumps({"__CURSOR": "c9", "__REALTIME_TIMESTAMP": "1000000", "_SYSTEMD_UNIT": "a.service", "MESSAGE": "started", "PRIORITY": "6"})
    result = journal_entries(cursor="c8", units=["a.service"], run=lambda argv: "invalid\\n".replace("\\n", "\n") + payload, limit=10)
    assert len(result) == 1
    assert result[0][1] == "c9"
    assert result[0][0].metadata["message"] == "started"
