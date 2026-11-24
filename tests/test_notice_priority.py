"""Priority integration of typed notices with existing event and Reports."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/gway"))
import lcd_lockfile_runner
from lcd_engine.notifications import store_notice
from lcd_engine.reports import store as store_reports


def base(system, state, severity, target, subject, reason):
    return {"schema": "gway-notification/v1", "system": system,
            "origin_node": "gway-001", "target_node": target,
            "subject": subject, "state": state, "severity": severity,
            "reason_code": reason, "episode_id": "sample-incident",
            "expires_in": 120}


def runner(root, monkeypatch):
    item = lcd_lockfile_runner.Runner(
        argparse.Namespace(lock_dir=[str(root)], dry_run=True))
    monkeypatch.setattr(item, "undervoltage_payload", lambda: None)
    return item


def test_urgent_fleet_incident_preempts_event_and_charging(tmp_path, monkeypatch, capsys):
    store_reports(tmp_path, [{"id": "charger_1", "line1": "P Monterrey 037m",
                             "line2": "Charging 78%"}])
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()
    (tmp_path / "lcd-event-test.lck").write_text(f"Routine\nEvent\n{expiry}\n")
    store_notice(tmp_path, base(
        "fleet", "down", "critical", "ocpp-abb-1",
        {"type": "service", "name": "ocpp-reports"}, "SERVICE_DOWN"))
    item = runner(tmp_path, monkeypatch)
    item.run_once()
    assert "notice-critical" in capsys.readouterr().out


def test_important_notice_yields_to_event_but_preempts_reports(tmp_path, monkeypatch, capsys):
    store_reports(tmp_path, [{"id": "charger_1", "line1": "P Monterrey 037m",
                             "line2": "Charging 78%"}])
    store_notice(tmp_path, base(
        "agentops", "finished", "important", "gway-001",
        {"type": "github_issue", "repository": "arthexis/aeon-mud", "number": 53},
        "PROCESS_ENDED"))
    item = runner(tmp_path, monkeypatch)
    item.run_once()
    assert "notice-important" in capsys.readouterr().out
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    (tmp_path / "lcd-event-test.lck").write_text(f"Event\nImportant\n{expiry}\n")
    item.run_once()
    assert "event" in capsys.readouterr().out
