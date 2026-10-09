"""Hardware-free fixtures for the pre-refactor behavioral contract suite."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "gway"


def load_script(name: str) -> ModuleType:
    path = SCRIPTS / name
    key = "contract_" + name.replace(".", "_").replace("-", "_")
    spec = importlib.util.spec_from_file_location(key, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def lcd_module():
    return load_script("lcd_lockfile_runner.py")


@pytest.fixture
def sound_monitor():
    return load_script("gway_event_sound_monitor.py")


@pytest.fixture
def fake_lcd():
    class Display:
        def __init__(self):
            self.frames = []

        def write_frame(self, high: str, low: str) -> None:
            self.frames.append((high, low))

    return Display()


@pytest.fixture
def controlled_clock():
    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def advance(self, seconds: float) -> None:
            self.value += seconds

    return Clock()


@pytest.fixture
def audio_harness(tmp_path):
    """Real shell entry point with an injectable, non-playing sound executable."""
    playback = tmp_path / "playback.txt"
    sound = tmp_path / "sound"
    sound.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PLAYBACK_LOG"\nexit "${FAKE_SOUND_EXIT:-0}"\n')
    sound.chmod(0o755)
    state = tmp_path / "sound-state"
    env = {
        **os.environ,
        "CODEX_SOUND_HOOK_STATE_DIR": str(state),
        "CODEX_SOUND_HOOK_SOUND_BIN": str(sound),
        "PLAYBACK_LOG": str(playback),
        "CODEX_SOUND_HOOK_LOCK_WAIT": "0",
        "CODEX_SOUND_HOOK_TIMEOUT": "2",
    }

    def invoke(*args, extra=None):
        return subprocess.run(
            ["bash", str(SCRIPTS / "codex-sound-hook"), *args],
            env={**env, **(extra or {})},
            capture_output=True,
            text=True,
            timeout=10,
        )

    return invoke, state, playback
