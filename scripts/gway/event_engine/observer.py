"""Read-only polling with explicit delivery acknowledgement and isolation."""
from __future__ import annotations
import logging
from collections.abc import Callable, Iterable
from .collectors import systemd_states, journal_entries
from .model import Event, Transition
from .state import CheckpointStore

LOG = logging.getLogger(__name__)
Deliver = Callable[[Event], None]
DeliverTransition = Callable[[Transition], None]


def poll_systemd(store: CheckpointStore, units: Iterable[str], *,
                 collect=systemd_states, deliver: DeliverTransition | None = None,
                 on_error: Callable[[str, Exception], None] | None = None) -> list[Transition]:
    """Observe units independently; checkpoint only after delivery succeeds.

    Pass deliver to enable crash-safe acknowledgement. Without it, this remains
    a collection-only compatibility API; caller must save its checkpoint.
    """
    changes = []
    for unit in units:
        try:
            for event in collect([unit]):
                previous = store._data["subjects"].get(event.key)
                from .model import detect_transition
                transition = detect_transition(event, previous)
                if transition is not None and deliver is not None:
                    deliver(transition)
                if transition is not None:
                    changes.append(transition)
                store.observe(event)
                if deliver is not None:
                    store.save()
        except Exception as exc:
            if on_error is not None:
                on_error(unit, exc)
            else:
                LOG.warning("systemd collector failed for %s: %s", unit, exc)
    return changes


def poll_journal(store: CheckpointStore, units: Iterable[str], *,
                 collect=journal_entries, limit: int = 100,
                 deliver: Deliver | None = None,
                 on_error: Callable[[str, Exception], None] | None = None,
                 max_batches: int = 10) -> list[Event]:
    """Replay bounded journal batches, persisting only acknowledged entries.

    The first call creates a silent baseline from the latest matching record.
    When deliver is supplied, each successful delivery is checkpointed before
    the next event. A delivery exception leaves its cursor uncommitted.
    """
    if limit < 1 or max_batches < 1:
        raise ValueError("limit and max_batches must be positive")
    source = "journald:" + ",".join(sorted(set(units)))
    cursor = store.cursor(source)
    emitted = []
    if cursor is None:
        try:
            entries = collect(cursor=None, units=units, limit=1)
            if entries:
                store.set_cursor(source, entries[-1][1])
                store.save()
        except Exception as exc:
            if on_error is not None:
                on_error(source, exc)
            else:
                LOG.warning("journal baseline failed: %s", exc)
        return emitted
    for _ in range(max_batches):
        try:
            entries = collect(cursor=cursor, units=units, limit=limit)
        except Exception as exc:
            if on_error is not None:
                on_error(source, exc)
            else:
                LOG.warning("journal collector failed: %s", exc)
            break
        if not entries:
            break
        for event, mark in entries:
            if mark == cursor:
                continue
            if deliver is not None:
                deliver(event)
            emitted.append(event)
            store.set_cursor(source, mark)
            cursor = mark
            if deliver is not None:
                store.save()
        if len(entries) < limit:
            break
    return emitted
