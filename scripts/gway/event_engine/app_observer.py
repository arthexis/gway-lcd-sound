"""Application polling with acknowledged cursor advancement."""
from __future__ import annotations
from pathlib import Path
from collections.abc import Callable
from .app_collectors import csms_events, codex_processes
from .model import Event
from .state import CheckpointStore

def poll_csms(store: CheckpointStore, data_dir: Path, *,
              deliver: Callable[[Event], None], collect=csms_events,
              limit: int = 100, max_batches: int = 10) -> int:
    """Initialize silently at the current tail; subsequently replay after cursor."""
    source = "ocpp:" + str(Path(data_dir).expanduser().resolve())
    saved = store.cursor(source)
    if saved is None:
        # Initial baseline: discover the most recent ID without replaying history.
        database = Path(data_dir).expanduser() / "ocpp-csms.sqlite3"
        if not database.exists():
            return 0
        import sqlite3
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
            latest = db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
        store.set_cursor(source, str(latest))
        store.save()
        return 0
    cursor = int(saved)
    count = 0
    for _ in range(max_batches):
        batch = collect(data_dir, after=cursor, limit=limit)
        if not batch:
            break
        for event, identifier in batch:
            deliver(event)
            store.set_cursor(source, str(identifier))
            store.save()
            cursor = identifier
            count += 1
        if len(batch) < limit:
            break
    return count

def poll_codex(store: CheckpointStore, *, collect=codex_processes,
               deliver: Callable[[Event], None]) -> int:
    """Report newly visible processes, without claiming process exit is job success."""
    current = collect()
    count = 0
    for event in current:
        key = event.key
        prior = store._data["subjects"].get(key)
        if prior is None:
            deliver(event)
            count += 1
        store.observe(event)
        store.save()
    return count
