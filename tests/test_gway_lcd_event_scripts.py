from __future__ import annotations

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
