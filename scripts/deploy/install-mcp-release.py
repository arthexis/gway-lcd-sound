#!/usr/bin/env python3
"""Opt-in immutable MCP release installer; never activates or publishes a provider."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

REQUIRED = ("scripts/gway/lcd-sound-mcp", "scripts/gway/lcd_sound_mcp.py", "scripts/gway/gway-lcd-sound",
            "scripts/gway/lcd_control.py", "scripts/gway/sound.sh")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def digest(root):
    """Hash all release files, not only entrypoints and their direct dependencies."""
    h = hashlib.sha256()
    for path in sorted((root / "scripts/gway").rglob("*")):
        if path.is_symlink():
            raise ValueError("symlinked_release_content")
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        data = path.read_bytes()
        h.update(name.encode() + bytes([0]) + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def check(root):
    for name in REQUIRED:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing_or_symlinked_release_file:" + name)
    if not os.access(root / REQUIRED[0], os.X_OK):
        raise ValueError("dispatcher_not_executable")


def install(source, releases, revision):
    source, releases = Path(source).resolve(), Path(releases)
    if not SHA.fullmatch(revision):
        raise ValueError("invalid_full_sha")
    if releases.is_symlink():
        raise ValueError("symlinked_release_root")
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != revision:
        raise ValueError("revision_mismatch")
    releases.mkdir(parents=True, exist_ok=True)
    if releases.is_symlink():
        raise ValueError("symlinked_release_root")
    destination = releases / revision
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("invalid_existing_release")
        check(destination)
        marker = destination / ".mcp-release-digest"
        if not marker.is_file() or marker.is_symlink() or marker.read_text().strip() != digest(destination):
            raise ValueError("modified_existing_release")
        return False
    with tempfile.TemporaryDirectory(prefix=".staging.", dir=releases) as stage:
        staged = Path(stage)
        archive = subprocess.check_output(["git", "-C", str(source), "archive", "--format=tar", revision])
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if member.name.startswith("/") or ".." in parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                    raise ValueError("unsafe_archive_entry")
                if member.name not in ("scripts", "scripts/gway") and not member.name.startswith("scripts/gway/"):
                    continue
                target = staged / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(tar.extractfile(member).read())
                    target.chmod(member.mode & 0o755)
        (staged / REQUIRED[0]).chmod(0o755)
        (staged / "scripts/gway/gway-lcd-sound").chmod(0o755)
        check(staged)
        (staged / ".mcp-release-digest").write_text(digest(staged) + "\n")
        # Publish only after every validation succeeds; same filesystem atomic rename.
        os.rename(staged, destination)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--releases", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print("installed" if install(args.source, args.releases, args.revision) else "unchanged")


if __name__ == "__main__":
    main()
