"""Fake-I2C contract tests for the two legacy LCD controllers."""
from __future__ import annotations

import pytest
from scripts.gway.lcd_engine.hardware.discovery import select_device, prepare_lcd
from scripts.gway.lcd_engine.hardware.pcf8574 import PCF8574LCD, LCDTimings
from scripts.gway.lcd_engine.hardware.aip31068 import AiP31068LCD


class FakeBus:
    def __init__(self, channel=1):
        self.operations = []
        self.closed = False

    def write_byte(self, address, value):
        self.operations.append(("byte", address, value))

    def write_byte_data(self, address, command, value):
        self.operations.append(("data", address, command, value))

    def close(self):
        self.closed = True


@pytest.mark.parametrize(("addresses", "preference", "driver", "address"), [
    (set(), "auto", "pcf8574", 0x27),
    ({0x27, 0x3E}, "auto", "pcf8574", 0x27),
    ({0x27, 0x3F}, "auto", "pcf8574", 0x3F),
    ({0x3E}, "auto", "aip31068", 0x3E),
    ({0x27}, "waveshare", "aip31068", 0x3E),
    ({0x3E}, "pcf8574", "pcf8574", 0x3E),
])
def test_existing_address_precedence(addresses, preference, driver, address):
    selection = select_device(addresses, preference)
    assert (selection.driver, selection.address) == (driver, address)


def test_aip31068_writes_registers_and_two_rows(monkeypatch):
    monkeypatch.setattr("scripts.gway.lcd_engine.hardware.aip31068.time.sleep", lambda _: None)
    bus = FakeBus()
    display = AiP31068LCD(bus=bus)
    display.init_lcd()
    display.write_frame("Hello", "World")
    assert ("data", 0x3E, 0x80, 0x80) in bus.operations
    assert ("data", 0x3E, 0x80, 0xC0) in bus.operations
    assert sum(op[:3] == ("data", 0x3E, 0x40) for op in bus.operations) == 32
    assert ("data", 0x3E, 0x40, ord("H")) in bus.operations


def test_pcf8574_writes_both_rows_in_four_bit_mode(monkeypatch):
    monkeypatch.setattr("scripts.gway.lcd_engine.hardware.pcf8574.time.sleep", lambda _: None)
    bus = FakeBus()
    timings = LCDTimings()
    display = PCF8574LCD(bus=bus, address=0x27, timings=timings)
    display.init_lcd()
    before = len(bus.operations)
    display.write_frame("First", "Second")
    assert len(bus.operations) > before
    assert all(op[0] == "byte" and op[1] == 0x27 for op in bus.operations)
    assert display.columns == 16 and display.rows == 2


def test_failed_initialization_closes_bus(monkeypatch, tmp_path):
    class FailingBus(FakeBus):
        def write_byte_data(self, address, command, value):
            raise OSError("test I2C failure")

    created = []

    def create(channel):
        bus = FailingBus(channel)
        created.append(bus)
        return bus

    monkeypatch.setattr("scripts.gway.lcd_engine.hardware.aip31068.time.sleep", lambda _: None)
    with pytest.raises(OSError, match="test I2C failure"):
        prepare_lcd([tmp_path], driver_preference="aip31068",
                    bus_factory=create, scan=lambda: {0x3E})
    assert created and created[0].closed


def test_device_discovery_can_initialize_without_hardware(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.gway.lcd_engine.hardware.aip31068.time.sleep", lambda _: None)
    devices = []

    def create(channel):
        device = FakeBus(channel)
        devices.append(device)
        return device

    lcd, bus = prepare_lcd([tmp_path], bus_factory=create, scan=lambda: {0x3E})
    lcd.write_frame("Ready", "Online")
    assert devices == [bus]
    assert any(op[:3] == ("data", 0x3E, 0x40) for op in bus.operations)
    bus.close()
    assert bus.closed


@pytest.mark.parametrize("driver", ["aip31068", "pcf8574"])
def test_device_close_releases_bus(monkeypatch, driver):
    monkeypatch.setattr("scripts.gway.lcd_engine.hardware.aip31068.time.sleep", lambda _: None)
    monkeypatch.setattr("scripts.gway.lcd_engine.hardware.pcf8574.time.sleep", lambda _: None)
    bus = FakeBus()
    if driver == "aip31068":
        lcd = AiP31068LCD(bus=bus)
    else:
        lcd = PCF8574LCD(bus=bus, address=0x27, timings=LCDTimings())
    lcd.close()
    assert bus.closed
