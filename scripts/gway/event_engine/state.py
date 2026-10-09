"""Atomic, durable observer checkpoints with no application dependencies."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from .model import Event, Transition, detect_transition

class CheckpointStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, Any] = {"version": 1, "subjects": {}, "cursors": {}}
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("version") != 1:
                raise ValueError("Unsupported checkpoint format")
            if not isinstance(loaded.get("subjects"), dict) or not isinstance(loaded.get("cursors"), dict):
                raise ValueError("Invalid checkpoint structure")
            self._data = loaded

    def observe(self, event: Event) -> Transition | None:
        previous = self._data["subjects"].get(event.key)
        transition = detect_transition(event, previous)
        self._data["subjects"][event.key] = event.state
        return transition

    def cursor(self, source: str) -> str | None:
        return self._data["cursors"].get(source)

    def set_cursor(self, source: str, cursor: str) -> None:
        self._data["cursors"][source] = cursor

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".checkpoint-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._data, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
