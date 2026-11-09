"""End-to-end offline one-shot CLI contract (no audio hardware)."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1] / "scripts" / "gway"
DISPATCHER = ROOT / "gway-lcd-sound"
SEQUENCE = json.dumps({"format": "gway-piano-v1", "notes": [[440, 0.1, 0.02], [0, 0.05, 0]]})

def run(tmp_path, *args):
    env = dict(os.environ, XDG_RUNTIME_DIR=str(tmp_path), GWAY_SOUND_EVENT_DB=str(tmp_path / "unused.sqlite3"))
    return subprocess.run(["bash", str(DISPATCHER), "sound", "play", *args],
                          capture_output=True, text=True, timeout=10, env=env)

def test_sequence_dry_run_has_no_database_or_audio(tmp_path):
    result = run(tmp_path, "--sequence", SEQUENCE, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "440.0Hz" in result.stdout
    assert not (tmp_path / "unused.sqlite3").exists()

def test_sequence_invalid_rejected_without_database(tmp_path):
    result = run(tmp_path, "--sequence", '{"format":"gway-piano-v1","notes":[]}', "--dry-run")
    assert result.returncode != 0
    assert not (tmp_path / "unused.sqlite3").exists()

def test_sequence_rejects_unexpected_flags(tmp_path):
    result = run(tmp_path, "--sequence", SEQUENCE, "--backend", "audio")
    assert result.returncode != 0

def test_existing_named_cue_dry_run(tmp_path):
    result = run(tmp_path, "ok", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "1047Hz" in result.stdout

def test_muted_sequence_is_silent_and_does_not_write_db(tmp_path):
    lock_dir = tmp_path / "gway-sound"
    lock_dir.mkdir(mode=0o700)
    (lock_dir / "gpio-muted").write_text("muted\\n")
    env = dict(os.environ, XDG_RUNTIME_DIR=str(tmp_path),
               GWAY_SOUND_EVENT_DB=str(tmp_path / "unused.sqlite3"),
               GWAY_SOUND_BACKEND_LOG=str(tmp_path / "backend.log"))
    result = subprocess.run(["bash", str(DISPATCHER), "sound", "play", "--sequence", SEQUENCE],
                            capture_output=True, text=True, timeout=10, env=env)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "unused.sqlite3").exists()
    assert "skipped=muted" in (tmp_path / "backend.log").read_text()
