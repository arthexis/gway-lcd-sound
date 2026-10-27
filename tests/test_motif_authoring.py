"""Contract tests for the supported motif CLI (hardware-free)."""
import json
import os
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/gway/sound.sh"
NOTES = "[[440,0.06,0.02],[0,0.04,0]]"


def run(tmp_path, *args):
    env = os.environ.copy()
    env["GWAY_SOUND_EVENT_DB"] = str(tmp_path / "events.sqlite3")
    env["GWAY_SOUND_BACKEND_LOG"] = str(tmp_path / "backend.log")
    return subprocess.run(["bash", str(SCRIPT), "motif", *args, "--event-db", env["GWAY_SOUND_EVENT_DB"]],
                          env=env, capture_output=True, text=True)


def test_preview_and_validation_do_not_create_database(tmp_path):
    result = run(tmp_path, "preview", "--notes", NOTES, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "events.sqlite3").exists()
    result = run(tmp_path, "validate", "--notes", NOTES, "--cooldown-seconds", "30")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"]
    assert not (tmp_path / "events.sqlite3").exists()


def test_create_show_list_remove(tmp_path):
    result = run(tmp_path, "set", "my-source", "--notes", NOTES, "--cooldown-seconds", "12")
    assert result.returncode == 0, result.stderr
    result = run(tmp_path, "show", "my-source")
    assert json.loads(result.stdout)["cooldown_seconds"] == 12
    result = run(tmp_path, "list")
    assert "my-source" in [item["source"] for item in json.loads(result.stdout)]
    result = run(tmp_path, "remove", "my-source")
    assert json.loads(result.stdout)["removed"]
    assert run(tmp_path, "show", "my-source").returncode != 0


def test_invalid_notes_and_sources(tmp_path):
    for bad in ('[[NaN,0.1,0]]', '[[440,0.5,0]]', '[[true,0.1,0]]', '[]', '[[440,0.1]]'):
        assert run(tmp_path, "validate", "--notes", bad, "--cooldown-seconds", "30").returncode != 0
    for source in ("../escape", "github-actions", "Bad Source", "*"):
        assert run(tmp_path, "set", source, "--notes", NOTES, "--cooldown-seconds", "30").returncode != 0
    assert run(tmp_path, "set", "valid", "--notes", NOTES, "--cooldown-seconds", "nan").returncode != 0
    assert not (tmp_path / "events.sqlite3").exists()


def test_builtin_delete_prohibited_and_legacy_list(tmp_path):
    assert run(tmp_path, "remove", "codex").returncode != 0
    env = os.environ.copy()
    env["GWAY_SOUND_EVENT_DB"] = str(tmp_path / "events.sqlite3")
    result = subprocess.run(["bash", str(SCRIPT), "--list-motifs"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "codex" in json.loads(result.stdout)
