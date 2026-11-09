"""Offline lock and mute regression tests for one-shot playback."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1] / "scripts" / "gway"
DISPATCHER = ROOT / "gway-lcd-sound"
SEQUENCE = json.dumps({"format": "gway-piano-v1", "notes": [[440, .1, 0]]})

def test_lock_directory_symlink_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "gway-sound").symlink_to(target, target_is_directory=True)
    env = dict(os.environ, XDG_RUNTIME_DIR=str(tmp_path))
    result = subprocess.run(["bash", str(DISPATCHER), "sound", "play", "--sequence", SEQUENCE, "--dry-run"],
                            capture_output=True, text=True, env=env, timeout=10)
    assert result.returncode != 0
    assert "unsafe sound lock directory" in result.stderr

def test_lock_file_symlink_rejected(tmp_path):
    lock_dir = tmp_path / "gway-sound"
    lock_dir.mkdir(mode=0o700)
    (lock_dir / "one-shot.lock").symlink_to(tmp_path / "outside")
    env = dict(os.environ, XDG_RUNTIME_DIR=str(tmp_path))
    result = subprocess.run(["bash", str(DISPATCHER), "sound", "play", "--sequence", SEQUENCE, "--dry-run"],
                            capture_output=True, text=True, env=env, timeout=10)
    assert result.returncode != 0
    assert not (tmp_path / "outside").exists()

def test_exclusive_lock_blocks_other_invocation(tmp_path):
    import fcntl
    lock_dir = tmp_path / "gway-sound"
    lock_dir.mkdir(mode=0o700)
    lock = lock_dir / "one-shot.lock"
    with lock.open("w+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        env = dict(os.environ, XDG_RUNTIME_DIR=str(tmp_path))
        child = subprocess.Popen(["bash", str(DISPATCHER), "sound", "play", "--sequence", SEQUENCE, "--dry-run"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            time.sleep(.25)
            assert child.poll() is None, "playback must wait for the existing lock"
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
            stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
        assert "440" in stdout
