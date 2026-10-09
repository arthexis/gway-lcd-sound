from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts' / 'gway'))
from event_engine.app_collectors import classify_ocpp

def test_transaction_classification():
    assert classify_ocpp('StartTransaction', 'in') == 'transaction'
    assert classify_ocpp('BootNotification', 'in') == 'status'
