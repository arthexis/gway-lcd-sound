"""Chunk 6 preparation: compact display labels and per-turn event identities."""
from event_engine.model import Event
from event_engine.notification_rules import evaluate
from event_engine.notification_outputs import output_plan
from event_engine.notification_journal import identity


def test_codex_lcd_does_not_expose_session_path():
    event = Event("codex-turn", "/home/arthe/.codex/sessions/2026/10/09/example.jsonl",
                  "completed", "2026-10-09T16:00:00Z", event_id="codex-jsonl:example:400")
    plan = output_plan(evaluate(event))
    assert plan["lcd_lines"] == ("Codex completed", "Codex")
    assert plan["subject"] == event.subject


def test_repeated_turns_have_distinct_ids():
    first = Event("codex-turn", "/tmp/session.jsonl", "completed", "2026-10-09T16:00:00Z",
                  event_id="codex-jsonl:/tmp/session.jsonl:400")
    second = Event("codex-turn", "/tmp/session.jsonl", "completed", "2026-10-09T16:00:00Z",
                   event_id="codex-jsonl:/tmp/session.jsonl:900")
    assert identity(first) != identity(second)
