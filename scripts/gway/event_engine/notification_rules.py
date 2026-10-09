"""Pure notification policy. No I/O, hardware, or producer imports.

This module returns *intentions*, not delivery. Consumers must handle
deduplication, shadow mode and output ownership separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from .model import Event


@dataclass(frozen=True)
class Notification:
    subject: str
    title: str
    sound: str | None = None
    source: str = ""


def evaluate(event: Event) -> Notification | None:
    """Map explicit evidence to a notification; unknown states remain silent."""
    if event.source == "codex-turn":
        actions = {
            "started": ("Codex running", None),
            "completed": ("Codex completed", "ok"),
            "interrupted": ("Codex interrupted", "warning"),
        }
        action = actions.get(event.state)
        if action:
            return Notification(event.subject, action[0], action[1], event.source)
        return None

    if event.source == "codex":
        # A process disappearing is NOT evidence that its task succeeded.
        return None

    if event.source == "ocpp":
        # The events table records requests, not necessarily accepted results.
        # StopTransaction alone cannot prove a successful charge.
        if event.metadata.get("direction") != "in":
            return None
        titles = {
            "StartTransaction": "OCPP start requested",
            "StopTransaction": "OCPP stop reported",
        }
        title = titles.get(event.state)
        return Notification(event.subject, title, None, event.source) if title else None

    if event.source in {"systemd", "systemd-unit"} and event.state == "failed":
        return Notification(event.subject, "Service failed", "error", event.source)

    return None
