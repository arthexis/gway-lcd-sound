"""Installer acceptance tests: real installed entry points, revision switch, rollback."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_versioned_install_verify_and_rollback(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "scripts" / "deploy").mkdir(parents=True)
    shutil.copytree(ROOT / "scripts" / "gway", checkout / "scripts" / "gway")
    shutil.copy2(ROOT / "scripts" / "deploy" / "install.sh",
                 checkout / "scripts" / "deploy" / "install.sh")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    git = fakebin / "git"
    git.write_text('#!/bin/sh\necho "$TEST_RELEASE"\n')
    git.chmod(0o755)
    env = {**os.environ,
           "HOME": str(tmp_path),
           "GWAY_LCD_SOUND_PREFIX": str(tmp_path / "installed"),
           "GWAY_LCD_SOUND_BIN_DIR": str(tmp_path / "bin"),
           "PATH": str(fakebin) + os.pathsep + os.environ["PATH"]}
    installer = checkout / "scripts" / "deploy" / "install.sh"

    def run(action, version):
        result = subprocess.run(
            ["bash", str(installer), action, "--no-restart"],
            env={**env, "TEST_RELEASE": version}, text=True,
            capture_output=True, timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    run("install", "first")
    run("verify", "first")
    assert (tmp_path / "bin" / "lcd-lockfile-runner").is_symlink()
    assert "first" in str((tmp_path / "installed" / "current").resolve())
    # Create the next checkout/release with a changed source file.
    (checkout / "scripts" / "gway" / "lcd-actions-runner-status").write_text(
        (checkout / "scripts" / "gway" / "lcd-actions-runner-status").read_text()
        + "\n# test revision\n"
    )
    run("install", "second")
    assert "second" in str((tmp_path / "installed" / "current").resolve())
    run("rollback", "second")
    assert "first" in str((tmp_path / "installed" / "current").resolve())
    run("verify", "first")
