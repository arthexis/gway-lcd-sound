"""Public CLI receipt correlation: opt-in, hermetic, secret-free."""
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/gway"))
import route_send
import server_source_route


def routed():
    return {"schema": 1, "sound": "gway-001", "lcd": "gway-001"}


def test_opt_in_receipts_opaque_and_correlatable(monkeypatch, capsys):
    secret = "gwr_deadbeef_TokenSecretMustNeverPrint"
    monkeypatch.setenv("GWAY_LCD_SOUND_AUDIT_RECEIPTS", "1")
    monkeypatch.setattr(server_source_route, "load", lambda: {
        "url": server_source_route.URL, "origin": "ocpp-abb-1",
        "token": secret})
    def dispatch(event, *, config):
        assert config["token"] == secret
        return {"status": "succeeded", "node": event["node"],
                "source": event["origin"], "request_id": event["request_id"],
                "receiver_request_id": "2" * 32, "source_event_sha256": "b" * 64,
                "duplicate": False, "unsafe_extra": secret}
    monkeypatch.setattr(server_source_route, "dispatch", dispatch)
    assert route_send.execute("sound", ["play", "notice"], route=routed(),
                              runner=lambda *_a, **_k: pytest.fail("local fallback")) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert secret not in captured.err
    assert captured.err.count("gway-lcd-sound-receipt ") == 2
    first, last = [json.loads(s.split("gway-lcd-sound-receipt ", 1)[1])
                   for s in captured.err.strip().splitlines()]
    assert first["phase"] == "submitted"
    assert last["phase"] == "confirmed"
    assert first["request_id"] == last["request_id"]
    assert last["receiver_request_id"] == "2" * 32
    assert last["source_event_sha256"] == "b" * 64
    assert last["source"] == "ocpp-abb-1"
    assert last["status"] == "succeeded"


def test_audit_unchanged_by_default(monkeypatch, capsys):
    monkeypatch.delenv("GWAY_LCD_SOUND_AUDIT_RECEIPTS", raising=False)
    monkeypatch.setattr(server_source_route, "load",
                        lambda: {"origin": "gelectriic.com", "url": server_source_route.URL, "token": "secret"})
    monkeypatch.setattr(server_source_route, "dispatch", lambda event, *, config: {
        "status": "succeeded", "node": event["node"],
        "request_id": event["request_id"], "source": event["origin"]})
    assert route_send.execute("lcd", ["clear"], route=routed()) == 0
    assert capsys.readouterr().err == ""


def test_uncertain_has_only_submitted_receipt_and_no_fallback(monkeypatch, capsys):
    monkeypatch.setenv("GWAY_LCD_SOUND_AUDIT_RECEIPTS", "1")
    monkeypatch.setattr(server_source_route, "load",
                        lambda: {"origin": "ocpp-abb-1", "url": server_source_route.URL, "token": "secret"})
    calls = []
    def dispatch(event, *, config):
        calls.append(event["request_id"])
        raise RuntimeError("outcome uncertain")
    monkeypatch.setattr(server_source_route, "dispatch", dispatch)
    with pytest.raises(RuntimeError):
        route_send.execute("sound", ["play", "notice"], route=routed(),
                           runner=lambda *_a, **_k: pytest.fail("no local fallback"))
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0].split("gway-lcd-sound-receipt ", 1)[1])
    assert entry["phase"] == "submitted"
    assert calls == [entry["request_id"]]
