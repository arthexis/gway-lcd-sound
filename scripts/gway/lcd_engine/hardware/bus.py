"""I2C bus adapter. Hardware imports occur only when opening a real bus."""
from __future__ import annotations

class LCDUnavailableError(RuntimeError):
    pass

class I2CBus:
    def __init__(self, channel: int = 1) -> None:
        try:
            import smbus
        except ImportError:
            try:
                import smbus2 as smbus
            except ImportError:
                smbus = None
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
