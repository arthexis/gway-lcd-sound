"""AiP31068 controller, preserving legacy command sequences."""
from __future__ import annotations
import time
from .bus import I2CBus
COLUMNS, ROWS = 16, 2

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

