"""Clock-driven priority and rotation scheduling; no I/O and no sleeps."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

from .model import Payload


@dataclass(frozen=True)
class Selection:
    payload: Payload
    source: str
    changed: bool
    scroll_step: int


class Scheduler:
    """Accept observations, advance virtual time and choose a frame.

    The adapter supplies the active runner, temporary event and current normal
    channel payload. Events and runner notifications preempt rotation; returning
    to rotation does not lose a previously selected normal frame.
    """

    def __init__(self, *, rotation_seconds: float, event_seconds: float, poll_seconds: float):
        self.rotation_seconds = max(float(rotation_seconds), 0.001)
        self.event_seconds = max(float(event_seconds), 0.001)
        self.poll_seconds = max(float(poll_seconds), 0.001)
        self.source = ""
        self.identity = None
        self.since = 0.0
        self.scroll_step = 0
        self.normal_advance = False

    def tick(self, *, now: datetime, monotonic: float,
             runner: Payload | None, event: Payload | None,
             normal: Payload) -> Selection:
        active = runner is not None and (runner.expires_at is None or runner.expires_at > now)
        selected = runner if active else event if event is not None and (
            event.expires_at is None or event.expires_at > now
        ) else normal
        source = "runner" if active else "event" if selected is event else "normal"
        identity = (source, selected)
        changed = source != self.source or identity != self.identity
        if changed:
            self.source = source
            self.identity = identity
            self.since = monotonic
            self.scroll_step = 0
            self.normal_advance = False
        elif source == "normal" and monotonic - self.since >= self.rotation_seconds:
            self.normal_advance = True
        elif source == "event" and monotonic - self.since >= self.event_seconds:
            # The caller may rotate an event's lines on the next observation.
            self.since = monotonic
        result = Selection(selected, source, changed, self.scroll_step)
        self.scroll_step += 1
        return result

    def take_normal_advance(self) -> bool:
        due = self.normal_advance
        self.normal_advance = False
        if due:
            self.since = 0.0
        return due
