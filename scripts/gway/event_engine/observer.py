"""Coordinate independent collectors and checkpoint changes without side effects."""
from __future__ import annotations
from collections.abc import Callable, Iterable
from .collectors import systemd_states, journal_entries
from .model import Event, Transition
from .state import CheckpointStore


def poll_systemd(store: CheckpointStore, units: Iterable[str], *, collect=systemd_states) -> list[Transition]:
    changes = []
    for event in collect(units):
        transition = store.observe(event)
        if transition is not None:
            changes.append(transition)
    return changes


def poll_journal(store: CheckpointStore, units: Iterable[str], *, collect=journal_entries,
                 limit: int = 100) -> list[Event]:
    cursor = store.cursor("journald")
    entries = collect(cursor=cursor, units=units, limit=limit)
    emitted = []
    for event, mark in entries:
        if mark == cursor:
            continue
        emitted.append(event)
        store.set_cursor("journald", mark)
        cursor = mark
    return emitted
