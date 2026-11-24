"""Hermetic priority carousel fixtures: no I2C, no sound, no route."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/gway"))
from lcd_engine.reports import parse_frames, store, current_payload, read_frames


NOW = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)


def sample(index, until=None):
    frame = {"id": f"charger_{index}", "line1": f"A Valle {index:03d}m",
             "line2": "Charging 78%"}
    if until:
        frame["until"] = until.isoformat()
    return frame


def test_multiple_frames_rotate_every_ten_seconds(tmp_path):
    store(tmp_path, [sample(1), sample(2)], now=NOW)
    assert current_payload([tmp_path], now=NOW, monotonic=1).line1.endswith("001m")
    assert current_payload([tmp_path], now=NOW, monotonic=11).line1.endswith("002m")
    assert current_payload([tmp_path], now=NOW, monotonic=21).line1.endswith("001m")


def test_short_lease_fails_closed(tmp_path):
    store(tmp_path, [sample(1)], now=NOW)
    assert current_payload([tmp_path], now=NOW + timedelta(seconds=74)) is not None
    assert current_payload([tmp_path], now=NOW + timedelta(seconds=76)) is None


def test_expired_complete_does_not_hide_other_chargers(tmp_path):
    store(tmp_path, [sample(1, NOW + timedelta(seconds=5)), sample(2)], now=NOW)
    frames = read_frames([tmp_path], now=NOW + timedelta(seconds=6))
    assert [item[0]["id"] for item in frames] == ["charger_2"]


@pytest.mark.parametrize("frames", [
    [{"id": "../escape", "line1": "A", "line2": "B"}],
    [{"id": "ok", "line1": "X"*17, "line2": "B"}],
    [{"id": "ok", "line1": "A\nB", "line2": "B"}],
    [{"id": "ok", "line1": "A", "line2": "B"}]*2,
    [sample(1)]*17,
    [{"id": "ok", "line1": "A", "line2": "B", "extra": "shell"}],
])
def test_bad_report_frames_rejected(frames):
    with pytest.raises(ValueError):
        parse_frames(json.dumps(frames), now=NOW)


def test_symlink_target_rejected(tmp_path):
    target = tmp_path / "real"
    target.write_text("preserve")
    (tmp_path / "lcd-reports.json").symlink_to(target)
    with pytest.raises(PermissionError):
        store(tmp_path, [sample(1)], now=NOW)
    assert target.read_text() == "preserve"
