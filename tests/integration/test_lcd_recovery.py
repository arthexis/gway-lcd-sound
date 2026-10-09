"""Full scheduler-to-controller path and controlled I2C faults."""
from scripts.gway.lcd_engine.model import Payload
from scripts.gway.lcd_engine.scheduler import Scheduler
from scripts.gway.lcd_engine.rendering import scroll_segment
from scripts.gway.lcd_engine.hardware.aip31068 import AiP31068LCD
from tests.fixtures.clocks import Clock
from tests.fixtures.hardware import RecordingBus


def test_pr_frames_reach_i2c_and_return_to_rotation(monkeypatch):
    monkeypatch.setattr("scripts.gway.lcd_engine.hardware.aip31068.time.sleep", lambda _: None)
    bus = RecordingBus()
    lcd = AiP31068LCD(bus=bus)
    scheduler = Scheduler(rotation_seconds=10, event_seconds=3)
    clock = Clock()
    normal = Payload("HOST gway-001", "READY", "normal")
    event = Payload("Warning", "Temperature", "event")
    pr = Payload("Run PR #142", "ci/long-pr-branch-name", "actions-runner")

    for active_runner, alert in ((None, None), (pr, event), (pr, event), (None, None)):
        decision = scheduler.tick(now=clock.now(), monotonic=clock.monotonic(),
                                  runner=active_runner, event=alert, normal=normal)
        lcd.write_frame(scroll_segment(decision.payload.line1, decision.scroll_step),
                        scroll_segment(decision.payload.line2, decision.scroll_step))
        clock.advance(1)
    assert scheduler.source == "normal"
    assert sum(op[:3] == ("data", 0x3E, 0x40) for op in bus.operations) == 4 * 32
    assert ("data", 0x3E, 0x40, ord("R")) in bus.operations
    lcd.close()
    assert bus.closed


def test_failed_bus_write_allows_reconnection(monkeypatch):
    monkeypatch.setattr("scripts.gway.lcd_engine.hardware.aip31068.time.sleep", lambda _: None)
    bad = RecordingBus()
    good = RecordingBus()
    device = AiP31068LCD(bus=bad)
    bad.fail_next = True
    try:
        device.write_frame("First", "Status")
    except OSError:
        device.close()
    else:
        raise AssertionError("fault should fail the current write")
    assert bad.closed
    replacement = AiP31068LCD(bus=good)
    replacement.write_frame("Recovered", "Online")
    assert any(op[:3] == ("data", 0x3E, 0x40) for op in good.operations)
    replacement.close()
    assert good.closed
