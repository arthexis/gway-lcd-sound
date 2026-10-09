#!/usr/bin/env python3
"""Publish host information to the established standalone LCD lockfiles."""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lcd_engine.system_info import collectors, formatting, publishing
from lcd_engine.system_info.model import Frame

DEFAULT_LOCK_DIR = collectors.DEFAULT_LOCK_DIR
ROTATION_SCRIPT_NAME = publishing.ROTATION_SCRIPT_NAME
CHANNELS_NAME = publishing.CHANNELS_NAME
STATUS_NAME = publishing.STATUS_NAME
render_rotation_script = publishing.render_rotation_script
atomic_write = publishing.atomic_write


def build_frames() -> list[Frame]:
    return formatting.build_frames(collectors.collect_snapshot())


def publish(lock_dir: Path, *, dry_run: bool = False) -> list[Frame]:
    return publishing.publish(lock_dir, frames=build_frames(), dry_run=dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish system info frames for lcd-lockfile-runner.")
    parser.add_argument("--lock-dir", type=Path, default=Path(os.environ.get("LCD_SYSTEM_INFO_LOCK_DIR", DEFAULT_LOCK_DIR)))
    parser.add_argument("--dry-run", action="store_true", help="Print generated frames without writing lockfiles.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    frames = publish(args.lock_dir.expanduser(), dry_run=args.dry_run)
    for index, frame in enumerate(frames, 1):
        print(f"{index:02d} {frame.key}: {frame.line1} / {frame.line2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
