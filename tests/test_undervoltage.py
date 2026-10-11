from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.gway.lcd_engine.undervoltage import Incident, is_active, display_time

class UndervoltageTests(unittest.TestCase):
    def test_only_current_bit_triggers(self):
        self.assertFalse(is_active("throttled=0x10000"))
        self.assertTrue(is_active("throttled=0x10001"))
        self.assertFalse(is_active("throttled=0x0"))
        self.assertIsNone(is_active("error"))

    def test_first_detection_survives_restart_and_resets_after_recovery(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "incident.json"
            start = datetime(2026, 10, 11, 14, 38, tzinfo=timezone.utc)
            observer = Incident(path)
            self.assertEqual(observer.update(True, start), start)
            self.assertEqual(observer.update(True, start + timedelta(minutes=4)), start)
            restarted = Incident(path)
            self.assertEqual(restarted.update(True, start + timedelta(minutes=5)), start)
            self.assertEqual(restarted.update(None, start + timedelta(minutes=6)), start)
            self.assertIsNone(restarted.update(False, start + timedelta(minutes=7)))
            self.assertFalse(path.exists())
            self.assertEqual(restarted.update(True, start + timedelta(minutes=8)), start + timedelta(minutes=8))

    def test_lcd_format_fits_sixteen_columns(self):
        moment = datetime(2026, 10, 11, 14, 38, tzinfo=timezone.utc)
        self.assertLessEqual(len(display_time(moment)), 16)

if __name__ == "__main__":
    unittest.main()
