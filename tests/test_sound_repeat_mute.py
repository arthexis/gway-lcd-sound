"""Hardware-free coverage for repeat, pause and playback-wide mute."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/gway/sound.sh"


class RepeatAndMuteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.mute = root / "gpio-muted"
        self.hook = root / "codex"
        self.hook.mkdir()
        self.env = {
            **os.environ,
            "GWAY_SOUND_EVENT_DB": str(root / "events.sqlite3"),
            "NODE_SOUND_GPIO_MUTE_FILE": str(self.mute),
            "CODEX_SOUND_HOOK_STATE_DIR": str(self.hook),
            "GWAY_SOUND_BACKEND_LOG": str(root / "backend.log"),
        }

    def invoke(self, *args):
        return subprocess.run(["bash", str(SCRIPT), *args],
                              capture_output=True, text=True, env=self.env, timeout=15)

    def test_direct_sound_repeats_and_dry_run_count(self):
        result = self.invoke("notice", "--repeat", "3", "--pause", "0", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 3)

    def test_custom_pattern_repeats(self):
        result = self.invoke("--pattern-json", "[[440,0.02,0.0]]", "--repeat", "4",
                             "--pause", "0", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 4)

    def test_event_repeats_without_repeating_source_context(self):
        result = self.invoke("--event", "SessionStart", "--source", "codex",
                             "--repeat", "3", "--pause", "0", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 3)

    def test_repeat_bounds_and_invalid_pause(self):
        for number in ("0", "-1", "21", "1.5"):
            result = self.invoke("notice", "--repeat", number, "--dry-run")
            self.assertNotEqual(result.returncode, 0, number)
        for seconds in ("nan", "inf", "-1", "3.1"):
            result = self.invoke("notice", "--pause", seconds, "--dry-run")
            self.assertNotEqual(result.returncode, 0, seconds)

    def test_muted_gpio_and_audio_backend_both_skip(self):
        self.mute.touch()
        for backend in ("gpio", "audio", "auto"):
            with self.subTest(backend=backend):
                result = self.invoke("notice", "--backend", backend, "--repeat", "3",
                                     "--pause", "0")
                self.assertEqual(result.returncode, 0, result.stderr)
        log = (Path(self.temp.name) / "backend.log").read_text()
        self.assertIn("skipped=muted", log)

    def test_legacy_silent_mutes_direct_audio(self):
        (self.hook / "silent").touch()
        result = self.invoke("ok", "--backend", "audio", "--repeat", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped=muted", (Path(self.temp.name) / "backend.log").read_text())

    def test_muted_event_does_not_play_motif(self):
        self.mute.touch()
        result = self.invoke("--event", "SessionStart", "--source", "codex",
                             "--backend", "audio", "--repeat", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = Path(self.temp.name) / "backend.log"
        self.assertIn("skipped=muted", log.read_text())

    def test_mute_does_not_suppress_readonly_dry_run(self):
        self.mute.touch()
        result = self.invoke("notice", "--repeat", "3", "--pause", "0", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
