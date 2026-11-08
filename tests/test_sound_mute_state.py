import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/gway/sound_engine/mute.py"

def run(tmp_path, *args):
    env = dict(os.environ, GWAY_SOUND_GPIO_MUTE_FILE=str(tmp_path/"runtime"/"gpio-muted"),
               CODEX_SOUND_HOOK_STATE_DIR=str(tmp_path/"codex"))
    return subprocess.run([sys.executable, str(MODULE), *args], env=env,
                          text=True, capture_output=True)

def test_status_read_only(tmp_path):
    result = run(tmp_path, "status", "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["muted"] is False
    assert not (tmp_path/"runtime").exists()

def test_persistent_idempotent_and_toggle(tmp_path):
    assert run(tmp_path, "mute").stdout.strip() == "muted"
    assert run(tmp_path, "mute").stdout.strip() == "muted"
    assert (tmp_path/"runtime"/"gpio-muted").exists()
    assert run(tmp_path, "toggle").stdout.strip() == "unmuted"
    assert run(tmp_path, "unmute").stdout.strip() == "unmuted"
    assert run(tmp_path, "toggle").stdout.strip() == "muted"

def test_legacy_markers(tmp_path):
    marker = tmp_path/"codex"/"silent"
    marker.parent.mkdir()
    marker.touch()
    assert json.loads(run(tmp_path, "status", "--json").stdout)["legacy_codex_muted"]
    assert run(tmp_path, "unmute").stdout.strip() == "unmuted"
    assert not marker.exists()

def test_invalid_action(tmp_path):
    assert run(tmp_path, "unknown").returncode == 2

def test_runtime_state_disappears_on_simulated_reboot(tmp_path):
    assert run(tmp_path, "mute").stdout.strip() == "muted"
    (tmp_path/"runtime"/"gpio-muted").unlink()
    assert run(tmp_path, "status").stdout.strip() == "unmuted"
