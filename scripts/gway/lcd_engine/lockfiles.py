"""Compatibility reader for the established GWAY LCD lockfile formats."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import EventPayload, Payload
from .rendering import clean_line

CHANNEL_FILES = {
    "high": "lcd-high",
    "low": "lcd-low",
    "summary": "lcd-summary",
    "github": "lcd-github",
    "clock": "clock",
    "uptime": "uptime",
    "stats": "stats",
    "usb": "lcd-usb",
}
KNOWN_CHANNELS = frozenset((*CHANNEL_FILES, "script"))
EVENT_PREFIX = "lcd-event-"
EVENT_GLOB = "lcd-event-*.lck"
RUNNER_LOCK = "lcd-actions-runner"
CHANNEL_ORDER_FILE = "lcd-channels.lck"
ROTATION_SCRIPT_FILE = "lcd-rotation.script"
TIMINGS_FILE = "lcd-timings"

_logger: Callable[..., None] = lambda _message, **_fields: None


def configure_logger(logger: Callable[..., None]) -> None:
    global _logger
    _logger = logger


def log(message: str, **fields: object) -> None:
    _logger(message, **fields)


def parse_datetime(raw: object) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_do_nothing_payload(line1: str, line2: str, label: str) -> bool:
    compacted = re.sub(r"\s+", " ", f"{line1} {line2}".strip().lower())
    if label in {"low", "summary"}:
        if "routine" in compacted and ("no action" in compacted or "0x/60m" in compacted):
            return True
        if "no err/wrn logs" in compacted or "ok no err/warn" in compacted:
            return True
    if label == "script":
        if compacted.startswith("work ") and "todo" in compacted:
            return True
        if compacted.startswith("log e0 w0") and "last none" in compacted:
            return True
        if compacted.startswith("serv fail 0") and "core ok" in compacted:
            return True
        if compacted.startswith("pwr ") and "thr ok" in compacted:
            return True
    return False


def read_channel_payload(path: Path, label: str, *, now: datetime) -> Payload | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log("lock-read-failed", path=str(path), error=str(exc))
        return None

    expires_at = parse_datetime(lines[2]) if len(lines) > 2 else None
    if expires_at and expires_at <= now:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    line1 = clean_line(lines[0] if lines else "")
    line2 = clean_line(lines[1] if len(lines) > 1 else "")
    if is_do_nothing_payload(line1, line2, label):
        return None
    return Payload(line1=line1, line2=line2, label=label, expires_at=expires_at, source=path)


def channel_lock_entries(lock_dir: Path, base_name: str) -> list[Path]:
    if not lock_dir.is_dir():
        return []
    entries: list[tuple[int, Path]] = []
    prefix = f"{base_name}-"
    for path in lock_dir.iterdir():
        name = path.name
        if name == base_name:
            entries.append((0, path))
        elif name.startswith(prefix):
            suffix = name[len(prefix) :]
            if suffix.isdigit():
                entries.append((int(suffix), path))
    return [path for _num, path in sorted(entries, key=lambda item: item[0])]


def load_channel_payloads(lock_dirs: Iterable[Path], channel: str, *, now: datetime) -> list[Payload]:
    base_name = CHANNEL_FILES[channel]
    payloads: list[Payload] = []
    for lock_dir in lock_dirs:
        for path in channel_lock_entries(lock_dir, base_name):
            payload = read_channel_payload(path, channel, now=now)
            if payload and payload.has_text:
                payloads.append(payload)
    return payloads


def event_sort_key(path: Path) -> tuple[int, str]:
    name = path.name
    if name.startswith(EVENT_PREFIX) and name.endswith(".lck"):
        suffix = name[len(EVENT_PREFIX) : -4]
        if suffix.isdigit():
            return int(suffix), name
    return 10**9, name


def parse_event_lock(path: Path, *, now: datetime) -> EventPayload | None:
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log("event-read-failed", path=str(path), error=str(exc))
        return None

    expires_at: datetime | None = None
    message_lines = raw_lines[:]
    if raw_lines:
        candidate = parse_datetime(raw_lines[-1])
        if candidate is not None:
            expires_at = candidate
            message_lines = raw_lines[:-1]
    if expires_at is None:
        expires_at = now + timedelta(hours=1)
    if expires_at <= now:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    if not message_lines:
        message_lines = ["", ""]
    lines = tuple(clean_line(line) for line in message_lines)
    return EventPayload(lines=lines, expires_at=expires_at, source=path)


def active_runner_payload(lock_dirs: Iterable[Path], *, now: datetime) -> Payload | None:
    """Persistent high-priority frame, expiring after abrupt job termination."""
    for lock_dir in lock_dirs:
        payload = read_channel_payload(lock_dir / RUNNER_LOCK, "actions-runner", now=now)
        if payload and payload.has_text and payload.expires_at is not None:
            return payload
    return None


def load_next_event(lock_dirs: Iterable[Path], *, now: datetime) -> EventPayload | None:
    candidates: list[Path] = []
    for lock_dir in lock_dirs:
        if lock_dir.is_dir():
            candidates.extend(lock_dir.glob(EVENT_GLOB))
    for path in sorted(candidates, key=event_sort_key):
        event = parse_event_lock(path, now=now)
        if event is not None:
            return event
    return None


def parse_channel_order(text: str) -> list[str]:
    channels: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0]
        if not line.strip():
            continue
        for token in line.replace(",", " ").split():
            value = token.strip().lower()
            if value in {"full", "all"}:
                value = "event"
            if value == "uptime":
                value = "stats"
            if not value or value == "event" or value in seen:
                continue
            if value in KNOWN_CHANNELS:
                seen.add(value)
                channels.append(value)
    return channels


def load_channel_order(lock_dirs: Iterable[Path]) -> list[str] | None:
    for lock_dir in lock_dirs:
        path = lock_dir / CHANNEL_ORDER_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as exc:
            log("channel-order-read-failed", path=str(path), error=str(exc))
            continue
        order = parse_channel_order(text)
        if order:
            return order
    return None


def load_rotation_script(lock_dirs: Iterable[Path], *, now: datetime) -> list[Payload]:
    payloads: list[Payload] = []
    for lock_dir in lock_dirs:
        path = lock_dir / ROTATION_SCRIPT_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as exc:
            log("rotation-script-read-failed", path=str(path), error=str(exc))
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not stripped.startswith("frame "):
                continue
            parts = re.findall(r'"([^"]*)"', stripped)
            if not parts:
                continue
            payloads.append(
                Payload(
                    line1=clean_line(parts[0]),
                    line2=clean_line(parts[1] if len(parts) > 1 else ""),
                    label="script",
                    source=path,
                )
            )
    return payloads


