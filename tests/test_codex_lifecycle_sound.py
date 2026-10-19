"""Hardware-free contract tests for the release-owned Codex adapter."""
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts/gway/codex-lifecycle-sound"
EVENTS = ("SessionStart", "UserPromptSubmit", "PermissionRequest",
          "PreCompact", "PostCompact", "SubagentStart", "SubagentStop", "Stop")


def test_codex_lifecycle_dispatch(tmp_path):
    log = tmp_path / "args"
    player = tmp_path / "sound"
    player.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SOUND_TEST_LOG"\n')
    player.chmod(0o755)
    env = {**os.environ, "GWAY_CODEX_SOUND_BIN": str(player), "SOUND_TEST_LOG": str(log)}
    for event in EVENTS:
        result = subprocess.run(["bash", str(HOOK), event], env=env, timeout=8)
        assert result.returncode == 0
    assert log.read_text().splitlines() == [
        f"--event {event} --source codex" for event in EVENTS
    ]


def test_codex_lifecycle_best_effort(tmp_path):
    player = tmp_path / "failure"
    player.write_text("#!/bin/sh\nexit 42\n")
    player.chmod(0o755)
    env = {**os.environ, "GWAY_CODEX_SOUND_BIN": str(player)}
    for event in (*EVENTS, "Unknown"):
        assert subprocess.run(["bash", str(HOOK), event], env=env, timeout=8).returncode == 0

def test_no_argument_wrappers(tmp_path):
    log = tmp_path / "events"
    player = tmp_path / "sound"
    player.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SOUND_TEST_LOG"\n')
    player.chmod(0o755)
    env = {**os.environ, "GWAY_CODEX_SOUND_BIN": str(player), "SOUND_TEST_LOG": str(log)}
    for event in EVENTS:
        wrapper = ROOT / "scripts/gway" / f"codex-hook-{event}"
        assert subprocess.run(["bash", str(wrapper)], env=env, timeout=8).returncode == 0
    assert log.read_text().splitlines() == [
        f"--event {event} --source codex" for event in EVENTS
    ]


def test_no_argument_wrappers_disabled_and_failure(tmp_path):
    player = tmp_path / "failure"
    player.write_text("#!/bin/sh\nexit 17\n")
    player.chmod(0o755)
    env = {**os.environ, "GWAY_CODEX_SOUND_BIN": str(player)}
    for event in EVENTS:
        wrapper = ROOT / "scripts/gway" / f"codex-hook-{event}"
        assert subprocess.run(["bash", str(wrapper)], env=env, timeout=8).returncode == 0

def test_disabled_does_not_dispatch(tmp_path):
    log = tmp_path / "called"
    player = tmp_path / "sound"
    player.write_text('#!/bin/sh\ntouch "$SOUND_TEST_LOG"\n')
    player.chmod(0o755)
    env = {**os.environ, "GWAY_CODEX_SOUND_BIN": str(player),
           "GWAY_CODEX_SOUND_DISABLED": "1", "SOUND_TEST_LOG": str(log)}
    for event in EVENTS:
        assert subprocess.run(["bash", str(HOOK), event], env=env, timeout=8).returncode == 0
    assert not log.exists()
