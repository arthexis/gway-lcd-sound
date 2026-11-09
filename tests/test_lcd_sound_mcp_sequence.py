"""MCP one-shot contract tests without physical audio."""
import importlib.util
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1] / "scripts" / "gway"
spec = importlib.util.spec_from_file_location("lcd_sound_mcp", ROOT / "lcd_sound_mcp.py")
sys.path.insert(0, str(ROOT))
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)
SEQUENCE = json.dumps({"format": "gway-piano-v1", "notes": [[440, .1, .02], [660, .1, 0]]})

def test_mcp_sequence_routes_as_single_argument():
    command = mcp.command_for("sound", {"action": "play", "sequence": SEQUENCE})
    assert command[-2:] == ["--sequence", SEQUENCE]
    assert command[:3] == [str(mcp.DISPATCHER), "sound", "play"]

def test_existing_named_cue_unchanged():
    assert mcp.command_for("sound", {"action": "play", "name": "ok"})[-1] == "ok"

@pytest.mark.parametrize("args", [
    {"action": "play", "sequence": SEQUENCE, "name": "ok"},
    {"action": "play", "sequence": '{"format":"gway-piano-v1","notes":[]}'},
    {"action": "play", "sequence": SEQUENCE, "extra": "bad"},
    {"action": "play", "sequence": 42},
    {"action": "status", "sequence": SEQUENCE},
])
def test_mcp_rejects_invalid_arguments(args):
    with pytest.raises(ValueError):
        mcp.command_for("sound", args)

def test_mcp_does_not_invoke_shell(monkeypatch):
    called = {}
    class Result:
        returncode = 0
        stdout = "ok"
    def fake_run(command, **kwargs):
        called.update(kwargs)
        assert command[-1] == SEQUENCE
        return Result()
    monkeypatch.setattr(mcp.subprocess, "run", fake_run)
    assert mcp.execute("sound", {"action": "play", "sequence": SEQUENCE})["exit_code"] == 0
    assert called["timeout"] == 15
    assert "shell" not in called
