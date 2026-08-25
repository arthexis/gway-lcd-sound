from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from scripts.gway import arthexis_dense_lcd_summary as dense_summary
from scripts.gway import gway_eth0_node_lcd_monitor as eth0_lcd
from scripts.gway import gway_event_sound_monitor as event_sound
from scripts.gway import lcd_lockfile_runner as lcd_runner
from scripts.gway import lcd_system_info_publisher as system_info


def test_lcd_runner_channel_order_aliases_and_dedupes():
    assert lcd_runner.parse_channel_order("full, uptime, summary, clock, clock\n# comment") == [
        "stats",
        "summary",
        "clock",
    ]


def test_lcd_runner_scroll_segment_is_fixed_width():
    assert lcd_runner.scroll_segment("short", 3) == "short".ljust(lcd_runner.COLUMNS)
    assert len(lcd_runner.scroll_segment("this message is too long", 2)) == lcd_runner.COLUMNS


def test_system_info_rotation_script_escapes_quotes():
    frame = system_info.Frame("quote", 'HELLO "LCD"', "READY")

    rendered = system_info.render_rotation_script([frame])

    assert 'frame "HELLO \'LCD\'" "READY"' in rendered


def test_system_info_standby_has_four_unlabeled_critical_frames(monkeypatch):
    monkeypatch.setattr(system_info, "primary_route", lambda: ("wlan1", "192.0.2.10", True))
    monkeypatch.setattr(system_info, "interface_ipv4", lambda iface: {"wlan0": "10.42.0.1", "eth0": "192.168.129.10"}[iface])
    monkeypatch.setattr(system_info, "journal_counts", lambda: (0, 0, "none"))

    frames = system_info.build_frames()

    assert [frame.key for frame in frames] == ["node", "health", "logs", "addresses"]
    assert frames[-1].line1 == "10.42.0.1"
    assert frames[-1].line2 == "192.168.129.10"
    assert not frames[0].line1.startswith("HOST ")


def test_high_lock_is_a_preemptive_bounded_lease(tmp_path, monkeypatch):
    high_lock = tmp_path / "lcd-high"
    high_lock.write_text("ACTION\nHOLD\n", encoding="utf-8")
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(lcd_runner, "high_hold_seconds", lambda: 10.0)

    event = lcd_runner.load_next_event([tmp_path], now=now)

    assert event is not None
    assert event.lines == ("ACTION", "HOLD")
    assert event.expires_at >= now + timedelta(seconds=9)


def test_expired_high_lock_is_removed_before_standby(tmp_path, monkeypatch):
    high_lock = tmp_path / "lcd-high"
    high_lock.write_text("OLD\nSCREEN\n", encoding="utf-8")
    expired = datetime.now(timezone.utc) - timedelta(seconds=20)
    os.utime(high_lock, (expired.timestamp(), expired.timestamp()))
    monkeypatch.setattr(lcd_runner, "high_hold_seconds", lambda: 10.0)

    assert lcd_runner.load_next_event([tmp_path], now=datetime.now(timezone.utc)) is None
    assert not high_lock.exists()


def test_runner_does_not_rewrite_unchanged_frame(tmp_path, monkeypatch):
    parser = lcd_runner.build_parser()
    args = parser.parse_args(["--lock-dir", str(tmp_path), "--no-hardware"])
    args.lock_dir = [tmp_path]
    runner = lcd_runner.Runner(args)
    monkeypatch.setattr(lcd_runner, "WORK_FILE", tmp_path / "screen.txt")
    monkeypatch.setattr(lcd_runner, "HISTORY_FILE", tmp_path / "history.ndjson")

    runner.write_frame("STABLE", "FRAME", "event")
    runner.write_frame("STABLE", "FRAME", "event")

    assert len((tmp_path / "history.ndjson").read_text(encoding="utf-8").splitlines()) == 1


def test_event_sound_usb_classification_and_aliases():
    assert event_sound.classify_usb("0bda", "b812", "adapter") == "wifi"
    assert event_sound.classify_usb("1949", "0004", "Amazon Kindle") == "kindle"
    assert event_sound.SOUND_ALIASES["bastion-ready"] == "ok"
    assert event_sound.SOUND_ALIASES["repo-upgrade-failed"] == "error"


def test_eth0_lcd_formats_known_roles():
    assert eth0_lcd.role_word("Control") == "CTRL"
    assert eth0_lcd.fit_two_words("Raspbian", "Gateway") == "RASPBIA GWAY"


def test_dense_lcd_summary_compacts_and_dedupes():
    frames = dense_summary._dedupe_frames(
        [
            ("ERR apps.core: Task heartbeat raised unexpected: nope", "body"),
            ("ERR apps.core: Task heartbeat raised unexpected: nope", "body"),
        ]
    )

    assert frames == [("apps.core: heart", "body")]
