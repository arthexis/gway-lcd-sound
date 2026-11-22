"""Persistent fail-closed LCD/Sound destination selection (routing control plane).

This module intentionally does not open a network connection or dispatch output.
Data-plane integration is gated on an authorized, structured GWay Remote
receiver; selecting a node must never turn into arbitrary SSH execution.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import tempfile

NODE = re.compile(r"gway-[0-9]{3,}$")
SCHEMA = 1
MAX_CONFIG_BYTES = 2048


class RoutingError(ValueError):
    pass


def config_path():
    return Path(os.environ.get(
        "GWAY_LCD_SOUND_ROUTE_CONFIG",
        str(Path.home() / ".config/gway-lcd-sound/routes.json"),
    ))


def _safe_parent(path, *, create=False):
    if path.is_symlink():
        raise RoutingError("symlinked route file rejected")
    parent = path.parent
    if create:
        # Never follow a symlink for either directory created by this module.
        root = parent.parent
        if root.is_symlink():
            raise RoutingError("symlinked configuration root rejected")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent.mkdir(mode=0o700, exist_ok=True)
    if parent.is_symlink():
        raise RoutingError("symlinked route directory rejected")
    info = parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise RoutingError("route configuration directory must be private and owned")
    return parent


def _validate(value):
    if type(value) is not dict or set(value) != {"schema", "lcd", "sound"} or value["schema"] != SCHEMA:
        raise RoutingError("invalid route config schema")
    for key in ("lcd", "sound"):
        target = value[key]
        if target is not None and (type(target) is not str or not NODE.fullmatch(target)):
            raise RoutingError("invalid route destination")
    return value


def read(path=None):
    path = Path(path or config_path())
    if not path.exists() and not path.is_symlink():
        return {"schema": SCHEMA, "lcd": None, "sound": None}
    _safe_parent(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > MAX_CONFIG_BYTES:
        raise RoutingError("unsafe route config")
    return _validate(json.loads(path.read_text(encoding="utf-8")))


def save(value, path=None):
    value = _validate(value)
    path = Path(path or config_path())
    parent = _safe_parent(path, create=True)
    if path.exists() or path.is_symlink():
        read(path)
    contents = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(contents) > MAX_CONFIG_BYTES:
        raise RoutingError("route config exceeds size limit")
    name = None
    try:
        fd, name = tempfile.mkstemp(dir=parent, prefix=".routes-")
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        name = None
    finally:
        if name is not None:
            os.unlink(name)


def check_enrollment(node):
    """Read only GWay Remote's authoritative, root-owned inventory; never DNS."""
    if not NODE.fullmatch(node):
        raise RoutingError("invalid node name")
    try:
        from gway_remote.node_registry_inventory import load
        inventory = load()
    except (ImportError, OSError, ValueError, PermissionError) as exc:
        raise RoutingError("trusted GWay Remote node inventory unavailable") from exc
    matches = [entry for entry in inventory["nodes"] if entry["node"] == node]
    if len(matches) != 1:
        raise RoutingError("node is not enrolled")
    row = matches[0]
    if not (row["registered"] is True
            and row["identity_verified"] is True
            and row["execute_eligible"] is True
            and row["reachable"] == "reachable"):
        raise RoutingError("node lacks verified execution eligibility/reachability")


def set_route(node, *, lcd=True, sound=True, path=None, enrollment=check_enrollment):
    enrollment(node)
    before = read(path)
    after = dict(before)
    if lcd:
        after["lcd"] = node
    if sound:
        after["sound"] = node
    if after != before:
        save(after, path)
    return {"changed": after != before, **after}


def local(*, lcd=True, sound=True, path=None):
    before = read(path)
    after = dict(before)
    if lcd:
        after["lcd"] = None
    if sound:
        after["sound"] = None
    if after != before:
        save(after, path)
    return {"changed": after != before, **after}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gway-lcd-sound route")
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("set", "local"):
        command = sub.add_parser(name)
        if name == "set":
            command.add_argument("node")
        group = command.add_mutually_exclusive_group()
        group.add_argument("--sound", action="store_true")
        group.add_argument("--lcd", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    sub.add_parser("test")
    args = parser.parse_args(argv)
    try:
        if args.operation in ("set", "local"):
            kwargs = {"lcd": not args.sound, "sound": not args.lcd}
            result = set_route(args.node, **kwargs) if args.operation == "set" else local(**kwargs)
        elif args.operation == "status":
            result = read()
        else:
            # Don't pretend connectivity is verified before the restricted
            # receiver is implemented and admitted through GWay Remote.
            raise RoutingError("remote event transport not yet enabled")
    except (RoutingError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        parser.exit(1, f"route: {exc}\n")
    result["transport"] = "not_enabled"
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
