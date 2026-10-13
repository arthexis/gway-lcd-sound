"""S3 tests for event-producing commands without real playback hardware."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOUND = ROOT / "scripts/gway/sound.sh"
HOTPLUG = ROOT / "scripts/gway/gway-event-sound-hotplug"


class ProducerMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.db = self.dir / "state/events.sqlite3"

    def test_hotplug_events_use_direct_sound_interface(self):
        spy = self.dir / "sound"
        spy.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$SOUND_SPY\"\n")
        spy.chmod(0o755)
        log = self.dir / "calls"
        env = {**os.environ, "GWAY_SOUND_BIN": str(spy), "SOUND_SPY": str(log)}
        for name in ("bastion-add", "bastion-remove", "wifi-add", "wifi-remove", "other"):
            subprocess.run(["bash", str(HOTPLUG), name], env=env, check=True)
        self.assertEqual(log.read_text().splitlines(), [
            "--event bastion-insert --source hotplug",
            "--event bastion-remove --source hotplug",
            "--event connected --source wifi",
            "--event disconnected --source wifi",
            "--event unknown --source hotplug",
        ])

    def test_all_migrated_events_resolve_to_original_sounds(self):
        old = {"ap-connect": "notice", "bastion-ready": "ok",
               "bastion-failed": "error", "usb-peripheral": "notice",
               "usb-unknown": "attention", "thermal-warm": "warning",
               "thermal-hot": "error", "thermal-critical": "critical",
               "repo-upgrade-complete-unknown": "notice",
               "repo-upgrade-start": "busy", "repo-upgrade-failed": "error"}
        for event, expected in old.items():
            result = subprocess.run(
                ["bash", str(SOUND), "--event", event, "--source", "gway-monitor", "--resolve"],
                env={**os.environ, "GWAY_SOUND_EVENT_DB": str(self.db)},
                text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["sound"], expected)

    def test_actions_runner_dropin_is_direct_and_nonfatal(self):
        conf = (ROOT / "config/systemd/gway/actions-runner/20-gway-sound.conf").read_text()
        self.assertIn("ExecStartPost=-/usr/bin/timeout 2 /usr/local/bin/sound --event started --source github-actions", conf)
        self.assertIn("ExecStopPost=-/usr/bin/timeout 2 /usr/local/bin/sound --event stopped --source github-actions", conf)
        self.assertNotIn("codex-sound-hook", conf)
        for event, expected in (("started", "notice"), ("stopped", "warning")):
            result = subprocess.run(
                ["bash", str(SOUND), "--event", event, "--source", "github-actions", "--resolve"],
                env={**os.environ, "GWAY_SOUND_EVENT_DB": str(self.db)},
                text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["sound"], expected)
