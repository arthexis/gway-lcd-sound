"""Characterize hardware-output formatting and playback locking."""
from __future__ import annotations

import argparse
import fcntl
from pathlib import Path


def test_fake_lcd_records_exact_padded_rows(tmp_path, monkeypatch, lcd_module, fake_lcd):
    monkeypatch.setattr(lcd_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lcd_module, "WORK_FILE", tmp_path / "lcd-screen.txt")
    monkeypatch.setattr(lcd_module, "HISTORY_FILE", tmp_path / "lcd-history.ndjson")
    runner = lcd_module.Runner(argparse.Namespace(
        lock_dir=[str(tmp_path)], no_hardware=True,
    ))
    runner.lcd = fake_lcd
    runner.write_frame("Run PR #142", "feature/very-long-branch", "actions-runner")
    assert fake_lcd.frames == [
        ("Run PR #142".ljust(16), "feature/very-long-branch"[:16])
    ]
    assert (tmp_path / "lcd-screen.txt").read_text().splitlines() == [
        "Run PR #142".ljust(16), "feature/very-long-branch"[:16]
    ]


def test_history_records_frame_transitions_only(tmp_path, monkeypatch, lcd_module, fake_lcd):
    monkeypatch.setattr(lcd_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lcd_module, "WORK_FILE", tmp_path / "lcd-screen.txt")
    monkeypatch.setattr(lcd_module, "HISTORY_FILE", tmp_path / "lcd-history.ndjson")
    runner = lcd_module.Runner(argparse.Namespace(lock_dir=[str(tmp_path)], no_hardware=True))
    runner.lcd = fake_lcd

    runner.write_frame("same", "frame", "script")
    runner.write_frame("same", "frame", "script")
    runner.write_frame("next", "frame", "script")

    assert len((tmp_path / "lcd-history.ndjson").read_text().splitlines()) == 2


def test_compact_history_retains_newest_entries(tmp_path, lcd_module):
    history = tmp_path / "lcd-history.ndjson"
    history.write_text("".join(f'{{"entry": {index}}}\n' for index in range(6)))

    kept = lcd_module.compact_history(history, max_bytes=1, retain_entries=3)

    assert kept == 3
    assert history.read_text().splitlines() == [
        '{"entry": 3}', '{"entry": 4}', '{"entry": 5}'
    ]


def test_sound_lock_contention_is_nonfatal(audio_harness):
    invoke, state, playback = audio_harness
    state.mkdir(parents=True, exist_ok=True)
    with (state / "play.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = invoke("actions-job-start", "busy")
        assert result.returncode == 0
        assert not playback.exists()
        assert "skipped=playback-busy" in (state / "events.log").read_text()
