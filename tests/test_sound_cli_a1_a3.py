"""Hardware-free end-to-end CLI compatibility checks."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts/gway"

def cli(tmp_path, executable, *args):
    env = dict(os.environ,
               GWAY_SOUND_GPIO_MUTE_FILE=str(tmp_path/"run"/"gpio-muted"),
               CODEX_SOUND_HOOK_STATE_DIR=str(tmp_path/"codex"),
               XDG_RUNTIME_DIR=str(tmp_path/"run"))
    return subprocess.run(["bash", str(SCRIPTS/executable), *args],
                          env=env, text=True, capture_output=True)

def test_sound_and_legacy_dispatcher_share_state(tmp_path):
    assert cli(tmp_path, "sound.sh", "status").stdout.strip() == "unmuted"
    assert cli(tmp_path, "sound.sh", "mute").stdout.strip() == "muted"
    assert cli(tmp_path, "gway-lcd-sound", "mute", "toggle", "--status").stdout.strip() == "muted"
    assert cli(tmp_path, "sound.sh", "unmute").stdout.strip() == "unmuted"
    assert cli(tmp_path, "sound.sh", "toggle", "--json").returncode == 0
    assert json.loads(cli(tmp_path, "sound.sh", "status", "--json").stdout)["muted"]

def test_sound_legacy_vocabulary(tmp_path):
    assert "ok" in cli(tmp_path, "sound.sh", "list").stdout
    assert cli(tmp_path, "sound.sh", "ok", "--dry-run").returncode == 0
    assert cli(tmp_path, "sound.sh", "bogus").returncode == 2

def test_status_does_not_create_state(tmp_path):
    assert cli(tmp_path, "sound.sh", "status", "--json").returncode == 0
    assert not (tmp_path/"run").exists()
