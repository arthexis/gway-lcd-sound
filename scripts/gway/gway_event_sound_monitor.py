#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

BASE = Path("/home/arthe")
SUITE = BASE / "arthexis"
STATE_DIR = Path(os.environ.get("GWAY_EVENT_SOUND_STATE_DIR", BASE / ".local/state/event-sounds"))
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = STATE_DIR / "events.log"
SOUND_HOOK = Path(os.environ.get("GWAY_EVENT_SOUND_HOOK", BASE / ".local/bin/codex-sound-hook"))
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
        os.environ.get("GWAY_EVENT_SOUND_UNDERVOLTAGE_REPEAT_SECONDS", "60"),
    )
)
VOLUME = os.environ.get("GWAY_EVENT_SOUND_VOLUME", "0.21")
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

STOP = False
INTERNAL_VIDEO_PREFIXES = (
    "bcm2835-",
    "rpi-",
)


def handle_stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def run(argv: list[str], *, timeout: float = 4.0, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            argv,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout


def udev_properties(path: Path | None = None, name: str | None = None) -> dict[str, str]:
    argv = ["udevadm", "info", "--query=property"]
    if name:
        argv.append(f"--name={name}")
    elif path:
        argv.append(f"--path={path}")
    else:
        return {}
    props: dict[str, str] = {}
    for line in run(argv, timeout=3).splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key] = value
    return props


def log(event: str, **payload: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **payload}
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


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


def ap_stations() -> dict[str, dict[str, str]]:
    output = run(["iw", "dev", AP_IFACE, "station", "dump"], timeout=4)
    stations: dict[str, dict[str, str]] = {}
    current = ""
    for raw in output.splitlines():
        line = raw.strip()
        match = re.match(r"Station\s+([0-9a-f:]{17})", line, re.IGNORECASE)
        if match:
            current = match.group(1).lower()
            stations[current] = {}
            continue
        if current and ":" in line:
            key, value = line.split(":", 1)
            stations[current][key.strip().lower()] = value.strip()
    return stations


def usb_devices() -> dict[str, dict[str, str]]:
    devices: dict[str, dict[str, str]] = {}
    for dev in sorted(Path("/sys/bus/usb/devices").glob("*")):
        vendor = text(dev / "idVendor").lower()
        product_id = text(dev / "idProduct").lower()
        if not vendor or not product_id or vendor == "1d6b":
            continue
        manufacturer = text(dev / "manufacturer")
        product = text(dev / "product")
        serial = text(dev / "serial")
        key = f"{vendor}:{product_id}:{serial or dev.name}"
        label = " ".join(part for part in [manufacturer, product, serial] if part)
        devices[key] = {
            "vendor": vendor,
            "product_id": product_id,
            "manufacturer": manufacturer,
            "product": product,
            "serial": serial,
            "label": label or key,
            "path": str(dev),
            "class": classify_usb(vendor, product_id, label),
        }
    return devices


def classify_usb(vendor: str, product_id: str, label: str) -> str:
    lowered = label.lower()
    if vendor == "0bda" and product_id == "b812":
        return "wifi"
    if vendor == "059f" and product_id == "1027" or "iamakey" in lowered:
        return "bastion"
    if vendor == "1949" or "kindle" in lowered or "amazon" in lowered:
        return "kindle"
    if "hub" in lowered:
        return "hub"
    return "other"


def usb_wifi_interfaces() -> dict[str, str]:
    interfaces: dict[str, str] = {}
    for iface in sorted(Path("/sys/class/net").glob("*")):
        props = udev_properties(iface)
        if props.get("ID_BUS") == "usb" and props.get("DEVTYPE") == "wlan":
            label = " ".join(
                part
                for part in [
                    props.get("INTERFACE", iface.name),
                    props.get("ID_VENDOR_FROM_DATABASE") or props.get("ID_VENDOR", ""),
                    props.get("ID_MODEL_FROM_DATABASE") or props.get("ID_MODEL", ""),
                    props.get("ID_SERIAL_SHORT", ""),
                ]
                if part
            )
            interfaces[iface.name] = label
    return interfaces


def eth0_carrier() -> str:
    value = text(Path("/sys/class/net/eth0/carrier"))
    if value == "1":
        return "connected"
    if value == "0":
        return "disconnected"
    return "unknown"


def hdmi_status() -> dict[str, str]:
    statuses: dict[str, str] = {}
    for connector in sorted(Path("/sys/class/drm").glob("card*-HDMI-A-*")):
        status = text(connector / "status")
        if status:
            statuses[connector.name] = status
    return statuses


def external_cameras() -> dict[str, str]:
    cameras: dict[str, str] = {}
    for node in sorted(Path("/sys/class/video4linux").glob("video*")):
        name = text(node / "name")
        if name.startswith(INTERNAL_VIDEO_PREFIXES):
            continue
        props = udev_properties(node)
        if props.get("ID_BUS") != "usb":
            continue
        key = props.get("ID_SERIAL") or props.get("ID_PATH") or node.name
        cameras[key] = name or props.get("DEVNAME", node.name)
    return cameras


def usb_inventory() -> dict[str, Any]:
    path = Path("/run/arthexis-usb/devices.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"devices": []}


def bastion_state(inventory: dict[str, Any], usb: dict[str, dict[str, str]]) -> dict[str, Any]:
    devices = inventory.get("devices") or []
    inventory_present = any("bastion-unlock" in (device.get("claimed_roles") or []) for device in devices)
    usb_present = any(device.get("class") == "bastion" for device in usb.values())
    present = inventory_present or usb_present
    output = run(
        ["ssh-add", "-l"],
        timeout=3,
        env={**os.environ, "SSH_AUTH_SOCK": "/run/bastion-ssh/agent.sock"},
    )
    agent_ready = bool(output.strip()) and "no identities" not in output.lower()
    return {"present": present, "agent_ready": agent_ready, "inventory_present": inventory_present, "usb_present": usb_present}


def kindle_present(inventory: dict[str, Any], usb: dict[str, dict[str, str]]) -> bool:
    for device in inventory.get("devices") or []:
        if device.get("kindle_shape"):
            return True
        label = " ".join(str(device.get(key, "")) for key in ("vendor", "model", "label")).lower()
        if "kindle" in label or "amazon" in label:
            return True
    return any(device.get("class") == "kindle" for device in usb.values())


def file_signatures(patterns: list[str]) -> dict[str, str]:
    signatures: dict[str, str] = {}
    for pattern in patterns:
        for path in sorted(SUITE.glob(pattern)):
            try:
                stat = path.stat()
            except OSError:
                continue
            signatures[str(path)] = f"{stat.st_mtime_ns}:{stat.st_size}"
    return signatures


def file_signature(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def upgrade_state() -> dict[str, Any]:
    duration_signature = file_signature(UPGRADE_DURATION_LOCK)
    duration_payload: dict[str, Any] = {}
    if duration_signature:
        try:
            loaded = json.loads(UPGRADE_DURATION_LOCK.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                duration_payload = loaded
        except (OSError, json.JSONDecodeError):
            duration_payload = {}
    return {
        "in_progress": UPGRADE_IN_PROGRESS_LOCK.exists(),
        "progress_signature": file_signature(UPGRADE_IN_PROGRESS_LOCK),
        "duration_signature": duration_signature,
        "duration_status": duration_payload.get("status"),
        "duration_finished_at": duration_payload.get("finished_at", ""),
        "duration_seconds": duration_payload.get("duration_seconds"),
    }


def read_temperature_c() -> float | None:
    candidates = [
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/class/hwmon/hwmon0/temp1_input"),
    ]
    for path in candidates:
        raw = text(path)
        if raw:
            try:
                return float(raw) / 1000.0
            except ValueError:
                pass
    output = run(["vcgencmd", "measure_temp"], timeout=2)
    match = re.search(r"temp=([0-9.]+)", output)
    if match:
        return float(match.group(1))
    return None


def thermal_level(temp_c: float | None) -> str:
    if temp_c is None:
        return "unknown"
    if temp_c >= THERMAL_CRITICAL_C:
        return "critical"
    if temp_c >= THERMAL_HOT_C:
        return "hot"
    if temp_c >= THERMAL_WARM_C:
        return "warm"
    return "normal"


def undervoltage_state() -> dict[str, Any]:
    output = run(["vcgencmd", "get_throttled"], timeout=2).strip()
    active = False
    historical = False
    value = None
    if "=" in output:
        try:
            value = int(output.split("=", 1)[1], 16)
            active = bool(value & 0x1)
            historical = bool(value & 0x10000)
        except ValueError:
            pass
    return {
        "active": active,
        "historical": historical,
        "raw": output,
        "value": value,
    }


def snapshot() -> dict[str, Any]:
    inventory = usb_inventory()
    usb = usb_devices()
    temp_c = read_temperature_c()
    return {
        "ap_stations": ap_stations(),
        "usb": usb,
        "usb_wifi": usb_wifi_interfaces(),
        "eth0": eth0_carrier(),
        "hdmi": hdmi_status(),
        "cameras": external_cameras(),
        "bastion": bastion_state(inventory, usb),
        "kindle": kindle_present(inventory, usb),
        "lcd_files": file_signatures(
            [
                ".locks/lcd-high*",
                ".locks/lcd-important*",
            ]
        ),
        "feedback_files": file_signatures(
            [
                ".locks/operator-local-feedback.jsonl",
                ".locks/*feedback*.lck",
                ".locks/*feedback*.jsonl",
            ]
        ),
        "upgrade": upgrade_state(),
        "thermal": {
            "temp_c": temp_c,
            "level": thermal_level(temp_c),
        },
        "undervoltage": undervoltage_state(),
    }


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
    severity = {"unknown": 0, "normal": 0, "warm": 1, "hot": 2, "critical": 3}
    if level in {"normal", "unknown"}:
        runtime["last_thermal_level"] = level
        return
    now = time.monotonic()
    last_level = runtime.get("last_thermal_level")
    last_played_level = runtime.get("last_thermal_played_level", "normal")
    last_at = float(runtime.get("last_thermal_at", 0.0))
    should_play = False
    if severity.get(level, 0) > severity.get(last_played_level, 0):
        should_play = True
    elif now - last_at >= THERMAL_REPEAT_SECONDS:
        should_play = True

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

    if not last_active or now - last_at >= UNDERVOLTAGE_REPEAT_SECONDS:
        detail = str(state.get("raw") or "undervoltage")
        play("undervoltage", "undervoltage", detail, dry_run=dry_run)
        runtime["last_undervoltage_at"] = now
    runtime["last_undervoltage_active"] = True


def save_state(payload: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(f".{STATE_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE_FILE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host-local GWAY event sound monitor.")
    parser.add_argument("--poll-seconds", type=float, default=float(os.environ.get("GWAY_EVENT_SOUND_POLL_SECONDS", "4")))
    parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
    parser.add_argument("--json", action="store_true", help="emit JSON for --once")
    parser.add_argument("--dry-run", action="store_true", help="log/print sound decisions without playback")
    args = parser.parse_args(argv)

    if args.once:
        payload = snapshot()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(payload)
        return 0

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    previous = snapshot()
    initial_thermal_level = (previous.get("thermal") or {}).get("level", "unknown")
    runtime: dict[str, Any] = {
        "last_thermal_level": initial_thermal_level,
        "last_thermal_played_level": initial_thermal_level,
        "last_thermal_at": time.monotonic(),
        "last_undervoltage_active": bool((previous.get("undervoltage") or {}).get("active")),
        "last_undervoltage_at": 0.0,
    }
    save_state({"started_at": time.time(), "snapshot": previous})
    log("baseline", summary="event sound monitor started")

    while not STOP:
        time.sleep(max(1.0, args.poll_seconds))
        current = snapshot()
        try:
            process_changes(previous, current, runtime, dry_run=args.dry_run)
        except Exception as exc:
            log("error", error=repr(exc))
        previous = current
        save_state({"updated_at": time.time(), "snapshot": current, "runtime": runtime})

    log("stopped", summary="event sound monitor stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
