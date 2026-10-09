"""Deterministic, hardware-free priority and timing engine.

Each tick consumes observations supplied by the host runner. Time is injected;
this module never reads files, sleeps, or touches an I2C device.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .model import Payload


@dataclass(frozen=True)
class Selection:
    payload: Payload
    source: str
    scroll_step: int
    advance_normal: bool
    advance_event: bool


class Scheduler:
    def __init__(self, *, rotation_seconds: float, event_seconds: float):
        self.rotation_seconds = max(float(rotation_seconds), 0.001)
        self.event_seconds = max(float(event_seconds), 0.001)
        self.source = ""
        self.identity: tuple | None = None
        self.since = 0.0
        self.scroll_step = 0

    def tick(self, *, now: datetime, monotonic: float, runner: Payload | None,
             event: Payload | None, normal: Payload) -> Selection:
        runner_valid = runner is not None and (
            runner.expires_at is None or runner.expires_at > now
        )
        event_valid = event is not None and (
            event.expires_at is None or event.expires_at > now
        )
        source = "runner" if runner_valid else "event" if event_valid else "normal"
        payload = runner if runner_valid else event if event_valid else normal
        assert payload is not None
        identity = (source, payload.label, payload.line1, payload.line2, payload.source)
        if identity != self.identity:
            self.source = source
            self.identity = identity
            self.since = monotonic
            self.scroll_step = 0
        elapsed = monotonic - self.since
        selection = Selection(
            payload=payload,
            source=source,
            scroll_step=self.scroll_step,
            advance_normal=source == "normal" and elapsed >= self.rotation_seconds,
            advance_event=source == "event" and elapsed >= self.event_seconds,
        )
        self.scroll_step += 1
        if selection.advance_normal or selection.advance_event:
            self.since = monotonic
            self.scroll_step = 0
        return selection
