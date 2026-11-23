"""Hermetic advanced public sound syntax and guarded forwarding (#687)."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/gway"))
import route_send

RID = "ab" * 16


@pytest.mark.parametrize(("command", "opts", "expected"), [
    (["play", "notice"], ["--volume", "0.35", "--repeat", "3", "--pause", "0.15"],
     {"volume": 0.35, "repeat": 3, "pause": 0.15}),
    (["play", "notice"], ["--backend", "audio", "--device", "default"],
     {"backend": "audio", "device": "default"}),
    (["play", "notice"], ["--pin", "18", "--motif", "codex", "--dry-run"],
     {"pin": 18, "motif": "codex", "dry_run": True}),
    (["play", "notice"], ["--within", "0.5"], {"within": 0.5}),
    (["event", "deploy-verified", "gway-remote"], ["--resolve"],
     {"resolve": True}),
    (["play", "--sequence", '{"format":"gway-piano-v1","notes":[[440,0.1,0]]}'],
     ["--volume", "0.4", "--dry-run"], {"volume": 0.4, "dry_run": True}),
])
def test_public_advanced_parity(command, opts, expected):
    e = route_send.event_for("sound", command + opts, "gway-001",
                             origin="ocpp-abb-1", request_id=RID)
    for key, value in expected.items():
        assert e["arguments"][key] == value


@pytest.mark.parametrize("args", [
    ["play", "notice", "--repeat", "21"],
    ["play", "notice", "--repeat", "2", "--repeat", "2"],
    ["play", "notice", "--volume", "nan"],
    ["play", "notice", "--volume", "inf"],
    ["play", "notice", "--backend", "sh"],
    ["play", "notice", "--backend", "gpio", "--device", "../../dev/gpiochip"],
    ["play", "notice", "--device", "default"],
    ["play", "notice", "--motif", "../etc/passwd"],
    ["play", "notice", "--event-db", "/tmp/fake"],
    ["play", "notice", "--pattern-json", "{}"],
    ["play", "--sequence", "{}", "--repeat", "2"],
    ["event", "deploy-verified", "gway-remote", "--motif", "custom"],
    ["play", "notice", "--resolve"],
    ["event", "deploy-verified", "gway-remote", "--resolve", "--dry-run"],
    ["play", "notice", "--dry-run", "--dry-run"],
])
def test_advanced_options_fail_closed_before_transport(args):
    with pytest.raises(ValueError):
        route_send.event_for("sound", args, "gway-001", origin="gelectriic.com")


def test_preview_receipt_and_text_roundtrip(monkeypatch, capsys):
    import server_source_route
    monkeypatch.setattr(server_source_route, "load", lambda: {
        "origin": "ocpp-abb-1", "url": server_source_route.URL, "token": "private"})
    sent = []
    def dispatch(event, *, config):
        sent.append(event)
        return {"node": event["node"], "request_id": event["request_id"],
                "status": "succeeded", "output": "notice: 784Hz preview\\n"}
    monkeypatch.setattr(server_source_route, "dispatch", dispatch)
    rc = route_send.execute("sound", ["play", "notice", "--dry-run"],
                            route={"lcd": None, "sound": "gway-001"},
                            runner=lambda *_a, **_kw: pytest.fail("no local hardware"))
    assert rc == 0
    assert capsys.readouterr().out == "notice: 784Hz preview\\n"
    assert sent[0]["arguments"]["dry_run"] is True


def test_local_advanced_argv_remains_unchanged(tmp_path):
    calls = []
    def runner(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0)
    assert route_send.execute("sound", ["play", "notice", "--volume", "0.45",
                          "--backend", "gpio"], runner=runner,
                          route={"lcd": None, "sound": None}, here=tmp_path) == 0
    assert calls == [["bash", str(tmp_path / "sound.sh"), "notice",
                      "--volume", "0.45", "--backend", "gpio"]]
