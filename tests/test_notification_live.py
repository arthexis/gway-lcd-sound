"""6A live primitives: no hardware or systemd required."""
import json
from pathlib import Path

import pytest

from event_engine.model import Event
from event_engine.notification_journal import NotificationJournal
from event_engine.notification_live import deliver_live, event_filename
from event_engine.notification_rules import evaluate


def sample(event_id="codex:100"):
    return Event("codex-turn", "/tmp/session.jsonl", "completed",
                 "2026-10-09T16:00:00Z", event_id=event_id)


def test_live_delivery_and_restart_are_idempotent(tmp_path):
    event = sample()
    journal_path = tmp_path / "journal.json"
    lcd = tmp_path / "lcd"
    sounds = []
    journal = NotificationJournal(journal_path)
    deliver_live(event, evaluate(event), journal, lcd_dir=lcd, play_sound=sounds.append)
    file = lcd / event_filename(event)
    assert file.read_text() == "Codex completed\nCodex\n"
    assert sounds == ["ok"]
    file.unlink()  # LCD consumer already displayed it
    deliver_live(event, evaluate(event), NotificationJournal(journal_path),
                 lcd_dir=lcd, play_sound=sounds.append)
    assert not file.exists()
    assert sounds == ["ok"]


def test_audio_attempt_recorded_before_failure(tmp_path):
    event = sample()
    journal = NotificationJournal(tmp_path / "journal.json")
    def fail(_sound):
        raise RuntimeError("speaker unavailable")
    with pytest.raises(RuntimeError, match="speaker unavailable"):
        deliver_live(event, evaluate(event), journal, lcd_dir=tmp_path / "lcd", play_sound=fail)
    assert NotificationJournal(journal.path).output_status(event, "audio") == "attempted"
    deliver_live(event, evaluate(event), NotificationJournal(journal.path),
                 lcd_dir=tmp_path / "lcd", play_sound=fail)


def test_existing_shadow_journal_is_readable(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text(json.dumps({"version": 1, "entries": {"old": "shadowed"}}))
    journal = NotificationJournal(path)
    assert journal.entries == {"old": "shadowed"}
    deliver_live(sample(), evaluate(sample()), journal,
                 lcd_dir=tmp_path / "lcd", play_sound=lambda _: None)
    data = json.loads(path.read_text())
    assert data["entries"]["old"] == "shadowed"
    assert data["outputs"]["codex:100"] == {"lcd": "queued", "audio": "attempted"}


def test_distinct_occurrences_have_distinct_files():
    assert event_filename(sample("codex:100")) != event_filename(sample("codex:200"))
