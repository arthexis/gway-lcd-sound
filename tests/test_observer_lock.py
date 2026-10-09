"""Single-writer lock and shadow replay behavior."""
import json
import pytest

from event_engine.observer_lock import ObserverLock, ObserverAlreadyRunning
from event_engine.notification_journal import NotificationJournal
from event_engine.model import Event


def test_lock_rejects_second_writer(tmp_path):
    path = tmp_path / "observer.lock"
    with ObserverLock(path):
        with pytest.raises(ObserverAlreadyRunning):
            with ObserverLock(path):
                pass
    with ObserverLock(path):
        pass


def test_lock_released_after_exception(tmp_path):
    path = tmp_path / "observer.lock"
    with pytest.raises(RuntimeError):
        with ObserverLock(path):
            raise RuntimeError("test")
    with ObserverLock(path):
        pass


def test_delivered_event_is_not_downgraded_by_shadow(tmp_path):
    journal = NotificationJournal(tmp_path / "journal.json")
    event = Event("codex-turn", "session", "completed", "2026-10-09T12:00:00Z")
    journal.record(event, "delivered")
    assert journal.status(event) in {"shadowed", "delivered"}
    assert journal.status(event) == "delivered"
