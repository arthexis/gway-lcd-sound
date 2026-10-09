from __future__ import annotations
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from .config import SOUND_HOOK, VOLUME
from .state import log
SOUND_ALIASES = {
    "ap-connect": "notice",
    "ap-disconnect": "warning",
    "bastion-ready": "ok",
    "bastion-failed": "error",
    "bastion-remove": "warning",
    "wifi-connect": "ok",
    "wifi-disconnect": "warning",
    "thermal-warm": "warning",
    "thermal-hot": "error",
    "thermal-critical": "critical",
    "undervoltage": "undervoltage",
    "lcd-important": "attention",
    "eth-connect": "ok",
    "eth-disconnect": "warning",
    "hdmi-connect": "notice",
    "hdmi-disconnect": "warning",
    "camera-connect": "notice",
    "camera-disconnect": "warning",
    "kindle-connect": "notice",
    "kindle-disconnect": "warning",
    "usb-peripheral": "notice",
    "usb-unknown": "attention",
    "usb-remove": "warning",
    "feedback-lock": "attention",
    "repo-upgrade-start": "busy",
    "repo-upgrade-complete": "ok",
    "repo-upgrade-failed": "error",
    "repo-upgrade-complete-unknown": "notice",
}

def play(event: str, sound: str, detail: str = "", *, dry_run: bool = False) -> None:
    requested_sound = sound
    sound = SOUND_ALIASES.get(sound, sound)
    payload: dict[str, Any] = {"event_name": event, "sound": sound, "detail": detail}
    if requested_sound != sound:
        payload["requested_sound"] = requested_sound
    log("play", **payload)
    if dry_run:
        print(f"sound {event} {sound} {detail}".rstrip(), flush=True)
        return
    if not SOUND_HOOK.exists():
        log("play-skipped", reason="missing-sound-hook", event_name=event, sound=sound)
        return
    env = os.environ.copy()
    env.setdefault("CODEX_SOUND_HOOK_VOLUME", VOLUME)
    subprocess.run(
        [str(SOUND_HOOK), event, sound],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        env=env,
    )


