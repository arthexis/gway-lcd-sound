"""Offline LCD overlay contracts: no I2C or service dependencies."""
import json
import os
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/gway/lcd_control.py"


def call(tmp_path, *args):
    env = dict(os.environ, GWAY_LCD_LOCK_DIR=str(tmp_path / "locks"))
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, text=True, capture_output=True)


def test_show_status_clear(tmp_path):
    assert call(tmp_path, "status").returncode == 0
    assert call(tmp_path, "show", "Hello", "World", "--seconds", "15").returncode == 0
    overlay = tmp_path / "locks" / "lcd-high-9000"
    assert overlay.read_text().splitlines()[:2] == ["Hello", "World"]
    assert json.loads(call(tmp_path, "status").stdout)["overlay"] is True
    assert call(tmp_path, "clear").returncode == 0
    assert not overlay.exists()


def test_rejects_invalid_lines_and_ttl(tmp_path):
    assert call(tmp_path, "show", "bad\nline").returncode != 0
    assert call(tmp_path, "show", "x", "--seconds", "301").returncode != 0
    assert call(tmp_path, "show", "x" * 161).returncode != 0


def test_clear_does_not_remove_other_producers(tmp_path):
    root = tmp_path / "locks"
    root.mkdir()
    (root / "lcd-high").write_text("owner")
    assert call(tmp_path, "clear").returncode == 0
    assert (root / "lcd-high").read_text() == "owner"


def test_rejects_symlink_overlay(tmp_path):
    root = tmp_path / "locks"
    root.mkdir()
    target = tmp_path / "other"
    target.write_text("safe")
    (root / "lcd-high-9000").symlink_to(target)
    assert call(tmp_path, "show", "hello").returncode != 0
    assert call(tmp_path, "clear").returncode != 0
    assert target.read_text() == "safe"
