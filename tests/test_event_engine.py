import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "gway"))
from event_engine import Event, CheckpointStore, detect_transition


def test_baseline_and_state_changes(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.json")
    offline = Event.now("ocpp", "charger-1", "offline")
    online = Event.now("ocpp", "charger-1", "online")
    assert store.observe(offline) is None
    assert store.observe(offline) is None
    transition = store.observe(online)
    assert transition.previous_state == "offline"
    assert transition.event.state == "online"
    assert store.observe(online) is None


def test_restart_deduplicates_and_restores_cursor(tmp_path):
    path = tmp_path / "checkpoint.json"
    store = CheckpointStore(path)
    store.observe(Event.now("systemd", "ocpp.service", "active"))
    store.set_cursor("journal", "cursor-42")
    store.save()
    resumed = CheckpointStore(path)
    assert resumed.cursor("journal") == "cursor-42"
    assert resumed.observe(Event.now("systemd", "ocpp.service", "active")) is None
    assert resumed.observe(Event.now("systemd", "ocpp.service", "failed")) is not None


def test_independent_subjects_and_invalid_event(tmp_path):
    store = CheckpointStore(tmp_path / "state.json")
    assert store.observe(Event.now("systemd", "a", "active")) is None
    assert store.observe(Event.now("systemd", "b", "failed")) is None
    assert store.observe(Event.now("systemd", "a", "failed")) is not None
    assert store.observe(Event.now("systemd", "b", "active")) is not None
