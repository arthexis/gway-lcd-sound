import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.gway import lcd_lockfile_runner as lcd


class CurrentFrameTests(unittest.TestCase):
    def test_missing_frame_is_not_claimed_as_hardware_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(lcd, "CURRENT_FRAME_FILE", Path(directory) / "missing.json"):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(lcd.Runner.show_current(), 1)

    def test_read_back_exact_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.json"
            path.write_text(json.dumps({"ts": "now", "label": "test",
                                        "line1": "HELLO           ",
                                        "line2": "WORLD           "}))
            with patch.object(lcd, "CURRENT_FRAME_FILE", path):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(lcd.Runner.show_current(as_json=True), 0)
                self.assertEqual(json.loads(out.getvalue())["line1"], "HELLO           ")


if __name__ == "__main__":
    unittest.main()
