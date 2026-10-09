"""Sound decisions with simulated observations and no physical devices."""
from __future__ import annotations

from scripts.gway.sound_engine import events, policy, observations, playback
from scripts.gway.sound_engine import state


def test_transitions_only_emit_when_state_changes(monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "play", lambda event, sound, detail="", *, dry_run=False: emitted.append((event, sound)))
    baseline = {"eth0": "disconnected", "thermal": {"level": "normal"}, "undervoltage": {"active": False}}
    connected = {**baseline, "eth0": "connected"}
    runtime = {}
    events.process_changes(baseline, connected, runtime, dry_run=True)
    assert ("eth0-connected", "eth-connected") in emitted
    emitted.clear()
    events.process_changes(connected, connected, runtime, dry_run=True)
    assert not emitted


def test_thermal_escalation_and_repetition(monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "play", lambda event, sound, detail="", *, dry_run=False: emitted.append(sound))
    time_value = [1000.0]
    monkeypatch.setattr(events.time, "monotonic", lambda: time_value[0])
    runtime = {"last_thermal_played_level": "normal", "last_thermal_at": 990.0}
    warm = {"thermal": {"level": "warm", "temp_c": 71.0}}
    events.handle_thermal({}, warm, runtime, dry_run=True)
    events.handle_thermal(warm, warm, runtime, dry_run=True)
    assert emitted == ["thermal-warm"]
    hot = {"thermal": {"level": "hot", "temp_c": 76.0}}
    events.handle_thermal(warm, hot, runtime, dry_run=True)
    assert emitted == ["thermal-warm", "thermal-hot"]
    time_value[0] += events.THERMAL_REPEAT_SECONDS
    events.handle_thermal(hot, hot, runtime, dry_run=True)
    assert emitted[-1] == "thermal-hot"
    assert len(emitted) == 3


def test_undervoltage_active_vs_historical(monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "play", lambda event, sound, detail="", *, dry_run=False: emitted.append(sound))
    runtime = {}
    historical = {"undervoltage": {"active": False, "historical": True}}
    events.handle_undervoltage({}, historical, runtime, dry_run=True)
    assert emitted == []
    active = {"undervoltage": {"active": True, "historical": True, "raw": "throttled=0x1"}}
    events.handle_undervoltage(historical, active, runtime, dry_run=True)
    events.handle_undervoltage(active, active, runtime, dry_run=True)
    assert emitted == ["undervoltage"]


def test_sound_alias_and_usb_classification():
    assert playback.SOUND_ALIASES["thermal-critical"] == "critical"
    assert playback.SOUND_ALIASES["repo-upgrade-start"] == "busy"
    assert observations.classify_usb("1949", "0001", "Reader") == "kindle"
    assert policy.thermal_due("critical", "hot", 1.0, 1.0, 300)
    assert not policy.voltage_due(True, True, 20.0, 10.0, 60)


def test_state_write_is_atomic_and_recoverable(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_FILE", tmp_path / "state.json")
    state.save_state({"runtime": {"last_thermal_level": "warm"}})
    assert '"warm"' in (tmp_path / "state.json").read_text()
    assert not list(tmp_path.glob("*.tmp"))
