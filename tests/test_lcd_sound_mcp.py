"""Offline contract for fail-closed LCD/Sound MCP provider."""
import importlib.util
import pathlib
import subprocess
import sys
from unittest.mock import patch

PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts/gway/lcd_sound_mcp.py"
spec = importlib.util.spec_from_file_location("lcd_sound_mcp", PATH)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


def test_catalog_exactly_two_tools():
    result = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert {tool["name"] for tool in result["result"]["tools"]} == {"lcd", "sound"}
    assert all(tool["inputSchema"]["additionalProperties"] is False and tool["annotations"]["readOnlyHint"] is False for tool in result["result"]["tools"])


def test_argument_validation_and_parity():
    assert mcp.command_for("lcd", {"action": "show", "line1": "hello", "seconds": 10})[1:] == ["lcd", "show", "hello", "", "--seconds", "10"]
    assert mcp.command_for("sound", {"action": "play", "name": "notice"})[1:] == ["sound", "play", "notice"]
    for name, args in [("sound", {"action": "play", "name": "rm -rf /"}),
                       ("lcd", {"action": "show", "line1": "x\ny"}),
                       ("lcd", {"action": "show", "line1": "x", "seconds": 301}),
                       ("sound", {"action": "status", "extra": "x"}),
                       ("lcd", {"action": "clear", "path": "/tmp/x"})]:
        try:
            mcp.command_for(name, args)
        except ValueError:
            continue
        assert False, (name, args)


def test_reject_invalid_arguments_before_execution():
    with patch.object(mcp.subprocess, "run") as run:
        for name, args in [("lcd", {"action": "show", "line1": "x", "seconds": 999}),
                           ("sound", {"action": "play", "name": "shell;bad"}),
                           ("lcd", {"action": "clear", "path": "/etc/passwd"})]:
            try:
                mcp.execute(name, args)
            except ValueError:
                pass
            else:
                assert False
        run.assert_not_called()


def test_authorized_dispatch_uses_argument_array():
    with patch.object(mcp.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as run:
        assert mcp.execute("sound", {"action": "play", "name": "ok"}) == {"output": "ok", "exit_code": 0}
        assert run.call_args.args[0][1:] == ["sound", "play", "ok"]


def test_stdio_dispatches_validated_call():
    with patch.object(mcp.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as run:
        result = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "lcd", "arguments": {"action": "show", "line1": "hi"}}})
        assert result["result"]["isError"] is False
        assert run.call_args.args[0][1:4] == ["lcd", "show", "hi"]


def test_scope_claims_in_client_arguments_are_rejected():
    with patch.object(mcp.subprocess, "run") as run:
        for tool, action in (("lcd", "clear"), ("sound", "mute")):
            result = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": tool, "arguments": {"action": action,
                                                                      "authorized_scopes": ["gway:execute"]}}})
            assert result["result"]["isError"] is True
        run.assert_not_called()


def test_malformed_action_and_cue_types_fail_closed():
    with patch.object(mcp.subprocess, "run") as run:
        for tool, args in (("sound", {"action": "play", "name": []}),
                           ("sound", {"action": ["status"]}),
                           ("lcd", {"action": {"show": True}})):
            result = mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                 "params": {"name": tool, "arguments": args}})
            assert result["result"]["isError"] is True
        run.assert_not_called()
