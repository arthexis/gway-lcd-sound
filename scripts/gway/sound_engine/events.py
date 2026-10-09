from __future__ import annotations
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from .config import THERMAL_REPEAT_SECONDS, UNDERVOLTAGE_REPEAT_SECONDS
from .playback import play
from .policy import thermal_due, voltage_due
def added_removed(before: dict[str, Any], after: dict[str, Any], key: str) -> tuple[set[str], set[str]]:
    before_keys = set((before.get(key) or {}).keys())
    after_keys = set((after.get(key) or {}).keys())
    return after_keys - before_keys, before_keys - after_keys


def process_changes(previous: dict[str, Any], current: dict[str, Any], runtime: dict[str, Any], *, dry_run: bool) -> None:
    for mac in sorted(added_removed(previous, current, "ap_stations")[0]):
        play("ap-connect", "ap-connect", mac, dry_run=dry_run)
    for mac in sorted(added_removed(previous, current, "ap_stations")[1]):
        play("ap-disconnect", "ap-disconnect", mac, dry_run=dry_run)

    for iface in sorted(added_removed(previous, current, "usb_wifi")[0]):
        play("wifi-connect", "wifi-connect", current["usb_wifi"].get(iface, iface), dry_run=dry_run)
    for iface in sorted(added_removed(previous, current, "usb_wifi")[1]):
        play("wifi-disconnect", "wifi-disconnect", previous["usb_wifi"].get(iface, iface), dry_run=dry_run)

    if previous.get("eth0") != current.get("eth0") and current.get("eth0") in {"connected", "disconnected"}:
        play(f"eth0-{current['eth0']}", f"eth-{current['eth0']}", "eth0", dry_run=dry_run)

    for name, status in sorted((current.get("hdmi") or {}).items()):
        old = (previous.get("hdmi") or {}).get(name)
        if old != status and status in {"connected", "disconnected"}:
            play(f"hdmi-{status}", f"hdmi-{status}", name, dry_run=dry_run)

    for key in sorted(added_removed(previous, current, "cameras")[0]):
        play("camera-connect", "camera-connect", current["cameras"].get(key, key), dry_run=dry_run)
    for key in sorted(added_removed(previous, current, "cameras")[1]):
        play("camera-disconnect", "camera-disconnect", previous["cameras"].get(key, key), dry_run=dry_run)

    old_bastion = previous.get("bastion") or {}
    new_bastion = current.get("bastion") or {}
    if not old_bastion.get("present") and new_bastion.get("present"):
        runtime["bastion_pending_since"] = time.monotonic()
        runtime["bastion_failed_reported"] = False
        if new_bastion.get("agent_ready"):
            runtime.pop("bastion_pending_since", None)
            play("bastion-insert", "bastion-ready", json.dumps(new_bastion, sort_keys=True), dry_run=dry_run)
    elif old_bastion.get("present") and not new_bastion.get("present"):
        runtime.pop("bastion_pending_since", None)
        runtime["bastion_failed_reported"] = False
        play("bastion-remove", "bastion-remove", "removed", dry_run=dry_run)
    elif new_bastion.get("present") and old_bastion.get("agent_ready") != new_bastion.get("agent_ready"):
        sound = "bastion-ready" if new_bastion.get("agent_ready") else "bastion-failed"
        if new_bastion.get("agent_ready"):
            runtime.pop("bastion_pending_since", None)
        runtime["bastion_failed_reported"] = not new_bastion.get("agent_ready")
        play("bastion-result", sound, json.dumps(new_bastion, sort_keys=True), dry_run=dry_run)
    elif new_bastion.get("present") and not new_bastion.get("agent_ready"):
        pending_since = float(runtime.setdefault("bastion_pending_since", time.monotonic()))
        if not runtime.get("bastion_failed_reported") and time.monotonic() - pending_since >= 12.0:
            runtime["bastion_failed_reported"] = True
            play("bastion-result", "bastion-failed", json.dumps(new_bastion, sort_keys=True), dry_run=dry_run)

    if previous.get("kindle") is False and current.get("kindle") is True:
        play("kindle-connect", "kindle-connect", "kindle", dry_run=dry_run)
    elif previous.get("kindle") is True and current.get("kindle") is False:
        play("kindle-disconnect", "kindle-disconnect", "kindle", dry_run=dry_run)

    handled_usb_classes = {"wifi", "bastion", "kindle"}
    for key in sorted(added_removed(previous, current, "usb")[0]):
        device = current["usb"].get(key, {})
        cls = device.get("class", "other")
        if cls in handled_usb_classes:
            continue
        sound = "usb-peripheral" if cls == "hub" else "usb-unknown"
        play("usb-connect", sound, device.get("label", key), dry_run=dry_run)
    for key in sorted(added_removed(previous, current, "usb")[1]):
        device = previous["usb"].get(key, {})
        if device.get("class") in handled_usb_classes:
            continue
        play("usb-disconnect", "usb-remove", device.get("label", key), dry_run=dry_run)

    if previous.get("lcd_files") != current.get("lcd_files"):
        old = previous.get("lcd_files") or {}
        new = current.get("lcd_files") or {}
        changed = [path for path, signature in new.items() if old.get(path) != signature]
        if changed:
            play("lcd-important", "lcd-important", ",".join(sorted(changed)), dry_run=dry_run)

    if previous.get("feedback_files") != current.get("feedback_files"):
        old = previous.get("feedback_files") or {}
        new = current.get("feedback_files") or {}
        changed = [path for path, signature in new.items() if old.get(path) != signature]
        if changed:
            play("feedback-lock", "feedback-lock", ",".join(sorted(changed)), dry_run=dry_run)

    handle_upgrade(previous, current, runtime, dry_run=dry_run)
    handle_thermal(previous, current, runtime, dry_run=dry_run)
    handle_undervoltage(previous, current, runtime, dry_run=dry_run)


def handle_upgrade(previous: dict[str, Any], current: dict[str, Any], runtime: dict[str, Any], *, dry_run: bool) -> None:
    old_upgrade = previous.get("upgrade") or {}
    new_upgrade = current.get("upgrade") or {}
    old_in_progress = bool(old_upgrade.get("in_progress"))
    new_in_progress = bool(new_upgrade.get("in_progress"))

    if not old_in_progress and new_in_progress:
        runtime["upgrade_start_duration_signature"] = old_upgrade.get("duration_signature", "")
        runtime.pop("upgrade_complete_pending_since", None)
        runtime.pop("upgrade_complete_previous_duration_signature", None)
        play("repo-upgrade-start", "repo-upgrade-start", "upgrade_in_progress.lck", dry_run=dry_run)
        return

    if old_in_progress and not new_in_progress:
        runtime["upgrade_complete_pending_since"] = time.monotonic()
        runtime["upgrade_complete_previous_duration_signature"] = (
            runtime.get("upgrade_start_duration_signature")
            or old_upgrade.get("duration_signature", "")
        )

    pending_since = runtime.get("upgrade_complete_pending_since")
    if pending_since is None:
        return

    previous_duration_signature = str(runtime.get("upgrade_complete_previous_duration_signature", ""))
    current_duration_signature = str(new_upgrade.get("duration_signature", ""))
    if current_duration_signature and current_duration_signature != previous_duration_signature:
        try:
            status = int(new_upgrade.get("duration_status"))
        except (TypeError, ValueError):
            status = -1
        sound = "repo-upgrade-complete" if status == 0 else "repo-upgrade-failed"
        detail = json.dumps(
            {
                "duration_seconds": new_upgrade.get("duration_seconds"),
                "finished_at": new_upgrade.get("duration_finished_at"),
                "status": status,
            },
            sort_keys=True,
        )
        event = "repo-upgrade-complete" if status == 0 else "repo-upgrade-failed"
        play(event, sound, detail, dry_run=dry_run)
        runtime.pop("upgrade_complete_pending_since", None)
        runtime.pop("upgrade_complete_previous_duration_signature", None)
        runtime.pop("upgrade_start_duration_signature", None)
        return

    if time.monotonic() - float(pending_since) >= 20.0:
        play("repo-upgrade-complete", "repo-upgrade-complete-unknown", "upgrade duration status unavailable", dry_run=dry_run)
        runtime.pop("upgrade_complete_pending_since", None)
        runtime.pop("upgrade_complete_previous_duration_signature", None)
        runtime.pop("upgrade_start_duration_signature", None)


def handle_thermal(previous: dict[str, Any], current: dict[str, Any], runtime: dict[str, Any], *, dry_run: bool) -> None:
    thermal = current.get("thermal") or {}
    level = thermal.get("level", "unknown")
    if level in {"normal", "unknown"}:
        runtime["last_thermal_level"] = level
        return
    now = time.monotonic()
    last_level = runtime.get("last_thermal_level")
    last_played_level = runtime.get("last_thermal_played_level", "normal")
    last_at = float(runtime.get("last_thermal_at", 0.0))
    should_play = False
    should_play = thermal_due(level, last_played_level, now, last_at, THERMAL_REPEAT_SECONDS)

    if should_play:
        sound = f"thermal-{level}"
        detail = f"{thermal.get('temp_c'):.1f}C" if isinstance(thermal.get("temp_c"), (float, int)) else level
        play("thermal", sound, detail, dry_run=dry_run)
        runtime["last_thermal_played_level"] = level
        runtime["last_thermal_at"] = now
    runtime["last_thermal_level"] = level


def handle_undervoltage(previous: dict[str, Any], current: dict[str, Any], runtime: dict[str, Any], *, dry_run: bool) -> None:
    state = current.get("undervoltage") or {}
    active = bool(state.get("active"))
    now = time.monotonic()
    last_active = bool(runtime.get("last_undervoltage_active", False))
    last_at = float(runtime.get("last_undervoltage_at", 0.0))

    if not active:
        runtime["last_undervoltage_active"] = False
        return

    if voltage_due(active, last_active, now, last_at, UNDERVOLTAGE_REPEAT_SECONDS):
        detail = str(state.get("raw") or "undervoltage")
        play("undervoltage", "undervoltage", detail, dry_run=dry_run)
        runtime["last_undervoltage_at"] = now
    runtime["last_undervoltage_active"] = True


