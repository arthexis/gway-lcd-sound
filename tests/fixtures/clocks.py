"""Controllable monotonic and UTC times without sleeping."""
from datetime import datetime, timedelta, timezone

class Clock:
    def __init__(self, instant=None):
        self.instant = instant or datetime(2026, 10, 8, tzinfo=timezone.utc)
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def now(self):
        return self.instant + timedelta(seconds=self.seconds)

    def advance(self, seconds):
        self.seconds += seconds
