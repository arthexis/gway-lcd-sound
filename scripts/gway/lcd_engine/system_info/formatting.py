from __future__ import annotations
import re
from .model import Frame, Snapshot
from .collectors import clean, compact, format_duration


def build_frames(snapshot: Snapshot) -> list[Frame]:
    s = snapshot
    frames = [
        Frame("host", compact(f"HOST {s.hostname}"), compact(f"{s.role} up {format_duration(s.uptime)}")),
        Frame("net", compact(f"NET {s.iface} {'ok' if s.reachable else 'no'}"), compact(s.ip_addr or "no primary ip")),
        Frame("wifi", s.wifi_line1, s.wifi_line2),
        Frame("health", compact(f"HEALTH {s.cpu_temp}"), compact(f"L{s.load1:.2f} RAM{s.ram_pct if s.ram_pct is not None else '?'}%")),
        Frame("disk", compact(f"DISK /{s.root_pct} h{s.home_pct}"), compact(f"free {s.root_free}/{s.home_free}")),
        Frame("devices", compact(f"DEV usb{s.usb_count} cam{s.camera_count}"), compact(f"i2c{','.join(s.addrs[:2]) or 'none'} {s.rfid}")),
    ]
    if s.throttle != "thr ok":
        frames.insert(5, Frame("power", compact(f"PWR {s.cpu_freq}"), compact(s.throttle)))
    if s.failed_count or not s.services_ok:
        frames.insert(6, Frame("services", compact(f"SERV fail {s.failed_count}"), compact(f"{'core ok' if s.services_ok else 'check'} p{s.process_count}")))
    if s.err_count or s.warn_count:
        frames.append(Frame("logs", compact(f"LOG e{s.err_count} w{s.warn_count}"), compact(f"last {s.last_log}")))
    return frames
