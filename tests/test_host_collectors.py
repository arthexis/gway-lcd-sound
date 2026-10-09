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
        if cursor:
            return []
        return [(Event.now("journald", "charger.service", "message"), "c1")]
    assert len(poll_journal(store, ["charger.service"], collect=collect)) == 1
    store.save()
    assert poll_journal(CheckpointStore(store.path), ["charger.service"], collect=collect) == []
    assert calls == [None, "c1"]


def test_journal_parsing_and_invalid_records():
    payload = json.dumps({"__CURSOR": "c9", "__REALTIME_TIMESTAMP": "1000000", "_SYSTEMD_UNIT": "a.service", "MESSAGE": "started", "PRIORITY": "6"})
    result = journal_entries(cursor="c8", units=["a.service"], run=lambda argv: "invalid\\n".replace("\\n", "\n") + payload, limit=10)
    assert len(result) == 1
    assert result[0][1] == "c9"
    assert result[0][0].metadata["message"] == "started"
