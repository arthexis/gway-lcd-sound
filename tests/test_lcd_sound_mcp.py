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
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in result["result"]["tools"])


def test_argument_validation_and_parity():
    assert mcp.command_for("lcd", {"action": "show", "line1": "hello", "seconds": 10})[1:] == ["lcd", "show", "hello", "", "--seconds", "10"]
    assert mcp.command_for("sound", {"action": "play", "name": "notice"})[1:] == ["sound", "play", "notice"]
    for name, args in [("sound", {"action": "play", "name": "rm -rf /"}),
                       ("lcd", {"action": "show", "line1": "x\\ny"}),
                       ("lcd", {"action": "show", "line1": "x", "seconds": 301}),
                       ("sound", {"action": "status", "extra": "x"}),
                       ("lcd", {"action": "clear", "path": "/tmp/x"})]:
        try:
            mcp.command_for(name, args)
        except ValueError:
            continue
        assert False, (name, args)


def test_scope_denial_precedes_execution():
    with patch.object(mcp.subprocess, "run") as run:
        for name, args, scopes in [("lcd", {"action": "show", "line1": "x"}, {"gway:remote"}),
                                   ("sound", {"action": "play", "name": "ok"}, {"gway:remote"}),
                                   ("sound", {"action": "status"}, set())]:
            try:
                mcp.execute(name, args, authorized_scopes=scopes)
            except PermissionError:
                pass
            else:
                assert False
        run.assert_not_called()


def test_authorized_dispatch_uses_argument_array():
    with patch.object(mcp.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as run:
        assert mcp.execute("sound", {"action": "play", "name": "ok"}, authorized_scopes={"gway:execute"}) == {"output": "ok", "exit_code": 0}
        assert run.call_args.args[0][1:] == ["sound", "play", "ok"]


def test_stdio_denies_calls_until_gateway_scope_protocol_is_integrated():
    result = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "lcd", "arguments": {"action": "show", "line1": "hi"}}})
    assert result["result"]["isError"] is True
    assert "gateway_scope_enforcement_required" in result["result"]["content"][0]["text"]
