from __future__ import annotations
import json

from scripts.gway.lcd_engine.system_info import formatting, publishing, collectors
from scripts.gway.lcd_engine.system_info.model import Snapshot


def sample(**overrides):
    values = dict(hostname="gway-001", role="control", iface="eth0", ip_addr="10.0.0.3",
                  reachable=True, load1=0.32, ram_pct=38, root_pct="42%", root_free="11G",
                  home_pct="36%", home_free="28G", err_count=0, warn_count=0,
                  last_log="none", addrs=["27"], camera_count=0,
                  throttle="thr ok", wifi_line1="WIFI none",
                  wifi_line2="no wlan ifaces", uptime=3600, cpu_temp="54C", rtc_temp="31C",
                  usb_count=2, rfid="rf-none", cpu_freq="1200MHz",
                  deployment_lines=None)
    values.update(overrides)
    return Snapshot(**values)


def test_normal_frames_preserve_order_and_format():
    frames = formatting.build_frames(sample())
    assert [f.key for f in frames] == ["host", "net", "wifi", "health", "disk"]
    assert frames[0].line1 == "HOST gway-001"
    assert frames[1].line1 == "NET eth0 ok"
    assert frames[3].line1 == "SOC54C RTC31C"
    assert frames[3].line2 == "L0.32 FRAM62%"
    assert all(len(f.line1) <= 16 and len(f.line2) <= 16 for f in frames)


def test_health_free_ram_and_width():
    for used, expected in [(30, "L4.08 FRAM70%"), (0, "L4.08 FRAM100%"),
                           (100, "L4.08 FRAM0%")]:
        frame = formatting.build_frames(sample(load1=4.08, ram_pct=used))[3]
        assert frame.line2 == expected
    assert formatting.build_frames(sample(load1=12345.67, ram_pct=0))[3].line2 == "L12346 FRAM100%"
    assert formatting.build_frames(sample(load1=123456789.0, ram_pct=0))[3].line2 == "FRAM100%"


def test_conditional_frames_preserve_existing_order():
    frames = formatting.build_frames(sample(throttle="thr 0x1",
                                            deployment_lines=("DEP A1 S1 U0 ?0", "H1 B0 N1 ?0"), err_count=3, warn_count=4))
    assert [f.key for f in frames] == [
        "host", "net", "wifi", "health", "disk", "power", "deployments", "logs"
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
    frames = formatting.build_frames(sample(ram_pct=None, cpu_temp="?C", rtc_temp="?C", iface="none",
                                            ip_addr="", reachable=False))
    assert frames[1].line2 == "no primary ip"
    assert frames[3].line1 == "SOC?C RTC?C"
    assert frames[3].line2 == "L0.32 FRAM?%"


def test_rtc_temperature_uses_only_valid_ds3231(tmp_path):
    hwmon = tmp_path / "hwmon3"
    hwmon.mkdir()
    (hwmon / "name").write_text("ds3231\n")
    (hwmon / "temp1_input").write_text("31250\n")
    assert collectors.rtc_temp_c(tmp_path) == "31C"
    (hwmon / "temp1_input").write_text("invalid")
    assert collectors.rtc_temp_c(tmp_path) == "?C"
    (hwmon / "temp1_input").write_text("126000")
    assert collectors.rtc_temp_c(tmp_path) == "?C"
    (hwmon / "name").write_text("other")
    (hwmon / "temp1_input").write_text("31250")
    assert collectors.rtc_temp_c(tmp_path) == "?C"


def test_command_runner_timeout_is_nonfatal(monkeypatch):
    import subprocess
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 0.01)
    monkeypatch.setattr(collectors.subprocess, "run", timed_out)
    assert collectors.run(["fake", "cmd"], timeout=0.01) == ""


def test_deployment_summary_distinguishes_evidence_and_runtime(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(collectors.shutil, "which", lambda _: "/usr/bin/gway-remote")
    data = {"schema": "gway-remote/status/v1", "components": [
        {"deployment_evidence": {"schema_version": 1, "installation_state": "activated", "runtime_state": "unhealthy"}},
        {"deployment_evidence": {"schema_version": 1, "installation_state": "staged", "runtime_state": "not_applicable"}},
        {"deployment_evidence": {"schema_version": 1, "installation_state": "unknown", "runtime_state": "healthy"}},
        {"deployment_evidence": {"schema_version": 1, "installation_state": "unavailable", "runtime_state": "unknown"}},
    ]}
    monkeypatch.setattr(collectors.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(data)))
    assert collectors.deployment_summary() == ("DEP A1 S1 U1 ?1", "H1 B1 N1 ?1")


def test_deployment_summary_absent_or_failed(monkeypatch):
    import subprocess
    monkeypatch.setattr(collectors.shutil, "which", lambda _: None)
    assert collectors.deployment_summary() is None
    monkeypatch.setattr(collectors.shutil, "which", lambda _: "/usr/bin/gway-remote")
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 20)
    monkeypatch.setattr(collectors.subprocess, "run", timed_out)
    assert collectors.deployment_summary() == ("DEP unavailable", "status unknown")


def test_wifi_summary_shows_connected_ssid_below_ap_status(monkeypatch):
    monkeypatch.setattr(collectors, "wlan_interfaces", lambda: ["wlan0", "wlan1"])

    def run(argv, timeout):
        if argv == ["iw", "dev", "wlan0", "info"]:
            return "type AP\n"
        if argv == ["iw", "dev", "wlan0", "station", "dump"]:
            return "Station aa:bb:cc:dd:ee:ff\n"
        if argv == ["iw", "dev", "wlan1", "info"]:
            return "type managed\n"
        if argv == ["iw", "dev", "wlan1", "link"]:
            return "SSID: IZZI-158E\nsignal: -47 dBm\n"
        raise AssertionError(argv)

    monkeypatch.setattr(collectors, "run", run)

    assert collectors.wifi_summary() == ("WIFI wlan0 AP1", "IZZI-158E")


def test_wifi_summary_shows_ap_ssid_when_no_client_connection(monkeypatch):
    monkeypatch.setattr(collectors, "wlan_interfaces", lambda: ["wlan0"])
    monkeypatch.setattr(collectors, "run", lambda argv, timeout: {
        ("iw", "dev", "wlan0", "info"): "type AP\nssid arthexis-1\n",
        ("iw", "dev", "wlan0", "station", "dump"): "",
    }[tuple(argv)])
    assert collectors.wifi_summary() == ("WIFI wlan0 AP0", "arthexis-1")


def test_wifi_summary_handles_missing_ap_ssid(monkeypatch):
    monkeypatch.setattr(collectors, "wlan_interfaces", lambda: ["wlan0"])
    monkeypatch.setattr(collectors, "run", lambda argv, timeout: "type AP\n" if argv[-1] == "info" else "")
    assert collectors.wifi_summary() == ("WIFI wlan0 AP0", "SSID unavailable")
