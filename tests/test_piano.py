"""Hardware-free piano composition regressions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1]/"scripts/gway/gway-piano.py"
spec=importlib.util.spec_from_file_location("gway_piano",MODULE)
piano=importlib.util.module_from_spec(spec)
spec.loader.exec_module(piano)

class PianoTests(unittest.TestCase):
    def test_pitch(self):
        self.assertAlmostEqual(piano.pitch(69),440)
        self.assertEqual(piano.label(440),"A4")
        self.assertEqual(piano.label(0),"REST")

    def test_validation(self):
        with self.assertRaises(ValueError):
            piano.validate([[500,0.41,0]])
        with self.assertRaises(ValueError):
            piano.validate([[500,0.1,0]]*13)
        with self.assertRaises(ValueError):
            piano.validate([[float("nan"),0.1,0]])
        self.assertEqual(piano.validate([[0,0.1,0]])[0][0],0)

    def test_save_load_existing_and_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"events.sqlite3"
            notes=[[440,0.12,0.04],[0,0.05,0]]
            piano.save(db,"motif","github-actions",notes)
            self.assertIn("github",piano.inventory(db,"motif"))
            self.assertEqual(piano.load(db,"motif","github"),notes)
            with self.assertRaises(ValueError):
                piano.save(db,"motif","github",notes)
            piano.save(db,"motif","github",notes,overwrite=True)
            piano.save(db,"sound","ready",notes)
            self.assertEqual(piano.load(db,"sound","ready"),notes)
            self.assertEqual(db.stat().st_mode & 0o077,0)

    def test_import_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/"notes.json"
            piano.export_file(output,[[440,0.1,0]])
            self.assertEqual(piano.import_file(output),[[440,0.1,0]])
            with self.assertRaises(ValueError):
                piano.export_file(output,[[440,0.1,0]])

if __name__=="__main__":
    unittest.main()
