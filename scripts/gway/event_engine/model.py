"""Pure event and state-transition model; no hardware or producer imports."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

@dataclass(frozen=True)
class Event:
    source: str
    subject: str
    state: str
    timestamp: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    event_id: str | None = None

    def __post_init__(self) -> None:
        if not all((self.source, self.subject, self.state, self.timestamp)):
            raise ValueError("source, subject, state and timestamp are required")
        datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))

    @classmethod
    def now(cls, source: str, subject: str, state: str, **metadata: Any) -> "Event":
        return cls(source, subject, state, datetime.now(timezone.utc).isoformat(), metadata)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.subject}"

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "subject": self.subject, "state": self.state,
                "timestamp": self.timestamp, "metadata": dict(self.metadata), "event_id": self.event_id}

@dataclass(frozen=True)
class Transition:
    event: Event
    previous_state: str | None


def detect_transition(event: Event, previous_state: str | None) -> Transition | None:
    """Emit on state change; first observation establishes a silent baseline."""
    if previous_state is None or previous_state == event.state:
        return None
    return Transition(event, previous_state)
