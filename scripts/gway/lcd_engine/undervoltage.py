"""Host-local Raspberry Pi undervoltage incident tracking.

Only the current undervoltage bit (bit 0) is actionable; historical bit 16
must not keep an alert active after voltage has recovered.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

def is_active(raw: str) -> bool | None:
    try:
        return bool(int(raw.strip().split("=", 1)[1], 16) & 1)
    except (IndexError, ValueError):
        return None

def read_active() -> bool | None:
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True,
            timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return is_active(result.stdout) if result.returncode == 0 else None

class Incident:
    def __init__(self, path: Path):
        self.path = path
        self.first_seen: datetime | None = None

    def update(self, active: bool | None, now: datetime) -> datetime | None:
        if active is None:
            # Unknown is not proof of recovery; retain any existing incident.
            return self.first_seen
        if not active:
            self.first_seen = None
            self.path.unlink(missing_ok=True)
            return None
        if self.first_seen is None:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                self.first_seen = datetime.fromisoformat(value["first_seen"])
            except (OSError, ValueError, KeyError, TypeError):
                self.first_seen = now
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"first_seen": now.isoformat()}) + "\n", encoding="utf-8")
                os.replace(temporary, self.path)
        return self.first_seen

def display_time(first_seen: datetime) -> str:
    return first_seen.astimezone().strftime("%d-%b %H:%M")
