"""Shadow-mode adapter from notification intentions to output plans.

Live output is deliberately deferred until notification ownership is settled.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from .notification_rules import Notification


def display_subject(notification: Notification) -> str:
    """Human-facing label; never use a filesystem path as an LCD line."""
    if notification.source in {"codex", "codex-turn"}:
        return "Codex"
    return notification.subject.rsplit("/", 1)[-1][:32]


def output_plan(notification: Notification) -> dict[str, object]:
    """Describe the existing LCD event and sound-engine contracts without I/O."""
    return {
        "source": notification.source,
        "subject": notification.subject,
        "lcd_lines": (notification.title, display_subject(notification)),
        "sound": notification.sound,
    }


def deliver_shadow(notification: Notification, *, emit: Callable[[str], None] = print) -> dict[str, object]:
    """Log intended outputs without touching lockfiles, hardware or playback."""
    plan = output_plan(notification)
    emit(json.dumps({"mode": "shadow", **plan}, sort_keys=True))
    return plan
