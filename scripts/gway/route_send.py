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



# Public, opt-in playback options; never turn options into shell commands.
SOUND_VALUES = {
    "--volume": ("volume", float), "--repeat": ("repeat", int),
    "--pause": ("pause", float), "--backend": ("backend", str),
    "--device": ("device", str), "--pin": ("pin", int),
    "--motif": ("motif", str), "--within": ("within", float),
}
SOUND_SWITCHES = {"--dry-run": "dry_run", "--resolve": "resolve"}


def _sound_options(raw):
    a = {}
    i = 0
    while i < len(raw):
        arg = raw[i]
        if arg in SOUND_SWITCHES:
            name = SOUND_SWITCHES[arg]
            if name in a:
                raise ValueError("duplicate sound flag")
            a[name] = True
            i += 1
        elif arg in SOUND_VALUES:
            name, convert = SOUND_VALUES[arg]
            if name in a or i + 1 >= len(raw):
                raise ValueError("missing or duplicate sound option")
            try:
                a[name] = convert(raw[i + 1])
            except (ValueError, OverflowError) as exc:
                raise ValueError("invalid sound option") from exc
            i += 2
        else:
            raise ValueError("unsupported sound option")
    import math
    if ("volume" in a and not (math.isfinite(a["volume"]) and 0 <= a["volume"] <= 1)
        or "pause" in a and not (math.isfinite(a["pause"]) and 0 <= a["pause"] <= 3)
        or "within" in a and not (math.isfinite(a["within"]) and 0 <= a["within"] <= 3600)
        or "repeat" in a and not 1 <= a["repeat"] <= 20
        or "backend" in a and a["backend"] not in ("auto", "gpio", "audio")
        or "device" in a and (not re.fullmatch(r"[a-zA-Z0-9_.,:-]{1,64}", a["device"])
                               or a.get("backend") != "audio")
        or "motif" in a and not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", a["motif"])):
        raise ValueError("unsupported sound option value")
    return a


def event_for(device, args, node, *, origin=None, request_id=None, now=None):
    if device not in ("lcd", "sound"):
        raise ValueError("invalid device")
    origin = origin or socket.gethostname().split(".")[0]
    if not re.fullmatch(r"(watchtower|gway-[0-9]{3,}|ocpp-abb-1|gelectriic\.com)", origin):
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
            if len(args) < 2:
                raise ValueError("missing sound selection")
            if args[1] == "--sequence":
                if len(args) < 3:
                    raise ValueError("missing sequence data")
                action, arguments = "sequence", {"sequence": args[2]}
                options = _sound_options(args[3:])
            else:
                action, arguments = "play", {"name": args[1]}
                options = _sound_options(args[2:])
        elif cmd in ("mute", "unmute", "toggle", "status") and len(args) in (1, 2):
            if len(args) == 2 and (cmd != "status" or args[1] != "--json"):
                raise ValueError("unexpected sound arguments")
            action, arguments = cmd, {}
            options = {}
        elif cmd == "event":
            if len(args) < 3:
                raise ValueError("invalid sound event arguments")
            action, arguments = "event", {"event": args[1], "source": args[2]}
            options = _sound_options(args[3:])
        else:
            raise ValueError("unsupported remote sound command")
        if action in ("play", "event", "sequence"):
            if ("motif" in options and action != "play"
                or "resolve" in options and action != "event"
                or action == "sequence" and
                    any(k in options for k in ("within", "repeat", "motif", "resolve"))
                or "dry_run" in options and "resolve" in options):
                raise ValueError("unsupported combination of sound options")
            arguments.update(options)
    return {"schema": 1, "node": node, "origin": origin,
            "request_id": request_id or secrets.token_hex(16),
            "expires_at": (now + timedelta(seconds=20)).isoformat(),
            "device": device, "action": action, "arguments": arguments, "hops": 0}



def _audit_receipt(phase, event, result=None):
    """Opt-in, sanitized operator acceptance receipt; never prints credentials.

    The submitting ID is emitted *before* transport so an ambiguous outcome
    remains identifiable and MUST NOT be retried with a new physical event.
    Ordinary stdout/stderr are unchanged unless explicitly opted in.
    """
    if os.environ.get("GWAY_LCD_SOUND_AUDIT_RECEIPTS") != "1":
        return
    record = {"schema": 1, "phase": phase, "source": event["origin"],
              "node": event["node"], "device": event["device"],
              "action": event["action"], "request_id": event["request_id"]}
    if phase == "confirmed" and type(result) is dict:
        for key, length in (("receiver_request_id", 32), ("source_event_sha256", 64)):
            value = result.get(key)
            if type(value) is str and re.fullmatch("[0-9a-f]{%s}" % length, value):
                record[key] = value
        record["status"] = "succeeded"
        if type(result.get("duplicate")) is bool:
            record["duplicate"] = result["duplicate"]
    print("gway-lcd-sound-receipt " + json.dumps(record, sort_keys=True),
          file=sys.stderr, flush=True)


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
            if args and args[0] == "play":
                local_args = args[1:]
            elif args and args[0] == "event":
                local_args = ["--event", args[1], "--source", args[2], *args[3:]]
            else:
                local_args = args
            cmd = ["bash", str(here / "sound.sh"), *local_args]
        return runner(cmd, check=False).returncode
    # Never run the sender-local hardware command after a failed bridge call.
    from server_source_route import load as source_config, dispatch as source_dispatch
    source = source_config()
    payload = event_for(device, list(args), target,
                        origin=source["origin"] if source else None)
    _audit_receipt("submitted", payload)
    if source is not None:
        result = source_dispatch(payload, config=source)
    else:
        from json import dumps
        remote = runner(["gway-remote", "--lcd-sound-bridge", "send"], input=dumps(payload).encode("utf-8"),
                    capture_output=True, timeout=16, check=False)
        if remote.returncode:
            raise RuntimeError("remote delivery failed")
        result = json.loads(remote.stdout)
    if (type(result) is not dict or result.get("node") != target
            or result.get("request_id") != payload["request_id"]
            or result.get("status") != "succeeded"):
        raise RuntimeError("remote delivery unconfirmed")
    _audit_receipt("confirmed", payload, result)
    if (payload["action"] == "status" or payload["arguments"].get("dry_run")
            or payload["arguments"].get("resolve")):
        output = result.get("output")
        if type(output) is not str or len(output.encode("utf-8")) > 4096:
            raise RuntimeError("invalid remote status")
        sys.stdout.write(output)
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
