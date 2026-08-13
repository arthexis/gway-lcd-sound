from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bash_helpers_parse():
    helpers = [
        ROOT / "scripts/gway/codex-sound-hook",
        ROOT / "scripts/gway/gway-event-sound-hotplug",
        ROOT / "scripts/gway/gway-toggle-gpio-sound-mute",
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
