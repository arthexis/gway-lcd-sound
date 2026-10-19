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
    (checkout / "docs" / "man").mkdir(parents=True)
    shutil.copytree(ROOT / "docs" / "man" / "man1", checkout / "docs" / "man" / "man1")
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
           "GWAY_LCD_SOUND_MAN_DIR": str(tmp_path / "man"),
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

    def run_raw(action, version):
        return subprocess.run(
            ["bash", str(installer), action, "--no-restart"],
            env={**env, "TEST_RELEASE": version}, text=True,
            capture_output=True, timeout=30,
        )

    run("install", "first")
    run("verify", "first")
    assert (tmp_path / "bin" / "lcd-lockfile-runner").is_symlink()
    assert (tmp_path / "bin" / "gway-lcd-sound").is_symlink()
    assert (tmp_path / "man" / "gway-lcd-sound.1").is_symlink()
    assert "first" in str((tmp_path / "installed" / "current").resolve())
    # A retained independent legacy helper is reported but never overwritten.
    legacy = tmp_path / "bin" / "gway-system-notify"
    legacy.write_text("#!/bin/sh\nexit 0\n")
    legacy.chmod(0o700)
    verify_with_legacy = run_raw("verify", "first")
    assert verify_with_legacy.returncode == 0, verify_with_legacy.stdout + verify_with_legacy.stderr
    assert "stale independent legacy helper retained" in verify_with_legacy.stderr
    assert not legacy.is_symlink()
    # Verification catches a divergent stable dispatcher link; reactivation repairs it.
    dispatcher = tmp_path / "bin" / "gway-lcd-sound"
    dispatcher.unlink()
    dispatcher.symlink_to("/not-a-release-owned-dispatcher")
    divergent = run_raw("verify", "first")
    assert divergent.returncode != 0
    assert "Missing installed command: gway-lcd-sound" in divergent.stderr
    run("install", "first")
    assert dispatcher.is_symlink()
    assert "gway-lcd-sound" in os.readlink(dispatcher)
    # A staging validation failure leaves the previous release active.
    discovery = checkout / "scripts" / "gway" / "lcd_engine" / "hardware" / "discovery.py"
    original_discovery = discovery.read_text()
    discovery.write_text("this is not valid Python\n")
    failed = run_raw("install", "broken")
    assert failed.returncode != 0
    assert "first" in str((tmp_path / "installed" / "current").resolve())
    discovery.write_text(original_discovery)
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
