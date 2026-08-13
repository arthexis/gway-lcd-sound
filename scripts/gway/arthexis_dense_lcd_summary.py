#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path("/home/arthe/arthexis")
PYTHON = BASE_DIR / ".venv" / "bin" / "python"
DB_PATH = BASE_DIR / "db.sqlite3"
LOCK_DIR = BASE_DIR / ".locks"
LOW_LOCK = LOCK_DIR / "lcd-low"
EXPIRES_AFTER = timedelta(minutes=10)
MAX_FRAMES = 6
STATUS_COMMAND_TIMEOUT_SECONDS = 1.5
STATUS_JOURNAL_LOOKBACK = "2 hours ago"
STATUS_JOURNAL_MAX_LINES = 80
JOURNAL_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T(?P<hhmm>\d{2}:\d{2}):")
STATUS_JOURNAL_KEEP_PATTERNS = (
    "fat-fs",
    "fat read failed",
    "asking for cache data failed",
    "i/o error",
    "usb write fail",
    "failed to start",
    "failed with result",
)
STATUS_JOURNAL_DROP_PATTERNS = (
    "bluetoothd",
    "connection closed by remote host",
    "kex_exchange_identification",
    "src/plugin.c:init_plugin",
)
USB_ROLE_LABELS = {
    "bastion-unlock": "bastion",
    "kindle-postbox": "kindle",
}

TASK_ALIASES = {
    "apps.core.tasks.heartbeat": "HB ok",
    "apps.ocpp.tasks.setup_forwarders": "OCPP fwd",
    "apps.ocpp.tasks.send_offline_charge_point_notifications": "OCPP note",
    "terminals.ensure_agent_terminals": "Term chk",
}
SOURCE_ALIASES = {
    "apps.core.tasks.heartbeat": "HB",
    "celery.beat": "Beat",
    "celery.worker.strategy": "Worker",
    "celery.app.trace": "Task trace",
    "apps.ocpp": "OCPP",
}
TASK_RE = re.compile(r"Task ([\w.]+)\[")
DUE_TASK_RE = re.compile(r"Sending due task [\w-]+ \(([\w.]+)\)")
SOURCE_RE = re.compile(r"^(?:DBG|INF|WRN|ERR|CRI)\s+([\w.]+):")


def main() -> int:
    subprocess.run(
        [str(PYTHON), "manage.py", "summary", "--run-now"],
        cwd=BASE_DIR,
        check=True,
    )
    prompt = _last_prompt()
    frames = _summarize(prompt)
    output = "\n---\n".join(f"{line1}\n{line2}" for line1, line2 in frames)
    _write_frames(frames)
    _store_last_output(output)
    return 0


def _last_prompt() -> str:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "select last_prompt from summary_llmsummaryconfig "
            "where slug='lcd-log-summary'"
        ).fetchone()
    return str(row[0] if row else "")


def _store_last_output(output: str) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "update summary_llmsummaryconfig set last_output=?, updated_at=? "
            "where slug='lcd-log-summary'",
            (output, now),
        )


def _summarize(prompt: str) -> list[tuple[str, str]]:
    log_lines: list[str] = []
    in_logs = False
    for line in prompt.splitlines():
        if line.strip() == "LOGS:":
            in_logs = True
            continue
        if in_logs and line.strip() and not line.startswith("["):
            log_lines.append(line)

    if not log_lines:
        status_frames = _status_frames()
        if status_frames:
            return status_frames[:MAX_FRAMES]
        return [("Quiet", "No new logs")]

    error_lines = [line for line in log_lines if _severity(line) == "ERR"]
    warn_lines = [line for line in log_lines if _severity(line) == "WRN"]
    task_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for line in log_lines:
        task_label = _task_label(line)
        if task_label:
            task_counts[task_label] = task_counts.get(task_label, 0) + 1
            continue
        source_label = _source_label(line)
        if source_label:
            source_counts[source_label] = source_counts.get(source_label, 0) + 1

    frames: list[tuple[str, str]] = []
    if error_lines or warn_lines:
        frames.append(
            (
                f"ERR {len(error_lines)} WRN {len(warn_lines)}",
                _compact_line((error_lines or warn_lines)[-1]),
            )
        )
    else:
        frames.append(("OK no err/warn", f"{len(log_lines)} lines"))

    for line in (error_lines + warn_lines)[-2:]:
        frames.append((_severity(line), _compact_line(line)))
    for label, count in _top_counts(task_counts, limit=4):
        frames.append((label, f"{count}x /5m"))
    if len(frames) < 3:
        for label, count in _top_counts(source_counts, limit=3):
            frames.append((label, f"{count}x /5m"))
    if len(frames) == 1:
        frames.append(("Routine only", "No action"))
    return frames[:MAX_FRAMES]


def _severity(line: str) -> str:
    if line.startswith("ERR ") or " raised unexpected" in line:
        return "ERR"
    if line.startswith("WRN ") or line.startswith("CRI "):
        return "WRN"
    return "OK"


def _alias(value: str, aliases: dict[str, str]) -> str:
    for prefix, label in aliases.items():
        if value == prefix or value.startswith(f"{prefix}."):
            return label
    return value.rsplit(".", 1)[-1].replace("_", " ")[:16]


def _task_label(line: str) -> str | None:
    match = DUE_TASK_RE.search(line) or TASK_RE.search(line)
    if not match:
        return "HB ok" if "Heartbeat task executed" in line else None
    return _alias(match.group(1), TASK_ALIASES)


def _source_label(line: str) -> str | None:
    match = SOURCE_RE.match(line)
    if not match:
        return None
    return _alias(match.group(1), SOURCE_ALIASES)


def _top_counts(counts: dict[str, int], *, limit: int) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def _status_frames() -> list[tuple[str, str]]:
    frames: list[tuple[str, str]] = []
    frames.extend(_systemd_failed_frames())
    frames.extend(_journal_frames())
    frames.extend(_usb_inventory_frames())
    host_frame = _host_resource_frame()
    if host_frame:
        frames.append(host_frame)
    return _dedupe_frames(frames)


def _run_status_command(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=STATUS_COMMAND_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None


def _systemd_failed_frames() -> list[tuple[str, str]]:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return []
    result = _run_status_command(
        [systemctl, "--failed", "--no-legend", "--plain", "--no-pager"]
    )
    if result is None or result.returncode not in {0, 1}:
        return []
    units = [line.split()[0].removesuffix(".service") for line in result.stdout.splitlines() if line.split()]
    if not units:
        return [("Status", "0 failed units")]
    shown = ", ".join(units[:2])
    suffix = "" if len(units) <= 2 else f" +{len(units) - 2}"
    return [("ERR Status", f"failed {shown}{suffix}")]


def _journal_frames() -> list[tuple[str, str]]:
    journalctl = shutil.which("journalctl")
    if not journalctl:
        return []
    result = _run_status_command(
        [
            journalctl,
            "-p",
            "3",
            "-b",
            "--since",
            STATUS_JOURNAL_LOOKBACK,
            "--lines",
            str(STATUS_JOURNAL_MAX_LINES),
            "--no-pager",
            "--output=short-iso",
        ]
    )
    if result is None or result.returncode not in {0, 1}:
        return []

    grouped: dict[str, dict[str, object]] = {}
    for raw_line in result.stdout.splitlines():
        lowered = raw_line.lower()
        if not lowered.strip():
            continue
        if any(pattern in lowered for pattern in STATUS_JOURNAL_DROP_PATTERNS):
            continue
        if not any(pattern in lowered for pattern in STATUS_JOURNAL_KEEP_PATTERNS):
            continue
        label = _journal_label(lowered, raw_line)
        entry = grouped.setdefault(label, {"count": 0, "last": ""})
        entry["count"] = int(entry["count"]) + 1
        match = JOURNAL_TIME_RE.search(raw_line)
        if match:
            entry["last"] = match.group("hhmm")

    frames: list[tuple[str, str]] = []
    for label, entry in sorted(
        grouped.items(), key=lambda item: (-int(item[1]["count"]), item[0])
    )[:3]:
        last = f" {entry['last']}" if entry.get("last") else ""
        frames.append(("ERR Journal", f"{label} x{entry['count']}{last}"))
    return frames


def _journal_label(lowered: str, raw_line: str) -> str:
    if "fat-fs" in lowered or "fat read failed" in lowered:
        return "USB FAT sda1"
    if "asking for cache data failed" in lowered:
        return "USB cache sda"
    if "usb write fail" in lowered:
        return "USB write fail"
    failed_start = re.search(r"Failed to start ([^:.]+)", raw_line)
    if failed_start:
        return f"failed {failed_start.group(1).strip()[:12]}"
    if "failed with result" in lowered:
        return "unit failed"
    return "system error"


def _usb_inventory_frames() -> list[tuple[str, str]]:
    path = Path("/run/arthexis-usb/devices.json")
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    devices = inventory.get("devices")
    if not isinstance(devices, list):
        return []
    frames: list[tuple[str, str]] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        if device.get("transport") != "usb" or device.get("type") != "part":
            continue
        name = str(device.get("name") or device.get("path") or "usb")
        label = str(device.get("label") or device.get("fstype") or "device")
        roles = device.get("claimed_roles") or []
        role = USB_ROLE_LABELS.get(str(roles[0]), str(roles[0])) if roles else "mounted"
        mounts = device.get("mounts") or []
        if not mounts:
            frames.append(("WRN USB key", f"{name} {label} unmounted"))
            continue
        read_only = any(isinstance(mount, dict) and mount.get("read_only") for mount in mounts)
        mode = "ro" if read_only else "rw"
        if role != "mounted":
            frames.append(("USB key", f"{name} {mode} {role}"))
        else:
            frames.append(("USB key", f"{name} {label} {mode}"))
    return frames[:2]


def _host_resource_frame() -> tuple[str, str] | None:
    parts: list[str] = []
    temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        raw_temp = temp_path.read_text(encoding="utf-8").strip()
        temp_c = float(raw_temp)
        if temp_c > 1000:
            temp_c = temp_c / 1000
        parts.append(f"t{round(temp_c)}C")
    except (OSError, ValueError):
        pass
    try:
        usage = shutil.disk_usage(BASE_DIR)
        if usage.total:
            parts.append(f"d{round((usage.used / usage.total) * 100)}%")
    except OSError:
        pass
    mem_percent = _memory_used_percent()
    if mem_percent is not None:
        parts.append(f"m{mem_percent}%")
    if not parts:
        return None
    return ("Host", " ".join(parts))


def _memory_used_percent() -> int | None:
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    values: dict[str, int] = {}
    for line in lines:
        key, _separator, rest = line.partition(":")
        if key not in {"MemTotal", "MemAvailable"}:
            continue
        try:
            values[key] = int(rest.strip().split()[0])
        except (IndexError, ValueError):
            continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return round(((total - available) / total) * 100)


def _dedupe_frames(frames: list[tuple[str, str]]) -> list[tuple[str, str]]:
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for subject, body in frames:
        frame = (_compact_line(subject), _compact_line(body))
        if frame in seen:
            continue
        seen.add(frame)
        deduped.append(frame)
    return deduped


def _compact_line(line: str) -> str:
    cleaned = re.sub(r"^(?:DBG|INF|WRN|ERR|CRI)\s+", "", line)
    cleaned = re.sub(r"\[[^\]]+\]", "", cleaned)
    cleaned = cleaned.replace("Task ", "")
    cleaned = cleaned.replace("raised unexpected:", "raised:")
    cleaned = cleaned.replace("Scheduler: Sending due task", "due")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned or "-")[:16].rstrip()


def _write_frames(frames: list[tuple[str, str]]) -> None:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    expires_at = (datetime.now(timezone.utc) + EXPIRES_AFTER).isoformat()
    for candidate in LOCK_DIR.glob("lcd-low-*"):
        suffix = candidate.name[len("lcd-low-") :]
        if suffix.isdigit():
            candidate.unlink(missing_ok=True)
    for index, (line1, line2) in enumerate(frames):
        target = LOW_LOCK if index == 0 else LOCK_DIR / f"lcd-low-{index}"
        target.write_text(
            f"{line1.strip()[:64]}\n{line2.strip()[:64]}\n{expires_at}\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(main())
