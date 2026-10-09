"""Hardware address selection and owned device lifecycle."""
from __future__ import annotations
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable
from .bus import I2CBus
from .aip31068 import AiP31068LCD
from .pcf8574 import PCF8574LCD, LCDTimings

@dataclass(frozen=True)
class DeviceSelection:
    driver: str
    address: int


def select_device(addresses: set[int], preference: str = "auto") -> DeviceSelection:
    preference = preference.lower().strip() or "auto"
    if preference in {"aip", "aip31068", "waveshare"}:
        return DeviceSelection("aip31068", 0x3E)
    if preference in {"pcf", "pcf8574", "pcf8574a"}:
        return DeviceSelection("pcf8574", 0x3F if 0x3F in addresses else 0x3E if 0x3E in addresses else 0x27)
    if 0x27 in addresses or 0x3F in addresses:
        return DeviceSelection("pcf8574", 0x3F if 0x3F in addresses else 0x27)
    if 0x3E in addresses:
        return DeviceSelection("aip31068", 0x3E)
    return DeviceSelection("pcf8574", 0x27)


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




def prepare_lcd(lock_dirs: Iterable[Path], *, driver_preference: str = "auto",
                bus_factory=I2CBus, scan=i2c_scan):
    bus = bus_factory(1)
    try:
        selection = select_device(scan(), driver_preference)
        if selection.driver == "aip31068":
            lcd = AiP31068LCD(bus=bus, address=selection.address)
        else:
            lcd = PCF8574LCD(bus=bus, address=selection.address,
                             timings=LCDTimings.from_lock_dirs(lock_dirs))
        lcd.init_lcd()
        return lcd, bus
    except Exception:
        bus.close()
        raise
