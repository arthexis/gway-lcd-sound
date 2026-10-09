from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bash_helpers_parse():
    helpers = [
        ROOT / "scripts/gway/codex-sound-hook",
        ROOT / "scripts/gway/gway-event-sound-hotplug",
        ROOT / "scripts/gway/gway-toggle-gpio-sound-mute",
        ROOT / "scripts/gway/radio-play",
        ROOT / "scripts/gway/sound.sh",
    ]

    for helper in helpers:
        result = subprocess.run(["bash", "-n", str(helper)], check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_templates_are_not_filled_with_local_bastion_identifiers():
    template = (ROOT / "config/udev/rules.d/94-gway-event-sound.rules.template").read_text(encoding="utf-8")

    assert "<BASTION_ID_SERIAL_SHORT>" in template
    assert "<BASTION_ID_FS_UUID>" in template


def test_documented_notification_helper_is_present():
    assert (ROOT / "scripts/gway/gway-system-notify").exists()


def test_archived_media_shortcuts_are_packaged():
    shortcuts = [
        "imperial-march-gpio",
        "mettaton-battle-start",
        "mettaton-metal-crusher-start",
        "radio-play",
    ]

    for shortcut in shortcuts:
        assert (ROOT / "scripts/gway" / shortcut).exists()
        assert (ROOT / "docs/man/man1" / f"{shortcut}.1").exists()


def test_actions_runner_sound_dropin_nonfatal_and_bounded():
    dropin = ROOT / "config/systemd/gway/actions-runner/20-gway-sound.conf"
    content = dropin.read_text(encoding="utf-8")
    assert "CODEX_SOUND_HOOK_LOCK_WAIT=0" in content
    assert "CODEX_SOUND_HOOK_TIMEOUT=2" in content
    assert "ExecStartPost=-/home/arthe/.local/bin/codex-sound-hook actions-runner-start notice" in content
    assert "ExecStopPost=-/home/arthe/.local/bin/codex-sound-hook actions-runner-stop warning" in content
