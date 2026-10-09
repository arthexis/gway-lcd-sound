"""Characterization tests for display formats, priority and expiry."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone


def test_16_column_scroll_and_padding(lcd_module):
    assert lcd_module.scroll_segment("Ready", 0) == "Ready".ljust(16)
    assert lcd_module.scroll_segment("ABCDEFGHIJKLMNOPQRST", 0) == "ABCDEFGHIJKLMNOP"
    assert lcd_module.scroll_segment("ABCDEFGHIJKLMNOPQRST", 1) == "BCDEFGHIJKLMNOPQ"
    assert lcd_module.scroll_segment("ABCDEFGHIJKLMNOPQRST", 7) == "HIJKLMNOPQRST   "


def test_control_characters_are_sanitized(lcd_module):
    assert lcd_module.clean_line("A\nB\r\x00C") == "A B  C"
    assert lcd_module.clean_line("X" * 80) == "X" * 64


def test_channel_legacy_name_and_expiration(tmp_path, lcd_module):
    now = datetime.now(timezone.utc)
    path = tmp_path / "lcd-high"
    path.write_text("Hello\nWorld\n" + (now + timedelta(minutes=2)).isoformat() + "\n")
    payload = lcd_module.read_channel_payload(path, "high", now=now)
    assert (payload.line1, payload.line2) == ("Hello", "World")
    expired = lcd_module.read_channel_payload(path, "high", now=now + timedelta(minutes=3))
    assert expired is None
    assert not path.exists()


def test_existing_event_lock_expires_and_restores_rotation(tmp_path, lcd_module, capsys):
    now = datetime.now(timezone.utc)
    (tmp_path / "lcd-high").write_text("Normal\nStatus\n")
    (tmp_path / "lcd-event-12.lck").write_text(
        "Warning\nReconnect\n" + (now + timedelta(seconds=2)).isoformat() + "\n"
    )
    args = argparse.Namespace(
        lock_dir=[str(tmp_path)], dry_run=True, no_hardware=True,
        stop_embedded=False, rotation_seconds=10.0,
        event_seconds=10.0, poll_seconds=0.1,
    )
    runner = lcd_module.Runner(args)
    runner.run_once()
    assert "event:" in capsys.readouterr().out
    (tmp_path / "lcd-event-12.lck").unlink()
    # The running scheduler caches events until expiry; a fresh runner reloads.
    runner = lcd_module.Runner(args)
    runner.run_once()
    assert "high:" in capsys.readouterr().out


def test_runner_pr_override_wins_over_event_and_rotation(tmp_path, lcd_module, capsys):
    now = datetime.now(timezone.utc)
    (tmp_path / "lcd-high").write_text("Normal\nStatus\n")
    (tmp_path / "lcd-event-1.lck").write_text("ALERT\nTemporary\n")
    (tmp_path / "lcd-actions-runner").write_text(
        "Run PR #142\nfeature/long-branch\n" +
        (now + timedelta(minutes=5)).isoformat() + "\n"
    )
    args = argparse.Namespace(
        lock_dir=[str(tmp_path)], dry_run=True, no_hardware=True,
        stop_embedded=False, rotation_seconds=10.0,
        event_seconds=10.0, poll_seconds=0.1,
    )
    runner = lcd_module.Runner(args)
    runner.run_once()
    out = capsys.readouterr().out
    assert "actions-runner:" in out
    assert "Run PR #142" in out
    (tmp_path / "lcd-actions-runner").unlink()
    runner.run_once()
    assert "event:" in capsys.readouterr().out


def test_rotation_config_keeps_legacy_aliases(lcd_module):
    assert lcd_module.parse_channel_order("high,low,uptime,github") == [
        "high", "low", "stats", "github"
    ]
    assert lcd_module.parse_channel_order("# comment\nall\nhigh high") == ["high"]
