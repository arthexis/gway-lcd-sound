from __future__ import annotations
import json

from scripts.gway.lcd_engine.system_info import formatting, publishing, collectors
from scripts.gway.lcd_engine.system_info.model import Snapshot


def sample(**overrides):
    values = dict(hostname="gway-001", role="control", iface="eth0", ip_addr="10.0.0.3",
                  reachable=True, load1=0.32, ram_pct=38, root_pct="42%", root_free="11G",
                  home_pct="36%", home_free="28G", err_count=0, warn_count=0,
                  last_log="none", addrs=["27"], camera_count=0, failed_count=0,
                  throttle="thr ok", services_ok=True, wifi_line1="WIFI none",
                  wifi_line2="no wlan ifaces", uptime=3600, cpu_temp="54C",
                  usb_count=2, rfid="rf-none", cpu_freq="1200MHz", process_count=50)
    values.update(overrides)
    return Snapshot(**values)


def test_normal_frames_preserve_order_and_format():
    frames = formatting.build_frames(sample())
    assert [f.key for f in frames] == ["host", "net", "wifi", "health", "disk", "devices"]
    assert frames[0].line1 == "HOST gway-001"
    assert frames[1].line1 == "NET eth0 ok"
    assert all(len(f.line1) <= 16 and len(f.line2) <= 16 for f in frames)


def test_conditional_frames_preserve_existing_order():
    frames = formatting.build_frames(sample(throttle="thr 0x1", failed_count=2,
                                            err_count=3, warn_count=4))
    assert [f.key for f in frames] == [
        "host", "net", "wifi", "health", "disk", "power", "services", "devices", "logs"
    ]


def test_publishing_preserves_lockfile_protocol(tmp_path):
    frames = formatting.build_frames(sample())
    result = publishing.publish(tmp_path, frames=frames)
    assert result == frames
    assert (tmp_path / "lcd-channels.lck").read_text() == "script\n"
    script = (tmp_path / "lcd-rotation.script").read_text()
    assert 'frame "HOST gway-001" "control up 1h0m"' in script
    data = json.loads((tmp_path / "lcd-system-info.json").read_text())
    assert data["frame_count"] == len(frames)


def test_dry_run_never_creates_lockfiles(tmp_path):
    frames = formatting.build_frames(sample())
    publishing.publish(tmp_path, frames=frames, dry_run=True)
    assert not list(tmp_path.iterdir())


def test_missing_metrics_remain_unknown():
    frames = formatting.build_frames(sample(ram_pct=None, cpu_temp="?C", iface="none",
                                            ip_addr="", reachable=False))
    assert frames[1].line2 == "no primary ip"
    assert frames[3].line1 == "HEALTH ?C"
    assert "RAM?%" in frames[3].line2


def test_command_runner_timeout_is_nonfatal(monkeypatch):
    import subprocess
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 0.01)
    monkeypatch.setattr(collectors.subprocess, "run", timed_out)
    assert collectors.run(["fake", "cmd"], timeout=0.01) == ""
