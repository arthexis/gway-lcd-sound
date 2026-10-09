"""PCF8574/HD44780 controller, preserving legacy command sequences."""
from __future__ import annotations
import os
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable
from .bus import I2CBus
from ..lockfiles import TIMINGS_FILE
COLUMNS, ROWS = 16, 2

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

    def close(self) -> None:
        self.bus.close()

    def write_frame(self, line1: str, line2: str) -> None:
        self._write_row(0, line1)
        self._write_row(1, line2)
        self.command(0x02)

    def _write_row(self, row: int, text: str) -> None:
        padded = text[:COLUMNS].ljust(COLUMNS)
        self.command(0x80 + 0x40 * row)
        for char in padded:
            self.data(ord(char))

