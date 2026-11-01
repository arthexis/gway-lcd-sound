"""Bounded owner-managed immutable release pruning. No service or data operations."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat

OWNER = "gway-lcd-sound"
NAME = re.compile("[0-9a-f]{12}")
HAS_PREVIOUS = True
LIMIT = 64


def directory(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError(f"unsafe owner directory: {path}")
    return info


def pointer(root: Path, name: str, *, optional: bool = False) -> Path | None:
    link = root / name
    if not link.is_symlink():
        if optional and not link.exists():
            return None
        raise ValueError(f"missing or non-symlink {name}")
    target = link.resolve(strict=True)
    if target.parent != root / "releases" or not NAME.fullmatch(target.name):
        raise ValueError(f"unsafe {name} target")
    directory(target)
    return target


def inventory(root: Path) -> dict:
    report = {"owner": OWNER, "root": str(root), "dry_run": True,
              "protected": [], "candidates": [], "legacy": [], "errors": []}
    try:
        directory(root)
        releases = root / "releases"
        directory(releases)
        current = pointer(root, "current")
        previous = pointer(root, "previous", optional=not HAS_PREVIOUS)
        protected = {current: ["current"]}
        if previous is not None:
            protected.setdefault(previous, []).append("previous")
        entries = sorted(releases.iterdir())
        if len(entries) > 4096:
            raise ValueError("release inventory limit exceeded")
        for path in entries:
            info = path.lstat()
            if not NAME.fullmatch(path.name):
                report["legacy"].append({"name": path.name, "reason": "unrecognized/staging"})
                continue
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise ValueError(f"unsafe release directory: {path.name}")
            item = {"name": path.name, "identity": [info.st_dev, info.st_ino]}
            if path in protected:
                item["reasons"] = protected[path]
                report["protected"].append(item)
            else:
                report["candidates"].append(item)
        if report["legacy"]:
            report["errors"].append("unrecognized or in-progress release entries present")
    except (OSError, ValueError) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        report["candidates"] = []
    report["status"] = "blocked" if report["errors"] else "candidates_ready"
    return report


def execute(root: Path, *, limit: int = LIMIT) -> dict:
    plan = inventory(root)
    receipt = {"owner": OWNER, "root": str(root), "dry_run": False,
               "status": "blocked", "protected": plan["protected"],
               "deleted": [], "skipped": [], "errors": list(plan["errors"])}
    if receipt["errors"]:
        return receipt
    if not shutil.rmtree.avoids_symlink_attacks:
        receipt["errors"].append("safe directory removal unavailable")
        return receipt
    if len(plan["candidates"]) > limit:
        receipt["errors"].append(f"candidate limit {limit} exceeded")
        return receipt
    for candidate in plan["candidates"]:
        fresh = inventory(root)
        if fresh["errors"]:
            receipt["errors"].extend(fresh["errors"])
            break
        match = next((r for r in fresh["candidates"] if r["name"] == candidate["name"]), None)
        if match != candidate:
            receipt["skipped"].append(candidate["name"])
            continue
        path = root / "releases" / candidate["name"]
        try:
            entry = directory(path)
            if [entry.st_dev, entry.st_ino] != candidate["identity"]:
                raise ValueError("release identity changed")
            shutil.rmtree(path)
            receipt["deleted"].append(candidate["name"])
        except (OSError, ValueError) as exc:
            receipt["errors"].append(f"{candidate['name']}: {type(exc).__name__}: {exc}")
            break
    receipt["status"] = "partial" if receipt["errors"] else "completed"
    return receipt


def format_result(report: dict) -> str:
    applied = "deleted" in report
    lines = [f"{OWNER} release retention — {'apply' if applied else 'dry-run'}",
             f"Root: {report['root']}",
             f"Status: {report['status']} | Protected: {len(report['protected'])} | "
             f"Candidates: {len(report.get('candidates', []))} | "
             f"Legacy: {len(report.get('legacy', []))}", ""]
    for label, items in (("Protected", report["protected"]),
                         ("Deletion candidates", report.get("candidates", [])),
                         ("Legacy (not eligible)", report.get("legacy", []))):
        if items:
            lines.append(label + ":")
            lines.extend("  " + item["name"] +
                         (" (" + ", ".join(item["reasons"]) + ")" if item.get("reasons") else "")
                         for item in items)
            lines.append("")
    if report["errors"]:
        lines.append("Blocking errors:")
        lines.extend("  - " + error for error in report["errors"])
    if applied:
        lines.append(f"Deleted {len(report['deleted'])} release(s).")
        lines.extend("  " + name for name in report["deleted"])
        lines.extend("  skipped " + name for name in report["skipped"])
    else:
        lines.append("No releases deleted (dry-run).")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Owner-managed release pruning")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error("run as release owner, not root")
    root = Path.home() / ".local/share" / OWNER
    # Shared with canonical deployment and any direct installer.
    state = Path.home() / ".local/state" / OWNER
    if state.is_symlink() or state.parent.is_symlink():
        parser.error("unsafe lock directory")
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "deploy.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            parser.error("unsafe deployment lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("deployment or pruning already in progress")
        result = execute(root) if args.apply else inventory(root)
    finally:
        os.close(fd)
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_result(result))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
