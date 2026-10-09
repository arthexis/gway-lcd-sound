from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts' / 'gway'))
from event_engine.app_collectors import classify_ocpp

def test_transaction_classification():
    assert classify_ocpp('StartTransaction', 'in') == 'transaction'
    assert classify_ocpp('BootNotification', 'in') == 'status'

from event_engine.app_collectors import codex_processes
from event_engine.app_observer import poll_codex
from event_engine.state import CheckpointStore

def test_codex_snapshot(tmp_path):
    proc = tmp_path / 'proc'
    proc.mkdir()
    process = proc / '123'
    process.mkdir()
    (process / 'cmdline').write_bytes(b'/usr/bin/codex' + bytes([0]) + b'run')
    (process / 'stat').write_text('123 (codex) S ' + '0 ' * 19 + '999 0')
    events = codex_processes(proc=proc)
    assert len(events) == 1
    store = CheckpointStore(tmp_path / 'checkpoint.json')
    seen = []
    assert poll_codex(store, collect=lambda: events, deliver=seen.append) == 1
    assert poll_codex(CheckpointStore(store.path), collect=lambda: events, deliver=seen.append) == 0
