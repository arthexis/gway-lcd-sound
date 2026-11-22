"""Hermetic routed command dispatch; no real GWay Remote or hardware calls."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/gway"))
import route_send


def fake_route(node="gway-001", *, device="sound"):
    result = {"schema": 1, "lcd": None, "sound": None}
    result[device] = node
    return result


def test_local_sound_play_preserves_legacy_argv(tmp_path):
    seen = []
    def runner(argv, **kwargs):
        seen.append((argv, kwargs))
        return SimpleNamespace(returncode=0)
    assert route_send.execute("sound", ["play", "notice"], runner=runner,
                              route={"lcd": None, "sound": None}, here=tmp_path) == 0
    assert seen[0][0] == ["bash", str(tmp_path / "sound.sh"), "notice"]


def test_remote_sound_ack_correlated(monkeypatch):
    monkeypatch.setattr(route_send.socket, "gethostname", lambda: "watchtower")
    calls = []
    def runner(argv, **kw):
        calls.append((argv, kw))
        event = json.loads(kw["input"])
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "node": "gway-001", "request_id": event["request_id"],
            "status": "succeeded"}).encode())
    assert route_send.execute("sound", ["play", "notice"], route=fake_route(), runner=runner) == 0
    assert calls[0][0] == ["gway-remote", "--lcd-sound-bridge", "send"]
    assert json.loads(calls[0][1]["input"])["device"] == "sound"


def test_failed_remote_never_executes_local(monkeypatch):
    monkeypatch.setattr(route_send.socket, "gethostname", lambda: "watchtower")
    calls = []
    def runner(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=1, stdout=b"")
    with pytest.raises(RuntimeError):
        route_send.execute("sound", ["play", "critical"], route=fake_route(), runner=runner)
    assert calls == [["gway-remote", "--lcd-sound-bridge", "send"]]


def test_remote_identity_mismatch_denied(monkeypatch):
    monkeypatch.setattr(route_send.socket, "gethostname", lambda: "gway-001")
    with pytest.raises(ValueError):
        route_send.event_for("sound", ["play", "notice"], "gway-001")


def test_lcd_overlay_envelope(monkeypatch):
    monkeypatch.setattr(route_send.socket, "gethostname", lambda: "watchtower")
    event = route_send.event_for("lcd", ["show", "Deploy", "Ready", "--seconds", "20"],
                                 "gway-001", request_id="ab" * 16)
    assert event["action"] == "show"
    assert event["arguments"] == {"line1": "Deploy", "line2": "Ready", "seconds": 20}
    assert event["hops"] == 0


def test_sound_event_keeps_event_semantics():
    event = route_send.event_for("sound",
        ["event", "deploy-verified", "gway-remote", "--within", "30"],
        "gway-001", origin="watchtower")
    assert event["arguments"] == {"event": "deploy-verified", "source": "gway-remote", "within": 30}


def test_rejects_unsupported_commands():
    for device, args in [("lcd", ["monitor", "eth0"]), ("sound", ["piano"]), ("sound", ["play", "name", "--bogus"])]:
        with pytest.raises(ValueError):
            route_send.event_for(device, args, "gway-001", origin="watchtower")

def test_server_source_route_calls_authenticated_gateway_not_local(monkeypatch):
    import server_source_route
    config = {"origin": "ocpp-abb-1", "url": server_source_route.URL, "token": "sealed"}
    monkeypatch.setattr(server_source_route, "load", lambda: config)
    seen = []
    monkeypatch.setattr(server_source_route, "dispatch",
                        lambda e, *, config: seen.append((e, config)) or {
                            "node": e["node"], "request_id": e["request_id"],
                            "source": e["origin"], "status": "succeeded"})
    def runner(*_args, **_kwargs):
        raise AssertionError("neither local hardware nor legacy SSH should run")
    assert route_send.execute("sound", ["play", "notice"],
                              route=fake_route(), runner=runner) == 0
    assert len(seen) == 1
    assert seen[0][0]["origin"] == "ocpp-abb-1"


def test_server_source_failure_never_falls_back(monkeypatch):
    import server_source_route
    monkeypatch.setattr(server_source_route, "load",
                        lambda: {"origin": "gelectriic.com", "url": server_source_route.URL,
                                 "token": "sealed"})
    calls = []
    def fail(event, *, config):
        calls.append(event)
        raise RuntimeError("uncertain")
    monkeypatch.setattr(server_source_route, "dispatch", fail)
    with pytest.raises(RuntimeError):
        route_send.execute("sound", ["play", "notice"], route=fake_route(),
                           runner=lambda *a, **k: pytest.fail("local fallback"))
    assert len(calls) == 1
    assert calls[0]["origin"] == "gelectriic.com"
