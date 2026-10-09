"""Independent read-only observers for CSMS evidence and Codex processes."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from .model import Event

def csms_events(data_dir: Path, *, after: int = 0, limit: int = 100) -> list[tuple[Event, int]]:
    """Read append-only OCPP evidence without importing or calling the CSMS."""
    if after < 0 or limit < 1:
        raise ValueError("Invalid event cursor or limit")
    database = Path(data_dir).expanduser() / "ocpp-csms.sqlite3"
    if not database.is_file():
        return []
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        rows = connection.execute(
            "SELECT id, received_at, charger_id, action, direction, transaction_id "
            "FROM events WHERE id > ? ORDER BY id LIMIT ?", (after, limit)
        ).fetchall()
    finally:
        connection.close()
    result = []
    for identifier, received, charger, action, direction, txn in rows:
        category = classify_ocpp(str(action), str(direction))
        result.append((Event("ocpp", str(charger), str(action), str(received),
                             {"direction": direction, "transaction_id": txn, "category": category},
                             event_id=f"ocpp:{identifier}"), identifier))
    return result

def codex_processes(*, proc: Path = Path("/proc")) -> list[Event]:
    """Snapshot visible Codex processes; absence does not prove session completion."""
    observed = []
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            cmdline = (item / "cmdline").read_bytes().split(bytes([0]))
            args = [arg.decode("utf-8", errors="replace") for arg in cmdline if arg]
            executable = Path(args[0]).name if args else ""
            if executable not in ("codex", "codex.exe"):
                continue
            started = (item / "stat").read_text().rsplit(")", 1)[1].split()[19]
            observed.append(Event.now("codex", f"{item.name}:{started}", "running",
                                      pid=int(item.name), executable=executable))
        except (OSError, IndexError, ValueError):
            continue
    return observed


def classify_ocpp(action: str, direction: str) -> str:
    """Conservative categories: protocol actions alone are not failures."""
    if direction != "in":
        return "outbound"
    if action in {"StartTransaction", "StopTransaction"}:
        return "transaction"
    if action in {"BootNotification", "Heartbeat", "StatusNotification"}:
        return "status"
    return "activity"
