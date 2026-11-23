"""Bounded, lower-than-event OCPP Reports LCD carousel (hardware-free)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import stat
import tempfile

from .lockfiles import parse_datetime
from .model import Payload

FILE = "lcd-reports.json"
MAX_BYTES = 8192
MAX_FRAMES = 16
KEY = re.compile(r"[a-zA-Z0-9:_-]{1,80}\Z")


def _clean_frames(frames, *, now):
    if type(frames) is not list or len(frames) > MAX_FRAMES:
        raise ValueError("invalid reports frame count")
    accepted = []
    seen = set()
    for frame in frames:
        if type(frame) is not dict or not {"id", "line1", "line2"} <= set(frame) or (
            set(frame) - {"id", "line1", "line2", "until"}
        ):
            raise ValueError("invalid reports frame")
        identity = frame["id"]
        if type(identity) is not str or not KEY.fullmatch(identity) or identity in seen:
            raise ValueError("invalid reports identity")
        seen.add(identity)
        for line in ("line1", "line2"):
            value = frame[line]
            if type(value) is not str or len(value) > 16 or any(ord(c) < 32 or ord(c) > 126 for c in value):
                raise ValueError("invalid reports LCD line")
        expiry = frame.get("until")
        if expiry is not None:
            dt = parse_datetime(expiry) if type(expiry) is str else None
            if dt is None or not now < dt <= now + timedelta(seconds=125):
                # Expired completion frames should be excluded by the sender.
                raise ValueError("invalid reports frame expiry")
        accepted.append(dict(frame))
    return accepted


def parse_frames(raw, *, now=None):
    now = now or datetime.now(timezone.utc)
    if type(raw) is not str or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("oversized reports payload")
    return _clean_frames(json.loads(raw), now=now)


def store(root: Path, frames, *, now=None):
    """Atomically replace only the report-owned lockfile, never event overlays."""
    now = now or datetime.now(timezone.utc)
    frames = _clean_frames(frames, now=now)
    if root.is_symlink():
        raise PermissionError("unsafe reports directory")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / FILE
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PermissionError("unsafe reports file")
    record = {
        "schema": 1,
        "expires_at": (now + timedelta(seconds=75)).isoformat(),
        "frames": frames,
    }
    data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("oversized reports snapshot")
    fd, name = tempfile.mkstemp(prefix=".lcd-reports-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_frames(lock_dirs, *, now=None):
    now = now or datetime.now(timezone.utc)
    for root in lock_dirs:
        path = root / FILE
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_size < 1:
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if type(raw) is not dict or set(raw) != {"schema", "expires_at", "frames"} or raw["schema"] != 1:
                continue
            expiry = parse_datetime(raw["expires_at"])
            if expiry is None or not now < expiry <= now + timedelta(seconds=76):
                continue
            frames = _clean_frames(raw["frames"], now=now)
            return [(frame, path) for frame in frames
                    if "until" not in frame or parse_datetime(frame["until"]) > now]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    return []


def current_payload(lock_dirs, *, now=None, monotonic=0.0):
    now = now or datetime.now(timezone.utc)
    frames = read_frames(lock_dirs, now=now)
    if not frames:
        return None
    frame, path = frames[int(monotonic // 10) % len(frames)]
    return Payload(frame["line1"], frame["line2"], label="reports", source=path)
