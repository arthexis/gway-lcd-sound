"""User-level sound migration is opt-in and reversible; never touches system command."""
import os
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deploy/migrate-sound-command.sh"

def fixture(tmp_path):
    home = tmp_path / "home"
    bindir = home / ".local/bin"
    bindir.mkdir(parents=True)
    prefix = home / ".local/share/gway-lcd-sound"
    target = prefix / "current/scripts/gway/sound.sh"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho new\n")
    target.chmod(0o755)
    original = tmp_path / "system-sound"
    original.write_text("#!/bin/sh\necho old\n")
    original.chmod(0o755)
    link = bindir / "sound"
    link.symlink_to(original)
    env = dict(os.environ, HOME=str(home), GWAY_SOUND_ORIGINAL_COMMAND=str(original))
    def run(action):
        return subprocess.run(["bash", str(SCRIPT), action], env=env,
                              capture_output=True, text=True)
    return run, link, original, target, home

def test_adopt_verify_idempotent_and_rollback(tmp_path):
    run, link, original, target, home = fixture(tmp_path)
    assert run("inspect").returncode == 0
    assert link.resolve() == original
    assert run("adopt").returncode == 0
    assert link.resolve() == target
    assert run("adopt").returncode == 0
    assert run("verify").returncode == 0
    assert subprocess.check_output([str(link)], text=True).strip() == "new"
    assert run("rollback").returncode == 0
    assert link.resolve() == original
    assert subprocess.check_output([str(link)], text=True).strip() == "old"
    assert run("verify").returncode != 0
    assert original.read_text().endswith("old\n")

def test_refuses_unexpected_owner_and_changed_link(tmp_path):
    run, link, original, target, home = fixture(tmp_path)
    link.unlink()
    link.symlink_to(target)
    assert run("adopt").returncode != 0
    link.unlink()
    link.symlink_to(original)
    assert run("adopt").returncode == 0
    link.unlink()
    link.symlink_to(original)
    assert run("rollback").returncode != 0
    assert link.resolve() == original

def test_refuses_missing_release(tmp_path):
    run, link, original, target, home = fixture(tmp_path)
    target.unlink()
    assert run("adopt").returncode != 0
    assert link.resolve() == original
