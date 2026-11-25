from __future__ import annotations
import re
from .model import Frame, Snapshot
from .collectors import clean, compact, format_duration


def health_metrics(load: float, ram_used: int | None) -> str:
    free = 100 - ram_used if ram_used is not None else "?"
    memory = f"FRAM{free}%"
    for precision in (2, 1, 0):
        line = f"L{load:.{precision}f} {memory}"
        if len(line) <= 16:
            return line
    return memory


def build_frames(snapshot: Snapshot) -> list[Frame]:
    s = snapshot
    frames = [
        Frame("host", compact(f"HOST {s.hostname}"), compact(f"{s.role} up {format_duration(s.uptime)}")),
        Frame("net", compact(f"NET {s.iface} {'ok' if s.reachable else 'no'}"), compact(s.ip_addr or "no primary ip")),
        Frame("wifi", s.wifi_line1, s.wifi_line2),
        Frame("health", compact(f"SOC{s.cpu_temp} RTC{s.rtc_temp}"), health_metrics(s.load1, s.ram_pct)),
        Frame("disk", compact(f"DISK /{s.root_pct} h{s.home_pct}"), compact(f"free {s.root_free}/{s.home_free}")),
    ]
    if s.throttle != "thr ok":
        frames.insert(5, Frame("power", compact(f"PWR {s.cpu_freq}"), compact(s.throttle)))
    if s.deployment_lines is not None:
        frames.append(Frame("deployments", *s.deployment_lines))
    if s.err_count or s.warn_count:
        frames.append(Frame("logs", compact(f"LOG e{s.err_count} w{s.warn_count}"), compact(f"last {s.last_log}")))
    return frames
