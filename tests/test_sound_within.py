"""Sound cooldown checks use a fake audio player and private state."""
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/gway/sound.sh'


class WithinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        bindir = root / 'bin'
        bindir.mkdir()
        player = bindir / 'paplay'
        player.write_text('#!/bin/sh\nprintf "played\\n" >> "$FAKE_PLAY_LOG"\nexit "${FAKE_EXIT:-0}"\n')
        player.chmod(0o700)
        for alternate in ('pw-play', 'aplay'):
            (bindir / alternate).symlink_to(player)
        pinctrl = bindir / 'pinctrl'
        pinctrl.write_text('#!/bin/sh\nexit 0\n')
        pinctrl.chmod(0o700)
        self.db = root / 'state/events.sqlite3'
        self.log = root / 'plays'
        self.mute = root / 'mute'
        self.env = {**os.environ, 'PATH': str(bindir) + ':/usr/bin:/bin',
                    'GWAY_SOUND_EVENT_DB': str(self.db), 'FAKE_PLAY_LOG': str(self.log),
                    'NODE_SOUND_GPIO_MUTE_FILE': str(self.mute),
                    'CODEX_SOUND_HOOK_STATE_DIR': str(root / 'legacy'),
                    'GWAY_SOUND_BACKEND_LOG': str(root / 'backend.log')}

    def invoke(self, *args, env=None):
        return subprocess.run(['bash', str(SCRIPT), *args, '--backend', 'audio'],
                              env=env or self.env, capture_output=True, text=True, timeout=15)

    def count(self):
        return len(self.log.read_text().splitlines()) if self.log.exists() else 0

    def test_same_sound_suppressed_different_sound_and_expiration(self):
        for sound in ('ok', 'ok', 'warning'):
            self.assertEqual(self.invoke(sound, '--within', '30').returncode, 0)
        self.assertEqual(self.count(), 2)
        with sqlite3.connect(self.db) as db:
            db.execute('update sound_within set played_at=? where sound=?', (time.time()-31, '["ok",null]'))
        self.assertEqual(self.invoke('ok', '--within', '30').returncode, 0)
        self.assertEqual(self.count(), 3)

    def test_sound_and_motif_form_identity(self):
        self.assertEqual(self.invoke('ok', '--within', '60').returncode, 0)
        self.assertEqual(self.invoke('ok', '--within', '60', '--motif', 'gway-remote').returncode, 0)
        self.assertEqual(self.invoke('--event', 'deploy-verified', '--source', 'gway-remote', '--within', '60').returncode, 0)
        self.assertEqual(self.invoke('ok', '--within', '60', '--motif', 'github').returncode, 0)
        self.assertEqual(self.count(), 5)  # direct, remote motif + sound, github motif + sound

    def test_non_opt_in_playback_ignores_existing_window(self):
        self.invoke('ok', '--motif', 'mcp', '--within', '20')
        before = self.count()
        self.invoke('ok', '--motif', 'mcp')
        self.assertEqual(self.count(), before + 2)  # explicit motif and sound
        self.invoke('ok', '--motif', 'mcp', '--within', '20')
        self.assertEqual(self.count(), before + 2)

    def test_mcp_hook_events_use_dedicated_motif(self):
        self.invoke('--event', 'tool-started', '--source', 'mcp', '--within', '20')
        self.invoke('--event', 'tool-started', '--source', 'mcp', '--within', '20')
        self.invoke('--event', 'tool-finished', '--source', 'mcp', '--within', '20')
        self.invoke('--event', 'tool-finished', '--source', 'mcp', '--within', '20')
        self.assertEqual(self.count(), 3)  # motif, start and finish

    def test_repeat_is_one_invocation(self):
        self.invoke('ok', '--within', '30', '--repeat', '3', '--pause', '0')
        self.invoke('ok', '--within', '30', '--repeat', '3', '--pause', '0')
        self.assertEqual(self.count(), 3)

    def test_muted_and_dry_run_do_not_start_window(self):
        self.mute.touch()
        self.invoke('ok', '--within', '30')
        self.mute.unlink()
        self.invoke('ok', '--within', '30', '--dry-run')
        self.invoke('ok', '--within', '30')
        self.assertEqual(self.count(), 1)

    def test_failed_playback_does_not_start_window(self):
        failed = self.invoke('ok', '--within', '30', env={**self.env, 'FAKE_EXIT': '1'})
        self.assertNotEqual(failed.returncode, 0)
        before = self.count()
        self.assertEqual(self.invoke('ok', '--within', '30').returncode, 0)
        self.assertGreater(self.count(), before)

    def test_concurrent_calls_are_atomic(self):
        command = ['bash', str(SCRIPT), 'ok', '--within', '30', '--backend', 'audio']
        processes = [subprocess.Popen(command, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for _ in range(5)]
        for process in processes:
            _, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stderr.decode())
        self.assertEqual(self.count(), 1)

    def test_invalid_values_and_unsupported_modes(self):
        for value in ('-1', 'nan', 'inf', '86401'):
            self.assertNotEqual(self.invoke('ok', '--within', value).returncode, 0)
        self.assertNotEqual(self.invoke('all', '--within', '30', '--dry-run').returncode, 0)
        self.assertNotEqual(self.invoke('--event', 'Stop', '--resolve', '--within', '30').returncode, 0)
