"""Offline tests for opt-in SHA-pinned release installation and failure recovery."""
import importlib.util
from pathlib import Path
import subprocess
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deploy/install-mcp-release.py"
spec = importlib.util.spec_from_file_location("mcp_release_installer", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    for name in installer.REQUIRED:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    dependency = source / "scripts/gway/sound_engine/events.py"
    dependency.parent.mkdir(parents=True, exist_ok=True)
    dependency.write_text("EVENT = 1\\n")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"], check=True)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    return source, revision


def test_install_second_convergence_and_tamper_detection(tmp_path):
    source, revision = repo(tmp_path)
    releases = tmp_path / "releases"
    assert installer.install(source, releases, revision) is True
    assert (releases / revision / "scripts/gway/sound_engine/events.py").is_file()
    assert installer.install(source, releases, revision) is False
    assert not list(releases.glob(".staging.*"))
    (releases / revision / installer.REQUIRED[0]).write_text("tampered")
    with pytest.raises(ValueError, match="modified_existing_release"):
        installer.install(source, releases, revision)


def test_reject_mismatched_sha_and_symlink_root(tmp_path):
    source, revision = repo(tmp_path)
    releases = tmp_path / "releases"
    with pytest.raises(ValueError, match="revision_mismatch"):
        installer.install(source, releases, "0" * 40 if revision != "0" * 40 else "1" * 40)
    with pytest.raises(ValueError, match="invalid_full_sha"):
        installer.install(source, releases, revision[:12])
    root = tmp_path / "linked"
    root.symlink_to(releases, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinked_release_root"):
        installer.install(source, root, revision)


def test_failure_before_promotion_keeps_previous_release(tmp_path, monkeypatch):
    source, revision = repo(tmp_path)
    releases = tmp_path / "releases"
    assert installer.install(source, releases, revision)
    prior = sorted(p.name for p in releases.iterdir())
    (source / installer.REQUIRED[0]).write_text("updated release")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "second"], check=True)
    revision2 = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    original = installer.check
    def fail_on_staging(root):
        if root.name.startswith(".staging."):
            raise RuntimeError("injected_validation_failure")
        return original(root)
    monkeypatch.setattr(installer, "check", fail_on_staging)
    with pytest.raises(RuntimeError, match="injected_validation_failure"):
        installer.install(source, releases, revision2)
    assert sorted(p.name for p in releases.iterdir()) == prior
