#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_IFACE = "eth0"
DEFAULT_LOCK_FILE = Path("/home/arthe/arthexis/.locks/lcd-low-3")
DEFAULT_STATE_FILE = Path("/home/arthe/.local/state/gway-eth0-node-lcd/state.json")
DEFAULT_INTERVAL = 15
LCD_WIDTH = 16
BAD_NEIGHBOR_STATES = {"FAILED", "INCOMPLETE", "NOARP"}
RASPBERRY_PI_OUIS = {
    "2C:CF:67",
    "B8:27:EB",
    "DC:A6:32",
    "D8:3A:DD",
    "E4:5F:01",
}
ROLE_WORDS = {
    "TERMINAL": "TERM",
    "GATEWAY": "GWAY",
    "CONTROL": "CTRL",
    "WATCHTOWER": "WATCH",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_command(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def carrier_is_up(iface: str) -> bool:
    carrier_path = Path(f"/sys/class/net/{iface}/carrier")
    return read_text(carrier_path) == "1"


def parse_neighbors(iface: str) -> list[dict[str, str]]:
    result = run_command(["ip", "-4", "neigh", "show", "dev", iface], timeout=3)
    neighbors: list[dict[str, str]] = []
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split()
        if not parts:
            continue
        ip = parts[0]
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            continue
        state = parts[-1].upper() if parts else ""
        if state in BAD_NEIGHBOR_STATES:
            continue
        mac = ""
        if "lladdr" in parts:
            idx = parts.index("lladdr")
            if idx + 1 < len(parts):
                mac = parts[idx + 1].upper()
        neighbors.append({"ip": ip, "mac": mac, "state": state})
    return neighbors


def interface_network(iface: str) -> ipaddress.IPv4Interface | None:
    result = run_command(["ip", "-j", "-4", "addr", "show", "dev", iface], timeout=3)
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    for item in payload:
        for addr in item.get("addr_info", []):
            if addr.get("family") == "inet" and addr.get("local") and addr.get("prefixlen"):
                try:
                    return ipaddress.ip_interface(f"{addr['local']}/{addr['prefixlen']}")
                except ValueError:
                    continue
    return None


def ping_host(ip: str, timeout: int = 1) -> tuple[bool, int | None, str]:
    try:
        result = run_command(["ping", "-c", "1", "-W", str(timeout), ip], timeout=timeout + 1.5)
    except subprocess.TimeoutExpired:
        return False, None, ""
    output = f"{result.stdout}\n{result.stderr}"
    ttl_match = re.search(r"\bttl=(\d+)\b", output, flags=re.IGNORECASE)
    ttl = int(ttl_match.group(1)) if ttl_match else None
    return result.returncode == 0, ttl, output.strip()


def scan_same_24(iface: str, workers: int = 32) -> list[str]:
    iface_net = interface_network(iface)
    if iface_net is None:
        return []

    if iface_net.network.prefixlen < 24:
        network = ipaddress.ip_network(f"{iface_net.ip}/24", strict=False)
    else:
        network = iface_net.network

    local_ip = str(iface_net.ip)
    hosts = [str(ip) for ip in network.hosts() if str(ip) != local_ip]
    hosts = hosts[:512]
    found: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(ping_host, ip, 1): ip for ip in hosts}
        for future in as_completed(future_map):
            ip = future_map[future]
            try:
                ok, _ttl, _output = future.result()
            except Exception:
                ok = False
            if ok:
                found.append(ip)
    return sorted(found, key=lambda value: ipaddress.ip_address(value))


def load_previous_ip(state_file: Path) -> str:
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    ip = str(payload.get("ip") or "")
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return ""
    return ip


def choose_device(iface: str, state_file: Path, allow_scan: bool = True) -> dict[str, Any] | None:
    neighbors = parse_neighbors(iface)
    previous_ip = load_previous_ip(state_file)
    neighbor_by_ip = {item["ip"]: item for item in neighbors}

    if previous_ip and previous_ip in neighbor_by_ip:
        ok, ttl, ping_output = ping_host(previous_ip)
        if ok:
            selected = dict(neighbor_by_ip[previous_ip])
            selected.update({"ttl": ttl, "ping": ping_output})
            return selected

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in neighbors:
        ok, ttl, ping_output = ping_host(item["ip"])
        if not ok:
            continue
        state = item.get("state", "")
        score = 0
        if state == "REACHABLE":
            score += 30
        elif state in {"DELAY", "PROBE"}:
            score += 20
        elif state == "STALE":
            score += 10
        if item.get("mac"):
            score += 5
        selected = dict(item)
        selected.update({"ttl": ttl, "ping": ping_output})
        scored.append((score, selected))

    if scored:
        scored.sort(key=lambda pair: (-pair[0], ipaddress.ip_address(pair[1]["ip"])))
        return scored[0][1]

    if not allow_scan:
        return None

    scanned = scan_same_24(iface)
    if not scanned:
        return None

    refreshed_neighbors = parse_neighbors(iface)
    refreshed_by_ip = {item["ip"]: item for item in refreshed_neighbors}
    selected_ip = previous_ip if previous_ip in scanned else scanned[0]
    ok, ttl, ping_output = ping_host(selected_ip)
    if not ok:
        return None
    selected = dict(refreshed_by_ip.get(selected_ip, {"ip": selected_ip, "mac": "", "state": "PING"}))
    selected.update({"ttl": ttl, "ping": ping_output})
    return selected


def tcp_banner(ip: str, port: int, timeout: float = 1.5) -> str:
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                data = sock.recv(256)
            except TimeoutError:
                return ""
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace").strip()


def tcp_open(ip: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_raspberry_pi_mac(mac: str) -> bool:
    normalized = mac.upper().replace("-", ":")
    return any(normalized.startswith(prefix) for prefix in RASPBERRY_PI_OUIS)


def clean_word(value: str, default: str, max_len: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value or "").upper()
    if not cleaned:
        cleaned = default
    return cleaned[:max_len]


def guess_os(mac: str, ssh: str, ttl: int | None) -> str:
    text = ssh.upper()
    if "OPENSSH_FOR_WINDOWS" in text or "MICROSOFT" in text:
        return "WIN"
    if is_raspberry_pi_mac(mac) or "RASPBIAN" in text or "RASPBERRY" in text:
        return "RPIOS"
    if "UBUNTU" in text:
        return "UBUNTU"
    if "DEBIAN" in text:
        return "DEBIAN"
    if "DROPBEAR" in text:
        return "LINUX"
    if "OPENSSH" in text:
        return "LINUX"
    if ttl is not None:
        if ttl >= 120:
            return "WIN"
        if ttl <= 70:
            return "LINUX"
    return "UNK"


def http_opener() -> urllib.request.OpenerDirector:
    context = ssl._create_unverified_context()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context),
    )


def fetch_node_info(ip: str) -> dict[str, Any]:
    opener = http_opener()
    probes = [
        ("http", 8888),
        ("http", 8000),
        ("http", 80),
        ("https", 443),
        ("https", 8888),
        ("https", 8443),
    ]
    for scheme, port in probes:
        url = f"{scheme}://{ip}:{port}/nodes/info/"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "gway-eth0-node-lcd/1.0"},
        )
        try:
            with opener.open(request, timeout=2) as response:
                body = response.read(8192)
                status = int(getattr(response, "status", 0) or response.getcode())
                content_type = response.headers.get("content-type", "")
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return {"detected": True, "role": "ARTHEX", "url": url, "status": exc.code}
            continue
        except Exception:
            continue

        if status != 200:
            continue

        text = body.decode("utf-8", errors="replace")
        data: Any = None
        if "json" in content_type.lower() or text.lstrip().startswith("{"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
        if isinstance(data, dict):
            role = (
                data.get("role")
                or data.get("role_name")
                or data.get("node_role")
                or data.get("roleName")
            )
            if isinstance(role, dict):
                role = role.get("name")
            if isinstance(role, str) and role.strip():
                return {"detected": True, "role": role.strip(), "url": url, "status": status}
            if {"public_key", "hostname", "token_signature"} & set(data.keys()):
                return {"detected": True, "role": "ARTHEX", "url": url, "status": status}
        if "arthexis" in text.lower():
            return {"detected": True, "role": "ARTHEX", "url": url, "status": status}
    return {"detected": False, "role": "NONODE"}


def role_word(role: str) -> str:
    cleaned = clean_word(role, "NONODE", 10)
    return ROLE_WORDS.get(cleaned, cleaned[:8])


def fit_two_words(first: str, second: str) -> str:
    first = clean_word(first, "UNK", 7)
    second = role_word(second)
    text = f"{first} {second}".strip()
    if len(text) <= LCD_WIDTH:
        return text
    available = max(1, LCD_WIDTH - len(first) - 1)
    return f"{first} {second[:available]}"


def write_lock(lock_file: Path, subject: str, body: str, ttl_seconds: int) -> None:
    expires_at = utc_now() + timedelta(seconds=ttl_seconds)
    payload = f"{subject.strip()[:64]}\n{body.strip()[:64]}\n{expires_at.isoformat()}\n"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = lock_file.with_name(f".{lock_file.name}.tmp")
    temp_file.write_text(payload, encoding="utf-8")
    os.replace(temp_file, lock_file)


def remove_lock(lock_file: Path) -> None:
    try:
        lock_file.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"failed to remove {lock_file}: {exc}", file=sys.stderr)


def write_state(state_file: Path, payload: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = state_file.with_name(f".{state_file.name}.tmp")
    temp_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_file, state_file)


def collect(iface: str, lock_file: Path, state_file: Path, interval: int, allow_scan: bool) -> dict[str, Any]:
    record: dict[str, Any] = {
        "time": utc_now().isoformat(),
        "iface": iface,
        "lock_file": str(lock_file),
    }

    if not carrier_is_up(iface):
        remove_lock(lock_file)
        record.update({"status": "eth0_down"})
        write_state(state_file, record)
        return record

    device = choose_device(iface, state_file, allow_scan=allow_scan)
    if device is None:
        remove_lock(lock_file)
        record.update({"status": "no_device"})
        write_state(state_file, record)
        return record

    ip = device["ip"]
    mac = device.get("mac", "")
    ttl = device.get("ttl")
    ssh = tcp_banner(ip, 22)
    ports = [port for port in (22, 80, 443, 8000, 8888) if tcp_open(ip, port)]
    arthexis = fetch_node_info(ip)
    os_word = guess_os(mac, ssh, ttl)
    role = str(arthexis.get("role") or "NONODE")
    line1 = ip[:LCD_WIDTH]
    line2 = fit_two_words(os_word, role)
    lock_ttl = max(interval * 8, 120)
    write_lock(lock_file, line1, line2, lock_ttl)

    record.update(
        {
            "status": "device",
            "ip": ip,
            "mac": mac,
            "neighbor_state": device.get("state", ""),
            "ttl": ttl,
            "ssh_banner": ssh,
            "open_ports": ports,
            "arthexis": arthexis,
            "os": os_word,
            "role": role_word(role),
            "line1": line1,
            "line2": line2,
            "expires_at_seconds": lock_ttl,
        }
    )
    write_state(state_file, record)
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show the eth0 attached node on the GWAY LCD loop.")
    parser.add_argument("--iface", default=DEFAULT_IFACE)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-scan", action="store_true", help="Use neighbor table only; do not ping-scan the local /24.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    interval = max(5, int(args.interval))
    allow_scan = not args.no_scan

    while True:
        try:
            record = collect(args.iface, args.lock_file, args.state_file, interval, allow_scan)
            print(json.dumps(record, sort_keys=True), flush=True)
        except Exception as exc:
            print(f"eth0 node lcd monitor failed: {exc}", file=sys.stderr, flush=True)
        if args.once:
            break
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
