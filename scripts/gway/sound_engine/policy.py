"""Policies used by the legacy event rules; injected clock for tests."""
from __future__ import annotations

SEVERITY = {"unknown": 0, "normal": 0, "warm": 1, "hot": 2, "critical": 3}


def thermal_due(level: str, last_level: str, now: float, last_at: float, repeat_seconds: float) -> bool:
    return SEVERITY.get(level, 0) > SEVERITY.get(last_level, 0) or now - last_at >= repeat_seconds


def voltage_due(active: bool, last_active: bool, now: float, last_at: float, repeat_seconds: float) -> bool:
    return active and (not last_active or now - last_at >= repeat_seconds)
