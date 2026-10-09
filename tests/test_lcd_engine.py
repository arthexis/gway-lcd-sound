from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.gway.lcd_engine.model import Payload
from scripts.gway.lcd_engine.rendering import clean_line, scroll_segment
from scripts.gway.lcd_engine.scheduler import Scheduler


def test_renderer_matches_existing_character_contract():
    assert clean_line("A\nB\r\x00C") == "A B  C"
    assert scroll_segment("Ready", 0) == "Ready".ljust(16)
    assert scroll_segment("ABCDEFGHIJKLMNOPQRST", 1) == "BCDEFGHIJKLMNOPQ"


def test_runner_pr_preempts_events_and_normal_until_removed():
    engine = Scheduler(rotation_seconds=10, event_seconds=3)
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    base = Payload("Normal", "Status", "normal")
    event = Payload("Warning", "Hot", "event", expires_at=now + timedelta(seconds=5))
    runner = Payload("Run PR #142", "feature/test", "actions-runner",
                     expires_at=now + timedelta(hours=1))
    assert engine.tick(now=now, monotonic=0, runner=None, event=None, normal=base).source == "normal"
    for minute in range(1, 15):
        result = engine.tick(
            now=now + timedelta(minutes=minute),
            monotonic=minute * 60, runner=runner, event=event, normal=base
        )
        assert result.source == "runner"
        assert not result.advance_normal
    back = engine.tick(now=now + timedelta(minutes=15), monotonic=900,
                       runner=None, event=None, normal=base)
    assert back.source == "normal"
    assert back.scroll_step == 0


def test_rotation_and_event_deadline_without_sleeping():
    engine = Scheduler(rotation_seconds=10, event_seconds=3)
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    base = Payload("Normal", "Status", "normal")
    event = Payload("Warning", "Hot", "event")
    assert not engine.tick(now=now, monotonic=0, runner=None, event=None,
                           normal=base).advance_normal
    assert not engine.tick(now=now, monotonic=9, runner=None, event=None,
                           normal=base).advance_normal
    assert engine.tick(now=now, monotonic=10, runner=None, event=None,
                       normal=base).advance_normal
    assert not engine.tick(now=now, monotonic=12, runner=None, event=event,
                           normal=base).advance_event
    assert engine.tick(now=now, monotonic=15, runner=None, event=event,
                       normal=base).advance_event


def test_expired_runner_does_not_override_live_event():
    engine = Scheduler(rotation_seconds=10, event_seconds=3)
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    expired = Payload("Run PR #42", "old", "actions-runner",
                      expires_at=now - timedelta(seconds=1))
    warning = Payload("Alert", "Now", "event")
    choice = engine.tick(now=now, monotonic=0, runner=expired,
                         event=warning, normal=Payload("Idle", "", "normal"))
    assert choice.payload is warning
    assert choice.source == "event"
