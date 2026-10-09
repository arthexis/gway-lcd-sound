"""Notification ownership and replay safety."""
import json
import pytest

from event_engine.model import Event
from event_engine.notification_journal import NotificationJournal, identity


def event(state="completed", event_id=None):
    return Event("codex-turn", "session", state, "2026-10-09T12:00:00Z", event_id=event_id)


def test_identity_stable_and_distinct():
    assert identity(event()) == identity(event())
    assert identity(event()) != identity(event("interrupted"))
    assert identity(event(event_id="record-123")) == "record-123"


def test_shadow_survives_restart_without_becoming_delivered(tmp_path):
    path = tmp_path / "journal.json"
    journal = NotificationJournal(path)
    journal.record(event(), "shadowed")
    reopened = NotificationJournal(path)
    assert reopened.status(event()) == "shadowed"
    assert reopened.status(event()) != "delivered"


def test_delivered_never_downgrades_to_shadow(tmp_path):
    journal = NotificationJournal(tmp_path / "journal.json")
    journal.record(event(), "delivered")
    journal.record(event(), "shadowed")
    assert NotificationJournal(journal.path).status(event()) == "delivered"


def test_pending_is_distinct_from_shadow(tmp_path):
    journal = NotificationJournal(tmp_path / "journal.json")
    journal.record(event(), "pending")
    assert NotificationJournal(journal.path).status(event()) == "pending"


def test_corrupt_journal_fails_closed(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text('{"version":1,"entries":{"bad":"unexpected"}}')
    with pytest.raises(ValueError):
        NotificationJournal(path)


def test_reject_unknown_status(tmp_path):
    journal = NotificationJournal(tmp_path / "journal.json")
    with pytest.raises(ValueError):
        journal.record(event(), "played-maybe")
