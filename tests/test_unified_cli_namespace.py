"""A1: two public dispatcher namespaces; legacy aliases remain available."""
import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/gway/gway-lcd-sound"


def run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)


def test_help_advertises_both_namespaces():
    result = run("--help")
    assert result.returncode == 0
    assert "lcd monitor eth0" in result.stdout
    assert "sound hotplug" in result.stdout
    assert "sound mute toggle" in result.stdout
    assert "sound status" in result.stdout
    assert "sound play NAME" in result.stdout
    assert "sound mute|unmute|toggle" in result.stdout
    assert "\\n  sound" not in result.stdout


def test_invalid_operations_fail_without_touching_hardware():
    for args in [("lcd",), ("lcd", "invalid"), ("sound",), ("sound", "invalid"), ("sound", "play"), ("sound", "invalid")]:
        result = run(*args)
        assert result.returncode == 64, (args, result.stderr)


def test_legacy_dispatcher_help_still_works():
    assert run("help").returncode == 0
