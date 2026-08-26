#!/usr/bin/env python3
"""Standalone LCD1602 runner driven by lock files.

This is intentionally host-local and independent from the Arthexis Python
runtime. It keeps the existing lockfile contract so producers can keep writing
lcd-high, lcd-low, lcd-summary, lcd-event-*.lck, and lcd-channels.lck.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import smbus  # type: ignore
except Exception:
    try:
        import smbus2 as smbus  # type: ignore
    except Exception:
        smbus = None  # type: ignore


COLUMNS = 16
ROWS = 2
DEFAULT_LOCK_DIRS = (
    Path.home() / ".local" / "state" / "lcd-lockfiles",
    Path("/home/arthe/arthexis/.locks"),
)
STATE_DIR = Path.home() / ".local" / "state" / "lcd-lockfile-runner"
LOG_FILE = STATE_DIR / "lcd-lockfile-runner.log"
WORK_FILE = STATE_DIR / "lcd-screen.txt"
HISTORY_FILE = STATE_DIR / "lcd-history.ndjson"

CHANNEL_FILES = {
    "high": "lcd-high",
    "low": "lcd-low",
    "summary": "lcd-summary",
    "github": "lcd-github",
    "clock": "clock",
    "uptime": "uptime",
    "stats": "stats",
    "usb": "lcd-usb",
}
KNOWN_CHANNELS = frozenset((*CHANNEL_FILES, "script"))
EVENT_PREFIX = "lcd-event-"
EVENT_GLOB = "lcd-event-*.lck"
CHANNEL_ORDER_FILE = "lcd-channels.lck"
ROTATION_SCRIPT_FILE = "lcd-rotation.script"
TIMINGS_FILE = "lcd-timings"
DEFAULT_ORDER = ("high", "low", "stats", "clock")
MIN_EVENT_SECONDS = 10.0
DEFAULT_HIGH_HOLD_SECONDS = 60.0


STOP = False
EVENT_INTERRUPT = False


def log(message: str, **fields: object) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "message": message,
        **fields,
    }
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def parse_datetime(raw: object) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean_line(text: object, *, limit: int = 64) -> str:
    value = "" if text is None else str(text)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " ", value)
    value = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in value)
    return value[:limit]


@dataclass(frozen=True)
class Payload:
    line1: str
    line2: str
    label: str
    expires_at: datetime | None = None
    source: Path | None = None

    @property
    def has_text(self) -> bool:
        return bool(self.line1.strip() or self.line2.strip())


@dataclass(frozen=True)
class EventPayload:
    lines: tuple[str, ...]
    expires_at: datetime
    source: Path


@dataclass
class ChannelState:
    payloads: list[Payload]
    index: int = 0

    def next(self) -> Payload | None:
        if not self.payloads:
            return None
        payload = self.payloads[self.index % len(self.payloads)]
        self.index = (self.index + 1) % len(self.payloads)
        return payload


def is_do_nothing_payload(line1: str, line2: str, label: str) -> bool:
    compacted = re.sub(r"\s+", " ", f"{line1} {line2}".strip().lower())
    if label in {"low", "summary"}:
        if "routine" in compacted and ("no action" in compacted or "0x/60m" in compacted):
            return True
        if "no err/wrn logs" in compacted or "ok no err/warn" in compacted:
            return True
    if label == "script":
        if compacted.startswith("work ") and "todo" in compacted:
            return True
        if compacted.startswith("log e0 w0") and "last none" in compacted:
            return True
        if compacted.startswith("serv fail 0") and "core ok" in compacted:
            return True
        if compacted.startswith("pwr ") and "thr ok" in compacted:
            return True
    return False


def read_channel_payload(path: Path, label: str, *, now: datetime) -> Payload | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log("lock-read-failed", path=str(path), error=str(exc))
        return None

    expires_at = parse_datetime(lines[2]) if len(lines) > 2 else None
    if expires_at and expires_at <= now:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    line1 = clean_line(lines[0] if lines else "")
    line2 = clean_line(lines[1] if len(lines) > 1 else "")
    if is_do_nothing_payload(line1, line2, label):
        return None
    return Payload(line1=line1, line2=line2, label=label, expires_at=expires_at, source=path)


def channel_lock_entries(lock_dir: Path, base_name: str) -> list[Path]:
    if not lock_dir.is_dir():
        return []
    entries: list[tuple[int, Path]] = []
    prefix = f"{base_name}-"
    for path in lock_dir.iterdir():
        name = path.name
        if name == base_name:
            entries.append((0, path))
        elif name.startswith(prefix):
            suffix = name[len(prefix) :]
            if suffix.isdigit():
                entries.append((int(suffix), path))
    return [path for _num, path in sorted(entries, key=lambda item: item[0])]


def load_channel_payloads(lock_dirs: Iterable[Path], channel: str, *, now: datetime) -> list[Payload]:
    base_name = CHANNEL_FILES[channel]
    payloads: list[Payload] = []
    for lock_dir in lock_dirs:
        for path in channel_lock_entries(lock_dir, base_name):
            payload = read_channel_payload(path, channel, now=now)
            if payload and payload.has_text:
                payloads.append(payload)
    return payloads


def event_sort_key(path: Path) -> tuple[int, str]:
    name = path.name
    if name.startswith(EVENT_PREFIX) and name.endswith(".lck"):
        suffix = name[len(EVENT_PREFIX) : -4]
        if suffix.isdigit():
            return int(suffix), name
    return 10**9, name


def parse_event_lock(path: Path, *, now: datetime) -> EventPayload | None:
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        log("event-read-failed", path=str(path), error=str(exc))
        return None

    expires_at: datetime | None = None
    message_lines = raw_lines[:]
    if raw_lines:
        candidate = parse_datetime(raw_lines[-1])
        if candidate is not None:
            expires_at = candidate
            message_lines = raw_lines[:-1]
    if expires_at is None:
        expires_at = now + timedelta(hours=1)
    if expires_at <= now:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    lines = tuple(clean_line(line) for line in message_lines)
    if not any(line.strip() for line in lines):
        try:
            path.unlink()
        except OSError:
            pass
        log("empty-event-lock-removed", path=str(path))
        return None
    return EventPayload(lines=lines, expires_at=expires_at, source=path)


def load_next_event(lock_dirs: Iterable[Path], *, now: datetime) -> EventPayload | None:
    candidates: list[Path] = []
    for lock_dir in lock_dirs:
        if lock_dir.is_dir():
            candidates.extend(lock_dir.glob(EVENT_GLOB))
    for path in sorted(candidates, key=event_sort_key):
        event = parse_event_lock(path, now=now)
        if event is not None:
            return event
    for lock_dir in lock_dirs:
        for path in channel_lock_entries(lock_dir, CHANNEL_FILES["high"]):
            event = parse_high_lock(path, now=now)
            if event is not None:
                return event
    return None


def high_hold_seconds() -> float:
    try:
        return max(
            MIN_EVENT_SECONDS,
            float(os.environ.get("LCD_HIGH_HOLD_SECONDS", DEFAULT_HIGH_HOLD_SECONDS)),
        )
    except (TypeError, ValueError):
        return DEFAULT_HIGH_HOLD_SECONDS


def parse_high_lock(path: Path, *, now: datetime) -> EventPayload | None:
    """Treat legacy ``lcd-high*`` locks as preemptive, bounded events.

    An ISO-8601 value on line three is an explicit hold request. Older two-line
    sticky locks receive a lease from their mtime so a forgotten message cannot
    suppress standby forever.
    """
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        return None
    except OSError as exc:
        log("high-lock-read-failed", path=str(path), error=str(exc))
        return None

    expires_at = parse_datetime(raw_lines[2]) if len(raw_lines) > 2 else None
    if expires_at is None:
        expires_at = modified_at + timedelta(seconds=high_hold_seconds())
    if expires_at <= now:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    lines = tuple(clean_line(line) for line in raw_lines[:2])
    return EventPayload(lines=lines or ("", ""), expires_at=expires_at, source=path)


def parse_channel_order(text: str) -> list[str]:
    channels: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0]
        if not line.strip():
            continue
        for token in line.replace(",", " ").split():
            value = token.strip().lower()
            if value in {"full", "all"}:
                value = "event"
            if value == "uptime":
                value = "stats"
            if not value or value == "event" or value in seen:
                continue
            if value in KNOWN_CHANNELS:
                seen.add(value)
                channels.append(value)
    return channels


def load_channel_order(lock_dirs: Iterable[Path]) -> list[str] | None:
    for lock_dir in lock_dirs:
        path = lock_dir / CHANNEL_ORDER_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as exc:
            log("channel-order-read-failed", path=str(path), error=str(exc))
            continue
        order = parse_channel_order(text)
        if order:
            return order
    return None


def load_rotation_script(lock_dirs: Iterable[Path], *, now: datetime) -> list[Payload]:
    payloads: list[Payload] = []
    for lock_dir in lock_dirs:
        path = lock_dir / ROTATION_SCRIPT_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as exc:
            log("rotation-script-read-failed", path=str(path), error=str(exc))
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not stripped.startswith("frame "):
                continue
            parts = re.findall(r'"([^"]*)"', stripped)
            if not parts:
                continue
            payloads.append(
                Payload(
                    line1=clean_line(parts[0]),
                    line2=clean_line(parts[1] if len(parts) > 1 else ""),
                    label="script",
                    source=path,
                )
            )
    return payloads


def boot_seconds() -> int | None:
    try:
        with Path("/proc/uptime").open(encoding="utf-8") as handle:
            first = handle.read().split()[0]
        return int(float(first))
    except Exception:
        return None


def format_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "?d?h?m"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d{hours}h{minutes}m"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


def default_low_payload() -> Payload:
    return Payload(
        line1=f"UP {format_duration(boot_seconds())}",
        line2=datetime.now().strftime("%a %H:%M:%S"),
        label="low",
    )


def stats_payload() -> Payload:
    load = " ".join(f"{value:.2f}" for value in os.getloadavg()[:2])
    disk = ""
    try:
        st = os.statvfs(str(Path.home()))
        free = st.f_bavail * st.f_frsize
        total = st.f_blocks * st.f_frsize
        used_pct = int(round((1 - (free / total)) * 100)) if total else 0
        disk = f" D{used_pct}%"
    except OSError:
        pass
    return Payload(line1=f"LOAD {load}", line2=f"UP {format_duration(boot_seconds())}{disk}", label="stats")


def clock_payload() -> Payload:
    local_now = datetime.now()
    return Payload(
        line1=local_now.strftime("%p %I:%M").replace(" 0", " "),
        line2=local_now.strftime("%Y-%m-%d %a"),
        label="clock",
    )


class LCDUnavailableError(RuntimeError):
    pass


@dataclass
class LCDTimings:
    pulse_enable_delay: float = 0.002
    pulse_disable_delay: float = 0.002
    command_delay: float = 0.005
    data_delay: float = 0.003
    clear_delay: float = 0.005

    @classmethod
    def from_lock_dirs(cls, lock_dirs: Iterable[Path]) -> LCDTimings:
        def env_float(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, default))
            except (TypeError, ValueError):
                return default

        for lock_dir in lock_dirs:
            path = lock_dir / TIMINGS_FILE
            try:
                text = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            except OSError:
                continue
            values: dict[str, float] = {}
            for raw in text.splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = [part.strip() for part in line.split("=", 1)]
                if not hasattr(cls, key):
                    continue
                try:
                    values[key] = float(value)
                except ValueError:
                    continue
            if values:
                timings = cls()
                for key, value in values.items():
                    setattr(timings, key, value)
                return timings
        return cls(
            pulse_enable_delay=env_float("LCD_PULSE_ENABLE_DELAY", cls.pulse_enable_delay),
            pulse_disable_delay=env_float("LCD_PULSE_DISABLE_DELAY", cls.pulse_disable_delay),
            command_delay=env_float("LCD_COMMAND_DELAY", cls.command_delay),
            data_delay=env_float("LCD_DATA_DELAY", cls.data_delay),
            clear_delay=env_float("LCD_CLEAR_DELAY", cls.clear_delay),
        )


class I2CBus:
    def __init__(self, channel: int = 1) -> None:
        if smbus is None:
            raise LCDUnavailableError("smbus/smbus2 is not available")
        self.bus = smbus.SMBus(channel)

    def write_byte(self, addr: int, data: int) -> None:
        self.bus.write_byte(addr, data)

    def write_byte_data(self, addr: int, cmd: int, data: int) -> None:
        self.bus.write_byte_data(addr, cmd, data)

    def close(self) -> None:
        try:
            self.bus.close()
        except Exception:
            pass


class PCF8574LCD:
    columns = COLUMNS
    rows = ROWS

    def __init__(self, *, bus: I2CBus, address: int, timings: LCDTimings) -> None:
        self.bus = bus
        self.address = address
        self.backlight = 1
        self.timings = timings

    def _write_word(self, data: int) -> None:
        data = data | 0x08 if self.backlight else data & 0xF7
        self.bus.write_byte(self.address, data)

    def _pulse_enable(self, data: int) -> None:
        self._write_word(data | 0x04)
        time.sleep(self.timings.pulse_enable_delay)
        self._write_word(data & ~0x04)
        time.sleep(self.timings.pulse_disable_delay)

    def command(self, cmd: int) -> None:
        high = cmd & 0xF0
        low = (cmd << 4) & 0xF0
        self._write_word(high)
        self._pulse_enable(high)
        self._write_word(low)
        self._pulse_enable(low)
        time.sleep(self.timings.command_delay)

    def data(self, data: int) -> None:
        high = (data & 0xF0) | 0x01
        low = ((data << 4) & 0xF0) | 0x01
        self._write_word(high)
        self._pulse_enable(high)
        self._write_word(low)
        self._pulse_enable(low)
        time.sleep(self.timings.data_delay)

    def init_lcd(self) -> None:
        time.sleep(0.05)
        self.command(0x33)
        self.command(0x32)
        self.command(0x28)
        self.command(0x0C)
        self.command(0x06)
        self.clear()
        self._write_word(0x00)

    def clear(self) -> None:
        self.command(0x01)
        time.sleep(self.timings.clear_delay)

    def write_frame(self, line1: str, line2: str) -> None:
        self._write_row(0, line1)
        self._write_row(1, line2)
        self.command(0x02)

    def _write_row(self, row: int, text: str) -> None:
        padded = text[:COLUMNS].ljust(COLUMNS)
        self.command(0x80 + 0x40 * row)
        for char in padded:
            self.data(ord(char))


class AiP31068LCD:
    columns = COLUMNS
    rows = ROWS

    def __init__(self, *, bus: I2CBus, address: int = 0x3E) -> None:
        self.bus = bus
        self.address = address

    def command(self, cmd: int) -> None:
        self.bus.write_byte_data(self.address, 0x80, cmd & 0xFF)
        time.sleep(0.002)

    def data(self, data: int) -> None:
        self.bus.write_byte_data(self.address, 0x40, data & 0xFF)
        time.sleep(0.001)

    def init_lcd(self) -> None:
        time.sleep(0.05)
        self.command(0x28)
        time.sleep(0.005)
        self.command(0x28)
        time.sleep(0.005)
        self.command(0x28)
        self.command(0x08)
        self.clear()
        self.command(0x06)
        self.command(0x0C)

    def clear(self) -> None:
        self.command(0x01)
        time.sleep(0.005)

    def write_frame(self, line1: str, line2: str) -> None:
        self._write_row(0, line1)
        self._write_row(1, line2)
        self.command(0x02)

    def _write_row(self, row: int, text: str) -> None:
        padded = text[:COLUMNS].ljust(COLUMNS)
        self.command(0x80 + 0x40 * row)
        for char in padded:
            self.data(ord(char))


def i2c_scan() -> set[int]:
    try:
        output = subprocess.check_output(["i2cdetect", "-y", "1"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return set()
    found: set[int] = set()
    for token in output.split():
        if re.fullmatch(r"[0-9a-fA-F]{2}", token):
            found.add(int(token, 16))
    return found


def prepare_lcd(lock_dirs: Iterable[Path], *, driver_preference: str = "auto"):
    bus = I2CBus(1)
    addresses = i2c_scan()
    preference = driver_preference.lower().strip() or "auto"
    try:
        if preference in {"aip", "aip31068", "waveshare"}:
            lcd = AiP31068LCD(bus=bus, address=0x3E)
        elif preference in {"pcf", "pcf8574", "pcf8574a"}:
            address = 0x3F if 0x3F in addresses else 0x3E if 0x3E in addresses else 0x27
            lcd = PCF8574LCD(bus=bus, address=address, timings=LCDTimings.from_lock_dirs(lock_dirs))
        else:
            if 0x27 in addresses or 0x3F in addresses:
                address = 0x3F if 0x3F in addresses else 0x27
                lcd = PCF8574LCD(bus=bus, address=address, timings=LCDTimings.from_lock_dirs(lock_dirs))
            elif 0x3E in addresses:
                lcd = AiP31068LCD(bus=bus, address=0x3E)
            else:
                lcd = PCF8574LCD(bus=bus, address=0x27, timings=LCDTimings.from_lock_dirs(lock_dirs))
        lcd.init_lcd()
        return lcd, bus
    except Exception:
        bus.close()
        raise


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.lock_dirs = [Path(path).expanduser() for path in args.lock_dir]
        self.lock_dirs = list(dict.fromkeys(self.lock_dirs))
        self.channels: dict[str, ChannelState] = {}
        self.order: tuple[str, ...] = DEFAULT_ORDER
        self.order_index = 0
        self.event: EventPayload | None = None
        self.event_line_index = 0
        self.lcd = None
        self.bus = None
        self.last_hardware_attempt = 0.0
        self.last_rendered: tuple[str, str] | None = None

    def setup(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        for lock_dir in self.lock_dirs:
            lock_dir.mkdir(parents=True, exist_ok=True)
            self.write_pid(lock_dir)
        self.install_signal_handlers()
        if self.args.stop_embedded:
            self.stop_embedded_lcd_runner()
        if not self.args.no_hardware:
            self.ensure_lcd(force=True)
        log("runner-start", lock_dirs=[str(path) for path in self.lock_dirs])

    def install_signal_handlers(self) -> None:
        def _stop(_signum: int, _frame: object) -> None:
            global STOP
            STOP = True

        def _event(_signum: int, _frame: object) -> None:
            global EVENT_INTERRUPT
            EVENT_INTERRUPT = True

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGHUP, _stop)
        signal.signal(signal.SIGUSR1, _event)

    def write_pid(self, lock_dir: Path) -> None:
        try:
            (lock_dir / "lcd.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        except OSError as exc:
            log("pid-write-failed", path=str(lock_dir / "lcd.pid"), error=str(exc))

    def cleanup_pid_files(self) -> None:
        for lock_dir in self.lock_dirs:
            pid_file = lock_dir / "lcd.pid"
            try:
                if pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_file.unlink()
            except OSError:
                pass

    def stop_embedded_lcd_runner(self) -> None:
        try:
            result = subprocess.run(
                ["pgrep", "-f", r"python -m apps\.screens\.lcd_screen\.runner"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return
        for raw in result.stdout.splitlines():
            try:
                pid = int(raw.strip())
            except ValueError:
                continue
            if pid <= 1 or pid == os.getpid():
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                log("stopped-embedded-lcd-runner", pid=pid)
            except OSError as exc:
                log("stop-embedded-failed", pid=pid, error=str(exc))

    def ensure_lcd(self, *, force: bool = False) -> None:
        if self.args.no_hardware:
            return
        if self.lcd is not None and not force:
            return
        now = time.monotonic()
        if not force and now - self.last_hardware_attempt < 30:
            return
        self.last_hardware_attempt = now
        try:
            self.lcd, self.bus = prepare_lcd(
                self.lock_dirs,
                driver_preference=os.environ.get("LCD_DRIVER", "auto"),
            )
            self.last_rendered = None
            log("lcd-ready")
        except Exception as exc:
            self.lcd = None
            if self.bus is not None:
                try:
                    self.bus.close()
                except Exception:
                    pass
            self.bus = None
            log("lcd-unavailable", error=str(exc))

    def load_channels(self, now: datetime) -> None:
        states: dict[str, ChannelState] = {}
        for channel in CHANNEL_FILES:
            payloads = load_channel_payloads(self.lock_dirs, channel, now=now)
            old_index = self.channels.get(channel, ChannelState([])).index
            states[channel] = ChannelState(payloads=payloads, index=old_index)
        script_payloads = load_rotation_script(self.lock_dirs, now=now)
        states["script"] = ChannelState(
            payloads=script_payloads,
            index=self.channels.get("script", ChannelState([])).index,
        )
        self.channels = states

    def channel_available(self, label: str) -> bool:
        if label in {"low", "stats", "clock"}:
            return True
        return bool(self.channels.get(label) and self.channels[label].payloads)

    def configure_order(self) -> None:
        configured = load_channel_order(self.lock_dirs)
        if configured:
            order = tuple(
                label for label in configured if label != "high" and self.channel_available(label)
            )
            self.order = order or ("clock",)
            self.order_index %= len(self.order)
            return

        if self.channel_available("script"):
            normal = ("script",)
        else:
            normal = ("low", "stats", "clock")

        if self.channel_available("github"):
            normal = (*normal[:-1], "github", normal[-1])
        if self.channel_available("usb"):
            normal = (*normal[:-1], "usb", normal[-1])
        if self.channel_available("summary"):
            interleaved: list[str] = []
            for label in normal:
                interleaved.extend((label, "summary"))
            self.order = tuple(interleaved)
        else:
            self.order = normal
        self.order_index %= len(self.order)

    def current_payload(self, now: datetime) -> Payload:
        label = self.order[self.order_index]
        state = self.channels.get(label)
        payload = state.next() if state else None
        if payload and payload.has_text:
            return payload
        if label in {"low", "uptime"}:
            return default_low_payload()
        if label == "stats":
            return stats_payload()
        if label == "clock":
            return clock_payload()
        return Payload("", "", label=label)

    def active_event(self, now: datetime) -> EventPayload | None:
        global EVENT_INTERRUPT
        if EVENT_INTERRUPT:
            self.event = None
            self.event_line_index = 0
            EVENT_INTERRUPT = False
        next_event = load_next_event(self.lock_dirs, now=now)
        if next_event is None:
            self.event = None
            self.event_line_index = 0
            return None
        if (
            self.event is None
            or self.event.source != next_event.source
            or self.event.lines != next_event.lines
        ):
            self.event_line_index = 0
        self.event = next_event
        return self.event

    def event_payload(self, event: EventPayload) -> Payload:
        max_index = max(len(event.lines) - 2, 0)
        self.event_line_index = min(self.event_line_index, max_index)
        line1 = event.lines[self.event_line_index] if event.lines else ""
        line2 = event.lines[self.event_line_index + 1] if len(event.lines) > self.event_line_index + 1 else ""
        if max_index:
            self.event_line_index = (self.event_line_index + 1) % (max_index + 1)
        return Payload(line1=line1, line2=line2, label="event", expires_at=event.expires_at, source=event.source)

    def frame_for_payload(self, payload: Payload, step: int) -> tuple[str, str]:
        return scroll_segment(payload.line1, step), scroll_segment(payload.line2, step)

    def write_frame(self, line1: str, line2: str, label: str) -> None:
        row1 = line1[:COLUMNS].ljust(COLUMNS)
        row2 = line2[:COLUMNS].ljust(COLUMNS)
        self.ensure_lcd()
        if self.last_rendered == (row1, row2):
            return
        WORK_FILE.parent.mkdir(parents=True, exist_ok=True)
        WORK_FILE.write_text(f"{row1}\n{row2}\n", encoding="utf-8")
        with HISTORY_FILE.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "line1": row1,
                        "line2": row2,
                        "label": label,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        self.last_rendered = (row1, row2)
        if self.lcd is None:
            return
        try:
            self.lcd.write_frame(row1, row2)
        except Exception as exc:
            log("lcd-write-failed", error=str(exc), label=label)
            self.lcd = None
            self.last_rendered = None

    def run_once(self) -> int:
        now = now_utc()
        self.load_channels(now)
        self.configure_order()
        event = self.active_event(now)
        payload = self.event_payload(event) if event else self.current_payload(now)
        line1, line2 = self.frame_for_payload(payload, 0)
        if self.args.dry_run:
            print(f"{payload.label}: {line1!r} / {line2!r}")
        else:
            self.write_frame(line1, line2, payload.label)
        return 0

    def run_forever(self) -> int:
        self.setup()
        try:
            while not STOP:
                if self.args.stop_embedded:
                    self.stop_embedded_lcd_runner()
                now = now_utc()
                self.load_channels(now)
                self.configure_order()
                event = self.active_event(now)
                if event:
                    payload = self.event_payload(event)
                    duration = min(
                        max(MIN_EVENT_SECONDS, self.args.event_seconds),
                        max(1.0, (event.expires_at - now).total_seconds()),
                    )
                else:
                    payload = self.current_payload(now)
                    duration = self.args.rotation_seconds
                started = time.monotonic()
                step = 0
                while not STOP and time.monotonic() - started < duration:
                    line1, line2 = self.frame_for_payload(payload, step)
                    self.write_frame(line1, line2, payload.label)
                    step += 1
                    time.sleep(self.args.poll_seconds)
                    if EVENT_INTERRUPT:
                        break
                if not event and self.order:
                    self.order_index = (self.order_index + 1) % len(self.order)
        finally:
            self.cleanup_pid_files()
            if self.bus is not None:
                self.bus.close()
            log("runner-stop")
        return 0


def scroll_segment(text: str, step: int) -> str:
    clean = clean_line(text)
    if len(clean) <= COLUMNS:
        return clean.ljust(COLUMNS)
    padded = f"{clean}   "
    span = max(len(padded) - COLUMNS + 1, 1)
    index = step % span
    return padded[index : index + COLUMNS].ljust(COLUMNS)


def parse_lock_dirs(values: list[str] | None) -> list[Path]:
    raw_values: list[str] = []
    env_value = os.environ.get("LCD_LOCK_DIRS")
    if env_value:
        raw_values.extend(part for part in env_value.split(":") if part)
    if values:
        raw_values.extend(values)
    if not raw_values:
        raw_values = [str(path) for path in DEFAULT_LOCK_DIRS if path.exists() or path == DEFAULT_LOCK_DIRS[0]]
    return [Path(raw).expanduser() for raw in raw_values]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone lockfile-driven LCD1602 runner.")
    parser.add_argument("--lock-dir", action="append", default=None, help="Directory containing lcd-* lockfiles; may be repeated.")
    parser.add_argument("--rotation-seconds", type=float, default=float(os.environ.get("LCD_ROTATION_SECONDS", "10")))
    parser.add_argument("--event-seconds", type=float, default=float(os.environ.get("LCD_EVENT_FRAME_SECONDS", "10")))
    parser.add_argument("--poll-seconds", type=float, default=float(os.environ.get("LCD_POLL_SECONDS", "0.5")))
    parser.add_argument("--no-hardware", action="store_true", help="Write only the fallback work/history files.")
    parser.add_argument("--stop-embedded", action="store_true", help="Stop embedded apps.screens.lcd_screen.runner processes owned by this user.")
    parser.add_argument("--once", action="store_true", help="Render one frame and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected frame instead of writing LCD/fallback output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.event_seconds = max(MIN_EVENT_SECONDS, args.event_seconds)
    args.lock_dir = parse_lock_dirs(args.lock_dir)
    runner = Runner(args)
    if args.once:
        if not args.dry_run:
            runner.setup()
        return runner.run_once()
    return runner.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
