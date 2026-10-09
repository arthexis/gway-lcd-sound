from __future__ import annotations
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
DEFAULT_LOCK_DIR = Path.home() / ".local" / "state" / "lcd-lockfiles"
DEFAULT_ARTHEXIS_LOCK_DIR = Path("/home/arthe/arthexis/.locks")
DEFAULT_TODO_FILE = Path("/home/arthe/TODO.txt")
DEFAULT_WORKGROUP_FILE = Path("/home/arthe/workgroup.txt")
DEFAULT_PRX_ASSIGNMENTS = Path.home() / ".local" / "state" / "prx" / "assignments.json"
ROTATION_SCRIPT_NAME = "lcd-rotation.script"
CHANNELS_NAME = "lcd-channels.lck"
STATUS_NAME = "lcd-system-info.json"


def run(command: list[str], *, timeout: float = 2.0) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def clean(text: object, *, limit: int = 64) -> str:
    value = "" if text is None else str(text)
    value = value.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    value = re.sub(r"[\x00-\x1F\x7F]", " ", value)
    value = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def compact(text: object, *, limit: int = 16) -> str:
    return clean(text, limit=limit)


def quote_frame_line(text: str) -> str:
    return clean(text).replace('"', "'")


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "?m"
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


def uptime_seconds() -> int | None:
    try:
        return int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except Exception:
        return None


def read_first(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
    except Exception:
        return ""


def systemctl_active(unit: str, *, user: bool = False) -> bool:
    command = ["systemctl"]
    if user:
        command.append("--user")
    command.extend(["is-active", unit])
    return run(command, timeout=1.5).strip() == "active"


def primary_route() -> tuple[str, str, bool]:
    output = run(["ip", "route", "get", "1.1.1.1"], timeout=1.5)
    iface_match = re.search(r"\bdev\s+(\S+)", output)
    src_match = re.search(r"\bsrc\s+(\S+)", output)
    iface = iface_match.group(1) if iface_match else "none"
    src = src_match.group(1) if src_match else ""
    reachable = False
    if src:
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=0.7):
                reachable = True
        except OSError:
            reachable = False
    return iface, src, reachable


def wlan_interfaces() -> list[str]:
    interfaces: list[str] = []
    for path in sorted(Path("/sys/class/net").glob("wlan*")):
        interfaces.append(path.name)
    return interfaces


def wifi_summary() -> tuple[str, str]:
    interfaces = wlan_interfaces()
    if not interfaces:
        return "WIFI none", "no wlan ifaces"

    ap_parts: list[str] = []
    link_parts: list[str] = []
    for iface in interfaces:
        info = run(["iw", "dev", iface, "info"], timeout=1.0)
        if "type AP" in info:
            stations = run(["iw", "dev", iface, "station", "dump"], timeout=1.0)
            clients = len(re.findall(r"^Station\s+", stations, flags=re.MULTILINE))
            ap_parts.append(f"{iface} AP{clients}")
            continue
        link = run(["iw", "dev", iface, "link"], timeout=1.0)
        ssid_match = re.search(r"^\s*SSID:\s+(.+)$", link, flags=re.MULTILINE)
        signal_match = re.search(r"^\s*signal:\s+(-?\d+)", link, flags=re.MULTILINE)
        if ssid_match:
            signal = signal_match.group(1) if signal_match else "?"
            link_parts.append(f"{iface} {signal}")
            link_parts.append(f"SSID {ssid_match.group(1)}")

    if ap_parts and link_parts:
        return compact(f"WIFI {ap_parts[0]}"), compact(link_parts[0])
    if ap_parts:
        return compact(f"WIFI {ap_parts[0]}"), compact(" ".join(interfaces))
    if link_parts:
        return compact(f"WIFI {link_parts[0]}"), compact(link_parts[1] if len(link_parts) > 1 else "")
    return compact(f"WIFI {interfaces[0]}"), "not connected"


def cpu_temp_c() -> str:
    for path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        try:
            value = int(path.read_text(encoding="utf-8").strip())
        except Exception:
            continue
        if value > 1000:
            value = round(value / 1000)
        return f"{value}C"
    return "?C"


def memory_percent() -> int | None:
    data: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition(":")
            match = re.search(r"\d+", raw)
            if match:
                data[key] = int(match.group(0))
    except OSError:
        return None
    total = data.get("MemTotal")
    available = data.get("MemAvailable")
    if not total or available is None:
        return None
    return int(round((1 - available / total) * 100))


def disk_line(path: Path) -> tuple[str, str]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return f"{path} ?", "disk unknown"
    used_pct = int(round((1 - usage.free / usage.total) * 100)) if usage.total else 0
    free_gib = usage.free / (1024**3)
    label = str(path)
    return compact(f"DISK {label} {used_pct}%"), compact(f"free {free_gib:.1f}G")


def disk_usage_label(path: Path) -> tuple[str, str]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return "?", "?G"
    used_pct = int(round((1 - usage.free / usage.total) * 100)) if usage.total else 0
    free_gib = usage.free / (1024**3)
    return f"{used_pct}%", f"{free_gib:.0f}G"


def cpu_freq_label() -> str:
    paths = [
        Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"),
        Path("/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq"),
    ]
    for path in paths:
        try:
            khz = int(path.read_text(encoding="utf-8").strip())
        except Exception:
            continue
        if khz >= 1_000_000:
            return f"{khz / 1_000_000:.1f}GHz"
        return f"{khz // 1000}MHz"
    return "?GHz"


def throttle_label() -> str:
    output = run(["vcgencmd", "get_throttled"], timeout=1.0)
    match = re.search(r"0x[0-9a-fA-F]+", output)
    if match:
        value = match.group(0)
        return "thr ok" if value == "0x0" else f"thr {value}"
    return "thr n/a"


def failed_systemd_count() -> int:
    output = run(["systemctl", "--failed", "--no-legend", "--no-pager"], timeout=2.0)
    if not output:
        return 0
    return sum(1 for line in output.splitlines() if line.strip())


def process_count() -> int:
    try:
        return sum(1 for path in Path("/proc").iterdir() if path.name.isdigit())
    except OSError:
        return 0


def usb_count() -> int:
    count = 0
    for path in Path("/sys/bus/usb/devices").glob("*"):
        try:
            vendor = (path / "idVendor").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if vendor and vendor != "1d6b":
            count += 1
    return count


def i2c_addresses() -> list[str]:
    output = run(["i2cdetect", "-y", "1"], timeout=1.5)
    addresses: list[str] = []
    for token in output.split():
        if re.fullmatch(r"[0-9a-fA-F]{2}", token):
            addresses.append(token.lower())
    return sorted(set(addresses))


def rfid_state() -> str:
    candidates: list[Path] = [
        DEFAULT_ARTHEXIS_LOCK_DIR / "rfid-scan.json",
        Path.home() / ".local" / "state" / "rfid-mode" / "rfid-scan.json",
    ]
    env_scan_file = os.environ.get("RFID_MODE_SCAN_FILE")
    if env_scan_file:
        candidates.insert(0, Path(env_scan_file))
    now = time.time()
    for path in candidates:
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        return "rf-ok" if age < 900 else "rf-old"
    return "rf-none"


def journal_counts() -> tuple[int, int, str]:
    err = run(["journalctl", "--since", "-15min", "-p", "err", "--no-pager", "-q", "-n", "200"], timeout=2.5)
    warn = run(["journalctl", "--since", "-15min", "-p", "warning", "--no-pager", "-q", "-n", "300"], timeout=2.5)
    last = ""
    lines = [line for line in warn.splitlines() if line.strip()]
    if lines:
        last_line = lines[-1]
        parts = last_line.split()
        if len(parts) >= 5:
            last = parts[4].split("[", 1)[0].rstrip(":")
        else:
            match = re.search(r"\s([\w@_.-]+)(?:\[\d+\])?:", last_line)
            if match:
                last = match.group(1)
    return len([line for line in err.splitlines() if line.strip()]), len(lines), last or "none"


def pending_todos(path: Path = DEFAULT_TODO_FILE) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    match = re.search(r"^## Pending\s*(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return 0
    return len(re.findall(r"^###\s+", match.group(1), re.MULTILINE))


def workgroup_active(path: Path = DEFAULT_WORKGROUP_FILE) -> int:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    return sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))


def assignment_count(path: Path = DEFAULT_PRX_ASSIGNMENTS) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    assignments = data.get("assignments") if isinstance(data, dict) else None
    if not isinstance(assignments, list):
        return 0
    return sum(1 for item in assignments if isinstance(item, dict) and item.get("status") in {"assigned", "active"})



from .model import Snapshot


def collect_snapshot() -> Snapshot:
    hostname = socket.gethostname().split(".")[0]
    role = read_first(DEFAULT_ARTHEXIS_LOCK_DIR / "role.lck") or "node"
    iface, ip_addr, reachable = primary_route()
    root_pct, root_free = disk_usage_label(Path("/"))
    home_pct, home_free = disk_usage_label(Path.home())
    err_count, warn_count, last_log = journal_counts()
    return Snapshot(
        hostname=hostname, role=role, iface=iface, ip_addr=ip_addr,
        reachable=reachable, load1=os.getloadavg()[0], ram_pct=memory_percent(),
        root_pct=root_pct, root_free=root_free, home_pct=home_pct, home_free=home_free,
        err_count=err_count, warn_count=warn_count, last_log=last_log,
        addrs=i2c_addresses(), camera_count=len(list(Path("/dev").glob("video*"))),
        failed_count=failed_systemd_count(), throttle=throttle_label(),
        services_ok=all((systemctl_active("ssh.service"),
                         systemctl_active("NetworkManager.service"),
                         systemctl_active("lcd-arthexis.service"),
                         systemctl_active("lcd-lockfile.service", user=True))),
        wifi_line1=wifi_summary()[0], wifi_line2=wifi_summary()[1],
        uptime=uptime_seconds(), cpu_temp=cpu_temp_c(), usb_count=usb_count(),
        rfid=rfid_state(), cpu_freq=cpu_freq_label(), process_count=process_count(),
    )
