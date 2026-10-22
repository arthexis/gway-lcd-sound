from __future__ import annotations
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
BASE = Path("/home/arthe")
SUITE = BASE / "arthexis"
STATE_DIR = Path(os.environ.get("GWAY_EVENT_SOUND_STATE_DIR", BASE / ".local/state/event-sounds"))
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = STATE_DIR / "events.log"
SOUND_HOOK = Path(os.environ.get("GWAY_EVENT_SOUND_SOUND_BIN", os.environ.get("GWAY_EVENT_SOUND_HOOK", "/usr/local/bin/sound")))
LCD_CURRENT_FRAME_FILE = Path(
    os.environ.get(
        "GWAY_EVENT_SOUND_LCD_CURRENT_FRAME",
        BASE / ".local/state/lcd-lockfile-runner/lcd-current.json",
    )
)
UPGRADE_IN_PROGRESS_LOCK = SUITE / ".locks/upgrade_in_progress.lck"
UPGRADE_DURATION_LOCK = SUITE / ".locks/upgrade_duration.lck"
AP_IFACE = os.environ.get("GWAY_EVENT_SOUND_AP_IFACE", "wlan0")
THERMAL_WARM_C = float(os.environ.get("GWAY_EVENT_SOUND_THERMAL_WARM_C", "70"))
THERMAL_HOT_C = float(os.environ.get("GWAY_EVENT_SOUND_THERMAL_HOT_C", "75"))
THERMAL_CRITICAL_C = float(os.environ.get("GWAY_EVENT_SOUND_THERMAL_CRITICAL_C", "80"))
THERMAL_REPEAT_SECONDS = float(os.environ.get("GWAY_EVENT_SOUND_THERMAL_REPEAT_SECONDS", "300"))
UNDERVOLTAGE_REPEAT_SECONDS = float(
    os.environ.get(
        "NODE_EVENT_SOUND_UNDERVOLTAGE_REPEAT_SECONDS",
        os.environ.get("GWAY_EVENT_SOUND_UNDERVOLTAGE_REPEAT_SECONDS", "5"),
    )
)
VOLUME = os.environ.get("GWAY_EVENT_SOUND_VOLUME", "0.21")
INTERNAL_VIDEO_PREFIXES = ("bcm2835-", "rpi-")
