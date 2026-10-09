"""Persistent notification decisions; shadow is not delivery.

Single-writer journal with atomic replacement. Output attempt state is stored
separately; the observer CLI still cannot activate live delivery.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from .model import Event


def identity(event: Event) -> str:
    """Prefer producer event IDs; otherwise identify a concrete observation."""
    if event.event_id:
        return event.event_id
    raw = json.dumps(
        [event.source, event.subject, event.state, event.timestamp, event.metadata],
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class NotificationJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, str] = {}
        self.outputs: dict[str, dict[str, str]] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("entries"), dict):
                raise ValueError("Invalid notification journal")
            if not all(isinstance(k, str) and v in {"shadowed", "delivered", "pending"} for k, v in data["entries"].items()):
                raise ValueError("Invalid notification journal entries")
            self.entries = data["entries"]
            outputs = data.get("outputs", {})
            if not isinstance(outputs, dict) or not all(
                isinstance(k, str) and isinstance(v, dict) and
                set(v).issubset({"lcd", "audio"}) and
                all(s in {"queued", "attempted"} for s in v.values())
                for k, v in outputs.items()
            ):
                raise ValueError("Invalid notification output journal")
            self.outputs = outputs

    def status(self, event: Event) -> str | None:
        return self.entries.get(identity(event))

    def record(self, event: Event, status: str) -> None:
        if status not in {"shadowed", "delivered", "pending"}:
            raise ValueError("Invalid notification status")
        key = identity(event)
        if self.entries.get(key) == "delivered" and status != "delivered":
            return
        self.entries[key] = status
        self.save()

    def output_status(self, event: Event, output: str) -> str | None:
        if output not in {"lcd", "audio"}:
            raise ValueError("Invalid notification output")
        return self.outputs.get(identity(event), {}).get(output)

    def record_output(self, event: Event, output: str, status: str) -> None:
        if (output, status) not in {("lcd", "queued"), ("audio", "attempted")}:
            raise ValueError("Invalid notification output state")
        key = identity(event)
        self.outputs.setdefault(key, {})[output] = status
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".notifications-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "entries": self.entries, "outputs": self.outputs}, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
