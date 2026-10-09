"""LCD frames and channel state independent of the host or I2C transport."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Payload:
    line1: str
    line2: str
    label: str
    expires_at: datetime | None = None
    source: Path | None = None

    @property
    def has_text(self) -> bool:
        return bool(self.line1.strip() or self.line2.strip())


@dataclass(frozen=True)
class EventPayload:
    lines: tuple[str, ...]
    expires_at: datetime
    source: Path


@dataclass
class ChannelState:
    payloads: list[Payload]
    index: int = 0

    def next(self) -> Payload | None:
        if not self.payloads:
            return None
        payload = self.payloads[self.index % len(self.payloads)]
        self.index = (self.index + 1) % len(self.payloads)
        return payload
