#!/usr/bin/env python3
"""Safe user-owned LCD overlay; never writes directly to I2C hardware."""
import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lcd")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    show = sub.add_parser("show")
    show.add_argument("line1")
    show.add_argument("line2", nargs="?", default="")
    show.add_argument("--seconds", type=int, default=30)
    sub.add_parser("clear")
    args = parser.parse_args(argv)
    root = Path(os.environ.get("GWAY_LCD_LOCK_DIR", str(Path.home() / ".local/state/lcd-lockfiles")))
    path = root / "lcd-high-9000"
    if args.action == "status":
        print(json.dumps({"overlay": path.is_file() and not path.is_symlink(), "path": str(path)}))
        return 0
    if args.action == "show":
        if not 1 <= args.seconds <= 300:
            parser.error("--seconds must be between 1 and 300")
        lines = [args.line1, args.line2]
        if any(len(s) > 160 or "\\n" in s or "\\r" in s or any(ord(c) < 32 for c in s) for s in lines):
            parser.error("LCD lines must be printable and at most 160 characters")
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or path.is_symlink():
            parser.error("unsafe LCD lockfile path")
        expires = (datetime.now(timezone.utc) + timedelta(seconds=args.seconds)).isoformat()
        tmp = root / f".lcd-high-9000.{os.getpid()}.tmp"
        try:
            with tmp.open("x", encoding="utf-8") as out:
                out.write(f"{lines[0]}\\n{lines[1]}\\n{expires}\\n")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        if path.is_symlink():
            parser.error("unsafe LCD lockfile path")
        path.unlink(missing_ok=True)
    print(json.dumps({"action": args.action, "ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
