from __future__ import annotations
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from .config import *
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


