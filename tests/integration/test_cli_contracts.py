"""CLI error paths and hardware-independent dry-run behavior."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "gway"


def test_release_owned_dispatcher_help_and_contracts(tmp_path):
    command = SCRIPTS / "gway-lcd-sound"
    help_result = subprocess.run(["bash", str(command), "--help"], capture_output=True, text=True, timeout=5)
    assert help_result.returncode == 0
    assert "monitor eth0" in help_result.stdout

    invalid = subprocess.run(["bash", str(command), "monitor", "wlan0"], capture_output=True, text=True, timeout=5)
    assert invalid.returncode == 64

    monitor_help = subprocess.run(
        ["bash", str(command), "monitor", "eth0", "--help"], capture_output=True, text=True, timeout=5
    )
    assert monitor_help.returncode == 0
    assert "--interval" in monitor_help.stdout

    mute_status = subprocess.run(
        ["bash", str(command), "mute", "toggle", "--status"],
        env={**os.environ, "XDG_RUNTIME_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert mute_status.returncode == 0
    assert mute_status.stdout.strip() == "unmuted"

    notify_help = subprocess.run(
        ["bash", str(command), "notify", "--help"], capture_output=True, text=True, timeout=5
    )
    assert notify_help.returncode == 0
    assert "--attach" in notify_help.stdout


def test_lcd_runner_rejects_invalid_flag():
    result = subprocess.run([sys.executable, str(SCRIPTS / "lcd_lockfile_runner.py"), "--does-not-exist"],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_runner_lockfile_start_stop_with_no_hardware(tmp_path):
    command = SCRIPTS / "lcd-actions-runner-status"
    env = {**os.environ, "GWAY_LCD_LOCK_DIR": str(tmp_path)}
    start = subprocess.run(["bash", str(command), "start", "812", "feature/long-name"],
                           env=env, capture_output=True, text=True, timeout=5)
    assert start.returncode == 0
    assert (tmp_path / "lcd-actions-runner").read_text().startswith("Run PR #812\n")
    display = subprocess.run([sys.executable, str(SCRIPTS / "lcd_lockfile_runner.py"),
                              "--once", "--dry-run", "--lock-dir", str(tmp_path)],
                             capture_output=True, text=True, timeout=5)
    assert display.returncode == 0
    assert "Run PR #812" in display.stdout
    stop = subprocess.run(["bash", str(command), "stop"], env=env, timeout=5)
    assert stop.returncode == 0
    assert not (tmp_path / "lcd-actions-runner").exists()
