"""Opt-in live output primitives. Not wired into the observer CLI.

The caller supplies the existing sound engine callback. No device is accessed
by importing this module. A single observer owns the notification journal.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from .model import Event
from .notification_journal import NotificationJournal, identity
from .notification_outputs import output_plan
from .notification_rules import Notification


def event_filename(event: Event) -> str:
    """Stable, filesystem-safe name independent of source-provided IDs."""
    digest = hashlib.sha256(identity(event).encode("utf-8")).hexdigest()
    return f"lcd-event-{digest}.lck"


def queue_lcd(event: Event, lines: tuple[str, str], directory: Path) -> Path:
    """Atomically publish a legacy-compatible LCD event lockfile.

    Does not publish a second file for the same event. The delivery journal
    suppresses replay after the LCD consumer removes a consumed lockfile.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / event_filename(event)
    if destination.exists():
        return destination
    fd, temporary = tempfile.mkstemp(prefix=".lcd-event-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(line.replace("\n", " ").replace("\r", " ") for line in lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def deliver_live(
    event: Event,
    notification: Notification,
    journal: NotificationJournal,
    *,
    lcd_dir: Path,
    play_sound: Callable[[str], None],
) -> dict[str, object]:
    """Deliver independently, with at-most-once audio attempts.

    A crash after LCD publication but before journaling may cause a requeue.
    A crash after journaling audio intent but before playback may lose sound.
    These tradeoffs are explicit; exactly-once hardware effects are impossible.
    """
    plan = output_plan(notification)
    if journal.output_status(event, "lcd") != "queued":
        queue_lcd(event, plan["lcd_lines"], lcd_dir)
        journal.record_output(event, "lcd", "queued")
    sound = plan["sound"]
    if sound is not None and journal.output_status(event, "audio") != "attempted":
        journal.record_output(event, "audio", "attempted")
        play_sound(sound)
    return plan
