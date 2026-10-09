"""Recording I2C bus and LCD output, usable across driver and integration tests."""
from __future__ import annotations

class RecordingBus:
    def __init__(self, channel=1):
        self.channel = channel
        self.operations = []
        self.closed = False
        self.fail_next = False

    def record(self, *operation):
        if self.fail_next:
            self.fail_next = False
            raise OSError("injected I2C failure")
        self.operations.append(operation)

    def write_byte(self, address, value):
        self.record("byte", address, value)

    def write_byte_data(self, address, register, value):
        self.record("data", address, register, value)

    def close(self):
        self.closed = True


class RecordingDisplay:
    def __init__(self):
        self.frames = []
        self.closed = False

    def write_frame(self, line1, line2):
        self.frames.append((line1, line2))

    def close(self):
        self.closed = True
