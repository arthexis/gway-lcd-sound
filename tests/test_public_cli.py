"""Hermetic public sound/lcd entrypoints and installer collision/rollback tests.

No receiver, transport, GPIO, LCD, credentials or production services are used.
"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "gway"
INSTALLER = ROOT / "scripts" / "deploy" / "install.sh"


@pytest.mark.parametrize(("entry", "argv", "expected"), [
    ("gway-sound-route", ["notice"], ["sound", "play", "notice"]),
    ("gway-sound-route", ["play", "notice"], ["sound", "play", "notice"]),
    ("gway-sound-route", ["status", "--json"], ["sound", "status", "--json"]),
    ("gway-sound-route", ["--event", "deploy-verified", "--source", "gway-remote"],
     ["sound", "event", "deploy-verified", "gway-remote"]),
    ("gway-sound-route", ["--sequence", '{"schema":1}'], ["sound", "play", "--sequence", '{"schema":1}']),
    ("gway-lcd-route", ["show", "Hello", "World", "--seconds", "15"],
     ["lcd", "show", "Hello", "World", "--seconds", "15"]),
    ("gway-lcd-route", ["status"], ["lcd", "status"]),
])
def test_public_command_grammar_without_hardware(tmp_path, entry, argv, expected):
    release = tmp_path / "release"
    release.mkdir()
    shutil.copy2(SCRIPTS / entry, release / entry)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$PUBLIC_COMMAND_ARGS"\n')
    fake_python.chmod(0o755)
    observed = tmp_path / "observed"
    env = dict(os.environ, PUBLIC_COMMAND_ARGS=str(observed),
               PATH=str(fake_bin) + os.pathsep + os.environ["PATH"])
    proc = subprocess.run(["bash", str(release / entry), *argv], env=env,
                          capture_output=True, text=True, timeout=10, check=False)
    assert proc.returncode == 0, proc.stderr
    arguments = observed.read_text().splitlines()
    assert arguments[0] == str(release / "route_send.py")
    assert arguments[1:] == expected


def _installer_environment(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    stub = fake_bin / "systemctl"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    prefix = tmp_path / "releases"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = dict(os.environ, HOME=str(home),
               GWAY_LCD_SOUND_PREFIX=str(prefix),
               GWAY_LCD_SOUND_BIN_DIR=str(bin_dir),
               GWAY_LCD_SOUND_UNIT_DIR=str(tmp_path / "systemd"),
               GWAY_LCD_SOUND_MAN_DIR=str(tmp_path / "man"),
               PATH=str(fake_bin) + os.pathsep + os.environ["PATH"])
    return env, prefix, bin_dir


def _install(env, action):
    proc = subprocess.run(["bash", str(INSTALLER), action, "--no-restart"],
                          env=env, cwd=ROOT, capture_output=True, text=True,
                          timeout=90, check=False)
    assert proc.returncode == 0, f"{action}: {proc.stdout}\n{proc.stderr}"


def test_install_public_names_and_rollback_to_pre_alias_release(tmp_path):
    env, prefix, bin_dir = _installer_environment(tmp_path)
    _install(env, "install")
    for name, shim in (("sound", "gway-sound-route"), ("lcd", "gway-lcd-route")):
        assert (bin_dir / name).is_symlink()
        assert (bin_dir / name).readlink() == prefix / "current" / "scripts" / "gway" / shim
    _install(env, "verify")

    old = prefix / "releases" / "pre-public-contract"
    shutil.copytree((prefix / "current").resolve(), old)
    (old / "scripts" / "gway" / ".transparent-public-cli-v1").unlink()
    (prefix / "previous").symlink_to(old)
    _install(env, "rollback")
    assert not (bin_dir / "sound").exists()
    assert not (bin_dir / "lcd").exists()


def test_preexisting_public_sound_is_never_overwritten(tmp_path):
    env, prefix, bin_dir = _installer_environment(tmp_path)
    (bin_dir / "sound").symlink_to("/bin/true")
    _install(env, "install")
    assert (bin_dir / "sound").readlink() == Path("/bin/true")
    assert (bin_dir / "lcd").is_symlink()
    _install(env, "verify")

    old = prefix / "releases" / "pre-public-contract"
    shutil.copytree((prefix / "current").resolve(), old)
    (old / "scripts" / "gway" / ".transparent-public-cli-v1").unlink()
    (prefix / "previous").symlink_to(old)
    _install(env, "rollback")
    assert (bin_dir / "sound").readlink() == Path("/bin/true")
    assert not (bin_dir / "lcd").exists()
