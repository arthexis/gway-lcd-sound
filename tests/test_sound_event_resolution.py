"""S1: real sound CLI event resolution without GPIO or audio hardware."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/gway/sound.sh"


class EventSoundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "private" / "events.sqlite3"

    def call(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPT), *args], capture_output=True, text=True,
            env={**os.environ, "GWAY_SOUND_EVENT_DB": str(self.db)}, timeout=10,
        )

    def test_seeded_codex_mapping(self):
        result = self.call("--event", "SessionStart", "--source", "codex", "--resolve")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sound"], "notice")
        self.assertEqual(self.db.stat().st_mode & 0o077, 0)

    def test_seeded_ssh_session_mapping_and_motif(self):
        result = self.call("--event", "session-opened", "--source", "ssh", "--resolve")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sound"], "notice")
        self.assertIn("ssh", json.loads(self.call("--list-motifs").stdout))

    def test_seeded_gway_monitor_motif(self):
        result = self.call("--event", "ap-connect", "--source", "gway-monitor", "--resolve")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sound"], "notice")
        result = self.call("--event", "lcd-external-change", "--source", "gway-monitor", "--resolve")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sound"], "notice")
        self.assertIn("gway-monitor", json.loads(self.call("--list-motifs").stdout))

    def test_source_override_global_fallback_and_alias(self):
        self.call("--event", "Stop", "--source", "codex", "--resolve")
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO events VALUES ('*', 'finished', 'ok')")
            db.execute("INSERT INTO events VALUES ('example', 'finished', 'warning')")
            db.execute("INSERT INTO aliases VALUES ('example', 'done', 'finished')")
        self.assertEqual(json.loads(self.call("--event", "done", "--source", "example", "--resolve").stdout)["sound"], "warning")
        self.assertEqual(json.loads(self.call("--event", "finished", "--source", "another", "--resolve").stdout)["sound"], "ok")

    def test_unknown_event_silent_and_existing_sound_unchanged(self):
        self.assertIsNone(json.loads(self.call("--event", "mystery", "--source", "app", "--resolve").stdout)["sound"])
        self.assertEqual(self.call("--event", "mystery", "--source", "app").returncode, 0)
        direct = self.call("ok", "--dry-run")
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertIn("ok:", direct.stdout)

    def test_resolve_never_plays_audio(self):
        result = self.call("--event", "Stop", "--source", "codex", "--resolve")
        self.assertNotIn("backend=", result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_requires_event_for_source(self):
        self.assertNotEqual(self.call("--source", "codex").returncode, 0)
