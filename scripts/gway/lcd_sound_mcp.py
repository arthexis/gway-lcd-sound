"""Two-tool LCD/Sound MCP stdio provider. Gateway enforces OAuth using readOnlyHint."""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DISPATCHER = HERE / "gway-lcd-sound"
CUES = frozenset(("ok", "notice", "email", "attention", "warning", "error", "noise", "busy", "critical", "undervoltage"))
ACTIONS = {"lcd": {"status", "show", "clear"}, "sound": {"status", "play", "mute", "unmute", "toggle"}}
TOOLS = (
    {"name": "lcd", "description": "LCD status (read), show or clear (execute).",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": sorted(ACTIONS["lcd"])},
         "line1": {"type": "string", "maxLength": 160},
         "line2": {"type": "string", "maxLength": 160},
         "seconds": {"type": "integer", "minimum": 1, "maximum": 300}},
         "required": ["action"], "additionalProperties": False}},
    {"name": "sound", "description": "Sound status (read), play/mute/unmute/toggle (execute).",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": sorted(ACTIONS["sound"])},
         "name": {"type": "string", "enum": sorted(CUES)}},
         "required": ["action"], "additionalProperties": False}},
)


def command_for(name, args):
    if name not in ACTIONS or type(args) is not dict or args.get("action") not in ACTIONS[name]:
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
        keys.add("name")
        if args.get("name") not in CUES:
            raise ValueError("invalid_arguments")
        command.append(args["name"])
    if set(args) - keys:
        raise ValueError("invalid_arguments")
    return command


def execute(name, args, *, authorized_scopes):
    command = command_for(name, args)
    required = "gway:remote" if args["action"] == "status" else "gway:execute"
    if required not in authorized_scopes:
        raise PermissionError("permission_denied")
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
        # The existing federated gateway authenticates calls and applies the action
        # scope policy before forwarding; stdio has no authenticated scope field.
        # Until that gateway support exists, deny every call rather than trust
        # client-provided scopes or permit writes accidentally.
        result = {"content": [{"type": "text", "text": json.dumps({"error": "gateway_scope_enforcement_required"})}], "isError": True}
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
