"""Behavioral contracts for pure notification policy."""
import pytest

from event_engine.model import Event
from event_engine.notification_rules import Notification, evaluate


def event(source, state, *, direction=None):
    metadata = {} if direction is None else {"direction": direction}
    return Event(source, "subject-1", state, "2026-10-09T12:00:00Z", metadata)


@pytest.mark.parametrize(("state", "title", "sound"), [
    ("started", "Codex running", None),
    ("completed", "Codex completed", "ok"),
    ("interrupted", "Codex interrupted", "warning"),
])
def test_codex_explicit_lifecycle(state, title, sound):
    assert evaluate(event("codex-turn", state)) == Notification(
        "subject-1", title, sound, "codex-turn"
    )


@pytest.mark.parametrize("state", ["not-visible", "running", "completed"])
def test_process_presence_never_proves_task_outcome(state):
    assert evaluate(event("codex", state)) is None


@pytest.mark.parametrize("state", ["unknown", "heartbeat", ""])
def test_unrecognized_codex_lifecycle_is_silent(state):
    assert evaluate(event("codex-turn", state)) is None


@pytest.mark.parametrize(("state", "title"), [
    ("StartTransaction", "OCPP start requested"),
    ("StopTransaction", "OCPP stop reported"),
])
def test_ocpp_requests_are_informational_not_success(state, title):
    notice = evaluate(event("ocpp", state, direction="in"))
    assert notice == Notification("subject-1", title, None, "ocpp")


@pytest.mark.parametrize("direction", ["out", "response", None])
def test_outbound_or_unclassified_ocpp_is_silent(direction):
    assert evaluate(event("ocpp", "StopTransaction", direction=direction)) is None


def test_ocpp_status_without_connection_evidence_is_silent():
    assert evaluate(event("ocpp", "StatusNotification", direction="in")) is None


def test_explicit_service_failure_has_error_intent():
    assert evaluate(event("systemd", "failed")) == Notification(
        "subject-1", "Service failed", "error", "systemd"
    )
    assert evaluate(event("systemd", "active")) is None


def test_unknown_source_is_silent():
    assert evaluate(event("other", "completed")) is None
