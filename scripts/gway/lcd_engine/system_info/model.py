from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Frame:
    key: str
    line1: str
    line2: str

@dataclass(frozen=True)
class Snapshot:
    hostname: str
    role: str
    iface: str
    ip_addr: str
    reachable: bool
    load1: float
    ram_pct: int | None
    root_pct: str
    root_free: str
    home_pct: str
    home_free: str
    err_count: int
    warn_count: int
    last_log: str
    addrs: list[str]
    camera_count: int
    failed_count: int
    throttle: str
    services_ok: bool
    wifi_line1: str
    wifi_line2: str
    uptime: int | None
    cpu_temp: str
    usb_count: int
    rfid: str
    cpu_freq: str
    process_count: int
