"""Hermetic HTTPS source-route sender tests. No network or hardware."""
from pathlib import Path
import json
import os
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from scripts.gway import server_source_route as source


@pytest.fixture
def config(tmp_path):
    root = tmp_path / "owned"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    token = root / "server-source.token"
    token.write_text("gwr_" + "ab" * 12 + "_" + "A" * 32)
    token.chmod(0o600)
    path = root / "server-source.json"
    path.write_text(json.dumps({"schema": 1, "origin": "ocpp-abb-1",
                                "url": source.URL, "token_file": str(token)}))
    path.chmod(0o600)
    return path, token


def event():
    return {"schema": 1, "origin": "ocpp-abb-1", "node": "gway-001",
            "request_id": "11" * 16, "expires_at": "2026-12-01T00:00:00+00:00",
            "device": "sound", "action": "status", "arguments": {}, "hops": 0}


def test_private_config_loads_but_no_token_exposure(config):
    path, token = config
    loaded = source.load(path)
    assert loaded["origin"] == "ocpp-abb-1"
    assert loaded["token"] == token.read_text()
    assert loaded["url"] == source.URL


def test_missing_config_keeps_legacy_transport(tmp_path):
    assert source.load(tmp_path / "nonexistent.json") is None


@pytest.mark.parametrize("bad", ["world", "symlink", "tokenworld", "wronghost"])
def test_untrusted_source_configuration_refused(config, bad):
    path, token = config
    if bad == "world":
        path.chmod(0o644)
    if bad == "symlink":
        target = path.with_suffix(".bak")
        path.rename(target)
        path.symlink_to(target)
    if bad == "tokenworld":
        token.chmod(0o644)
    if bad == "wronghost":
        data = json.loads(path.read_text())
        data["url"] = "https://attacker.invalid/steal"
        path.write_text(json.dumps(data))
    with pytest.raises((PermissionError, ValueError)):
        source.load(path)


class FakeResponse:
    def __init__(self, code=200, payload=None):
        self.status = code
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, limit):
        return json.dumps(self.payload).encode()


class FakeOpener:
    def __init__(self, code=200, status="succeeded"):
        self.calls = []
        self.code = code
        self.status = status
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        ev = json.loads(request.data)
        return FakeResponse(self.code, {"node": ev["node"], "source": ev["origin"],
                                         "request_id": ev["request_id"],
                                         "status": self.status})


def test_authenticated_request_is_bounded_and_correlated(config):
    loaded = source.load(config[0])
    opener = FakeOpener()
    answer = source.dispatch(event(), config=loaded, opener=opener)
    assert answer["status"] == "succeeded"
    req, timeout = opener.calls[0]
    assert timeout <= 8
    assert req.full_url == source.URL
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer " + loaded["token"]


@pytest.mark.parametrize("code,status", [(202, "uncertain"), (502, "failed")])
def test_ambiguous_or_failed_result_not_replayed(config, code, status):
    opener = FakeOpener(code, status)
    with pytest.raises(RuntimeError):
        source.dispatch(event(), config=source.load(config[0]), opener=opener)
    assert len(opener.calls) == 1


def test_claimed_source_not_equal_to_local_config_is_rejected(config):
    loaded = source.load(config[0])
    message = event()
    message["origin"] = "gelectriic.com"
    opener = FakeOpener()
    with pytest.raises(PermissionError):
        source.dispatch(message, config=loaded, opener=opener)
    assert not opener.calls
