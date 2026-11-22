"""Location-transparent dispatch for release-owned LCD/Sound commands.

A remote route never falls back to local hardware if dispatch fails. The
privileged GWay Remote bridge owns enrollment/pinned transport verification.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys

import route_config


def event_for(device, args, node, *, origin=None, request_id=None, now=None):
    if device not in ("lcd", "sound"):
        raise ValueError("invalid device")
    origin = origin or socket.gethostname().split(".")[0]
    if not re.fullmatch(r"(watchtower|gway-[0-9]{3,})", origin):
        raise ValueError("unrecognized sender identity")
    if origin == node:
        raise ValueError("self routing prohibited")
    now = now or datetime.now(timezone.utc)
    if device == "lcd":
        if not args or args[0] not in ("show", "clear", "status"):
            raise ValueError("unsupported remote LCD command")
        action = args[0]
        if action == "show":
            if len(args) not in (2, 3, 4, 5):
                raise ValueError("invalid LCD arguments")
            if len(args) >= 4 and (len(args) != 5 or args[3] != "--seconds"):
                raise ValueError("invalid LCD duration arguments")
            arguments = {"line1": args[1], "line2": args[2] if len(args) >= 3 else "",
                         "seconds": int(args[4]) if len(args) == 5 else 30}
        else:
            if len(args) != 1:
                raise ValueError("unexpected LCD arguments")
            arguments = {}
    else:
        if not args:
            raise ValueError("missing sound action")
        cmd = args[0]
        if cmd == "play":
            if len(args) == 3 and args[1] == "--sequence":
                action, arguments = "sequence", {"sequence": args[2]}
            elif len(args) == 2:
                action, arguments = "play", {"name": args[1]}
            else:
                raise ValueError("unsupported remote sound play arguments")
        elif cmd in ("mute", "unmute", "toggle", "status") and len(args) in (1, 2):
            if len(args) == 2 and (cmd != "status" or args[1] != "--json"):
                raise ValueError("unexpected sound arguments")
            action, arguments = cmd, {}
        elif cmd == "event":
            if len(args) not in (3, 5):
                raise ValueError("invalid sound event arguments")
            action, arguments = "event", {"event": args[1], "source": args[2]}
            if len(args) == 5 and args[3] == "--within":
                arguments["within"] = int(args[4])
            elif len(args) == 5:
                raise ValueError("invalid cooldown")
        else:
            raise ValueError("unsupported remote sound command")
    return {"schema": 1, "node": node, "origin": origin,
            "request_id": request_id or secrets.token_hex(16),
            "expires_at": (now + timedelta(seconds=20)).isoformat(),
            "device": device, "action": action, "arguments": arguments, "hops": 0}


def execute(device, args, *, runner=subprocess.run, route=None, here=None):
    if os.environ.get("GWAY_LCD_SOUND_FORCE_LOCAL") == "1":
        target = None
    else:
        routes = route if route is not None else route_config.read()
        target = routes[device]
    here = Path(here or Path(__file__).resolve().parent)
    if target is None:
        if device == "lcd":
            cmd = [sys.executable, str(here / "lcd_control.py"), *args]
        else:
            cmd = ["bash", str(here / "sound.sh"), *args]
        return runner(cmd, check=False).returncode
    # Never run the sender-local hardware command after a failed bridge call.
    payload = event_for(device, list(args), target)
    from json import dumps
    remote = runner(["gway-remote", "lcd-sound", "send"], input=dumps(payload).encode("utf-8"),
                    capture_output=True, timeout=16, check=False)
    if remote.returncode:
        raise RuntimeError("remote delivery failed")
    result = json.loads(remote.stdout)
    if (type(result) is not dict or result.get("node") != target
            or result.get("request_id") != payload["request_id"]
            or result.get("status") != "succeeded"):
        raise RuntimeError("remote delivery unconfirmed")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("lcd", "sound"):
        print("route-send: expected lcd or sound", file=sys.stderr)
        return 64
    try:
        return execute(argv[0], argv[1:])
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired):
        print("route-send: output unavailable (no local fallback)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
