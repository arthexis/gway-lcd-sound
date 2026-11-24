"""The new reports channel never masks existing high-priority messages."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/gway"))
import lcd_lockfile_runner
from lcd_engine.reports import store


def runner(lock_dir, monkeypatch):
    item = lcd_lockfile_runner.Runner(argparse.Namespace(lock_dir=[str(lock_dir)], dry_run=True))
    monkeypatch.setattr(item, "undervoltage_payload", lambda: None)
    return item


def test_priority_event_then_reports_then_normal(monkeypatch, tmp_path, capsys):
    store(tmp_path, [{"id": "ABB_1", "line1": "P Monterrey 037m",
                     "line2": "Charging 78%"}])
    item = runner(tmp_path, monkeypatch)
    item.run_once()
    assert "reports" in capsys.readouterr().out
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    (tmp_path / "lcd-event-test.lck").write_text(f"Important\nIncident\n{expiry}\n")
    item.run_once()
    assert "event" in capsys.readouterr().out
    (tmp_path / "lcd-actions-runner").write_text(f"Deploying\nNow\n{expiry}\n")
    item.run_once()
    assert "actions-runner" in capsys.readouterr().out or "runner" in capsys.readouterr().out


def test_fresh_reports_take_over_normal_only(monkeypatch, tmp_path, capsys):
    item = runner(tmp_path, monkeypatch)
    item.run_once()
    assert "reports" not in capsys.readouterr().out
    store(tmp_path, [{"id": "ABB_2", "line1": "A Valle 004m", "line2": "Preparing"}])
    item.run_once()
    assert "reports" in capsys.readouterr().out
