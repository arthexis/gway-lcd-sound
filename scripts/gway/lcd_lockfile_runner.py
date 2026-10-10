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

# Allow the installed standalone script to locate the adjacent pure LCD engine.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lcd_engine.model import Payload, EventPayload, ChannelState
from lcd_engine.rendering import clean_line, scroll_segment
from lcd_engine.scheduler import Scheduler
from lcd_engine.lockfiles import (
    CHANNEL_FILES, KNOWN_CHANNELS, EVENT_PREFIX, EVENT_GLOB, RUNNER_LOCK,
    CHANNEL_ORDER_FILE, ROTATION_SCRIPT_FILE, TIMINGS_FILE,
    configure_logger, parse_datetime, is_do_nothing_payload,
    read_channel_payload, channel_lock_entries, load_channel_payloads,
    event_sort_key, parse_event_lock, active_runner_payload, load_next_event,
    parse_channel_order, load_channel_order, load_rotation_script,
)

from lcd_engine.hardware.bus import I2CBus, LCDUnavailableError
from lcd_engine.hardware.pcf8574 import PCF8574LCD, LCDTimings
from lcd_engine.hardware.aip31068 import AiP31068LCD
from lcd_engine.hardware.discovery import i2c_scan, prepare_lcd



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
CURRENT_FRAME_FILE = STATE_DIR / "lcd-current.json"

DEFAULT_ORDER = ("high", "low", "stats", "clock")


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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


configure_logger(log)


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
        if self.lcd is not None:
            self.lcd.close()
            self.lcd = None
            self.bus = None
        try:
            self.lcd, self.bus = prepare_lcd(
                self.lock_dirs,
                driver_preference=os.environ.get("LCD_DRIVER", "auto"),
            )
            log("lcd-ready")
        except Exception as exc:
            self.lcd = None
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
            order = tuple(label for label in configured if self.channel_available(label))
            self.order = order or ("clock",)
            self.order_index %= len(self.order)
            return

        if self.channel_available("script"):
            normal = ("script",)
        elif self.channel_available("high"):
            normal = ("high", "low", "stats", "clock")
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
        if self.event is not None and self.event.expires_at > now:
            return self.event
        if self.event is not None and self.event.expires_at <= now:
            try:
                self.event.source.unlink()
            except OSError:
                pass
        self.event = load_next_event(self.lock_dirs, now=now)
        self.event_line_index = 0
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
        self.ensure_lcd()
        if self.lcd is None:
            return
        try:
            self.lcd.write_frame(row1, row2)
            frame = {"ts": datetime.now(timezone.utc).isoformat(),
                     "label": label, "line1": row1, "line2": row2}
            temp = CURRENT_FRAME_FILE.with_suffix(f".{os.getpid()}.tmp")
            try:
                temp.write_text(json.dumps(frame, sort_keys=True) + "\\n", encoding="utf-8")
                os.replace(temp, CURRENT_FRAME_FILE)
            finally:
                temp.unlink(missing_ok=True)
        except Exception as exc:
            log("lcd-write-failed", error=str(exc), label=label)
            try:
                self.lcd.close()
            except Exception:
                pass
            self.lcd = None
            self.bus = None

    @staticmethod
    def show_current(*, as_json: bool = False) -> int:
        """Read the last successful hardware write; never touch the I2C bus."""
        try:
            frame = json.loads(CURRENT_FRAME_FILE.read_text(encoding="utf-8"))
            if not isinstance(frame, dict) or not all(
                isinstance(frame.get(k), str) for k in ("ts", "label", "line1", "line2")
            ):
                raise ValueError("invalid current frame")
        except (OSError, ValueError) as exc:
            print(f"No confirmed LCD frame: {exc}", file=sys.stderr)
            return 1
        if as_json:
            print(json.dumps(frame, sort_keys=True))
        else:
            print(f"Last successful LCD write: {frame['ts']} [{frame['label']}]")
            print(f"|{frame['line1']}|")
            print(f"|{frame['line2']}|")
        return 0

    def run_once(self) -> int:
        now = now_utc()
        self.load_channels(now)
        self.configure_order()
        runner = active_runner_payload(self.lock_dirs, now=now)
        event = self.active_event(now) if runner is None else None
        payload = runner or (self.event_payload(event) if event else self.current_payload(now))
        line1, line2 = self.frame_for_payload(payload, 0)
        if self.args.dry_run:
            print(f"{payload.label}: {line1!r} / {line2!r}")
        else:
            self.write_frame(line1, line2, payload.label)
        return 0

    def run_forever(self) -> int:
        self.setup()
        scheduler = Scheduler(
            rotation_seconds=self.args.rotation_seconds,
            event_seconds=self.args.event_seconds,
        )
        normal_payload: Payload | None = None
        event_payload: Payload | None = None
        event_source: Path | None = None
        try:
            while not STOP:
                if self.args.stop_embedded:
                    self.stop_embedded_lcd_runner()
                now = now_utc()
                self.load_channels(now)
                self.configure_order()
                if normal_payload is None:
                    normal_payload = self.current_payload(now)
                runner = active_runner_payload(self.lock_dirs, now=now)
                event = self.active_event(now) if runner is None else None
                if event is None:
                    event_payload = None
                    event_source = None
                elif event_payload is None or event.source != event_source:
                    event_source = event.source
                    event_payload = self.event_payload(event)
                choice = scheduler.tick(
                    now=now,
                    monotonic=time.monotonic(),
                    runner=runner,
                    event=event_payload,
                    normal=normal_payload,
                )
                line1, line2 = self.frame_for_payload(choice.payload, choice.scroll_step)
                self.write_frame(line1, line2, choice.payload.label)
                if choice.advance_normal:
                    if self.order:
                        self.order_index = (self.order_index + 1) % len(self.order)
                    normal_payload = None
                if choice.advance_event:
                    event_payload = None
                time.sleep(self.args.poll_seconds)
        finally:
            self.cleanup_pid_files()
            if self.lcd is not None:
                self.lcd.close()
            log("runner-stop")
        return 0


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
    parser.add_argument("--show-current", action="store_true", help="Read last confirmed physical LCD frame without I2C access.")
    parser.add_argument("--json", action="store_true", help="JSON output with --show-current.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected frame instead of writing LCD/fallback output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.lock_dir = parse_lock_dirs(args.lock_dir)
    if args.show_current:
        return Runner.show_current(as_json=args.json)
    if args.json:
        parser.error("--json requires --show-current")
    runner = Runner(args)
    if args.once:
        if not args.dry_run:
            runner.setup()
        return runner.run_once()
    return runner.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
