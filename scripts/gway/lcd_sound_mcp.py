"""Two-tool LCD/Sound MCP stdio provider. Gateway enforces OAuth using readOnlyHint."""
import json
import subprocess
import sys
from pathlib import Path
from sound_sequence import parse_sequence, MAX_BYTES

HERE = Path(__file__).resolve().parent
DISPATCHER = HERE / "gway-lcd-sound"
CUES = frozenset(("ok", "notice", "email", "attention", "warning", "error", "noise", "busy", "critical", "undervoltage"))
ACTIONS = {"lcd": {"status", "show", "clear"}, "sound": {"status", "play", "mute", "unmute", "toggle"}}
TOOLS = (
    {"name": "lcd", "description": "LCD status, show or clear; requires execute authorization.",
     "annotations": {"readOnlyHint": False},
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": sorted(ACTIONS["lcd"])},
         "line1": {"type": "string", "maxLength": 160},
         "line2": {"type": "string", "maxLength": 160},
         "seconds": {"type": "integer", "minimum": 1, "maximum": 300}},
         "required": ["action"], "additionalProperties": False}},
    {"name": "sound", "description": "Sound status, play, mute, unmute or toggle; requires execute authorization.",
     "annotations": {"readOnlyHint": False},
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": sorted(ACTIONS["sound"])},
         "name": {"type": "string", "enum": sorted(CUES)},
         "sequence": {"type": "string", "maxLength": MAX_BYTES}},
         "required": ["action"], "additionalProperties": False}},
)


def command_for(name, args):
    if type(name) is not str or name not in ACTIONS or type(args) is not dict or type(args.get("action")) is not str or args["action"] not in ACTIONS[name]:
        raise ValueError("invalid_tool_or_action")
    action = args["action"]
    keys = {"action"}
    command = [str(DISPATCHER), name, action]
    if name == "lcd" and action == "show":
        keys |= {"line1", "line2", "seconds"}
        line1 = args.get("line1")
        line2 = args.get("line2", "")
        seconds = args.get("seconds", 30)
        if type(line1) is not str or not line1 or type(line2) is not str or type(seconds) is not int or not 1 <= seconds <= 300:
            raise ValueError("invalid_arguments")
        if any(len(s) > 160 or any(ord(c) < 32 for c in s) for s in (line1, line2)):
            raise ValueError("invalid_arguments")
        command += [line1, line2, "--seconds", str(seconds)]
    elif name == "sound" and action == "play":
        if "sequence" in args:
            keys.add("sequence")
            if "name" in args or type(args["sequence"]) is not str:
                raise ValueError("invalid_arguments")
            parse_sequence(args["sequence"])
            command += ["--sequence", args["sequence"]]
        else:
            keys.add("name")
            if type(args.get("name")) is not str or args["name"] not in CUES:
                raise ValueError("invalid_arguments")
            command.append(args["name"])
    if set(args) - keys:
        raise ValueError("invalid_arguments")
    return command


def execute(name, args):
    """Only callable from node-owned stdio process behind authenticated relay."""
    command = command_for(name, args)
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        return {"error": "command_failed", "exit_code": result.returncode}
    return {"output": result.stdout.strip(), "exit_code": 0}


def handle(request):
    if type(request) is not dict or request.get("jsonrpc") != "2.0":
        raise ValueError("invalid_request")
    if request.get("method") == "notifications/initialized":
        return None
    if "id" not in request:
        raise ValueError("invalid_request")
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "gway-lcd-sound", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": list(TOOLS)}
    elif method == "tools/call":
        params = request.get("params")
        if type(params) is not dict or type(params.get("name")) is not str:
            raise ValueError("invalid_arguments")
        try:
            data = execute(params["name"], params.get("arguments", {}))
            result = {"content": [{"type": "text", "text": json.dumps(data)}], "isError": bool(data.get("error"))}
        except (ValueError, subprocess.TimeoutExpired, OSError) as exc:
            result = {"content": [{"type": "text", "text": json.dumps({"error": "invalid_arguments" if type(exc) is ValueError else "provider_unavailable"})}], "isError": True}
    else:
        raise ValueError("method_not_found")
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def main():
    for line in sys.stdin:
        try:
            reply = handle(json.loads(line))
        except (ValueError, TypeError, UnicodeError):
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
