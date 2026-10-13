"""S2 motif context and source transition behavior without physical audio."""
import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/gway/sound.sh"


class MotifTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "state" / "events.sqlite3"

    def call(self, event="SessionStart", source="codex", *extra):
        p = subprocess.run(["bash", str(SCRIPT), "--event", event, "--source", source,
                            "--dry-run", *extra], text=True, capture_output=True,
                           env={**os.environ, "GWAY_SOUND_EVENT_DB": str(self.db)}, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def set_context(self, source, played_at):
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT OR REPLACE INTO motif_context VALUES (1,?,?)",
                       (source, played_at))

    def test_initial_motif_and_repeat_suppression(self):
        self.assertTrue(self.call()["motif"])
        self.set_context("codex", time.time())
        self.assertFalse(self.call("Stop")["motif"])

    def test_source_switch_reannounces_before_cooldown(self):
        self.call()
        self.set_context("wifi", time.time())
        self.assertTrue(self.call("Stop")["motif"])

    def test_expiration_reannounces_same_source(self):
        self.call()
        self.set_context("codex", time.time() - 60)
        self.assertTrue(self.call("Stop")["motif"])

    def test_missing_motif_keeps_event_only(self):
        self.call()
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO events VALUES ('app', 'finished', 'ok')")
        row = self.call("finished", "app")
        self.assertFalse(row["motif"])
        self.assertEqual(row["sound"], "ok")

    def test_invalid_definition_fails_without_playback(self):
        self.call()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE motifs SET notes='[]' WHERE source='codex'")
        p = subprocess.run(["bash", str(SCRIPT), "--event", "Stop", "--source", "codex",
                            "--dry-run"], capture_output=True, text=True,
                           env={**os.environ, "GWAY_SOUND_EVENT_DB": str(self.db)}, timeout=10)
        self.assertNotEqual(p.returncode, 0)
