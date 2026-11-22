"""Hermetic route control-plane tests; never contact a real node."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest

MODULE = Path(__file__).resolve().parents[1] / "scripts/gway/route_config.py"
spec = importlib.util.spec_from_file_location("gway_route_config", MODULE)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


@pytest.fixture
def config(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    directory = root / "routes"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory / "routes.json"


def approve(node):
    assert node == "gway-001"


def test_initial_local_and_idempotent_set(config):
    assert route.read(config)["lcd"] is None
    first = route.set_route("gway-001", path=config, enrollment=approve)
    assert first["changed"] is True
    before = config.stat().st_mtime_ns
    second = route.set_route("gway-001", path=config, enrollment=approve)
    assert second["changed"] is False
    assert before == config.stat().st_mtime_ns
    assert config.stat().st_mode & 0o777 == 0o600
    assert route.read(config)["sound"] == "gway-001"


def test_independent_routes(config):
    route.set_route("gway-001", lcd=False, path=config, enrollment=approve)
    assert route.read(config) == {"schema": 1, "lcd": None, "sound": "gway-001"}
    route.local(lcd=False, path=config)
    assert route.read(config)["sound"] is None
    route.set_route("gway-001", sound=False, path=config, enrollment=approve)
    assert route.read(config)["lcd"] == "gway-001"
    route.local(sound=False, path=config)
    assert route.read(config)["lcd"] is None


def test_invalid_node_cannot_replace_config(config):
    route.set_route("gway-001", path=config, enrollment=approve)
    existing = config.read_bytes()
    for node in ("gway-1", "attacker", "gway-001;id", "../gway-001"):
        with pytest.raises((route.RoutingError, AssertionError)):
            route.set_route(node, path=config)
        assert config.read_bytes() == existing


def test_unavailable_registry_fails_closed(config):
    with pytest.raises(route.RoutingError, match="inventory unavailable"):
        route.check_enrollment("gway-001")  # unless a trusted registry is installed
    assert not config.exists()


def test_symlinks_and_unsafe_mode_rejected(config):
    target = config.parent / "elsewhere"
    target.write_text("untouched")
    config.symlink_to(target)
    with pytest.raises(route.RoutingError):
        route.save({"schema": 1, "lcd": None, "sound": None}, config)
    assert target.read_text() == "untouched"
    config.unlink()
    config.write_text(json.dumps({"schema": 1, "lcd": None, "sound": None}))
    config.chmod(0o644)
    with pytest.raises(route.RoutingError):
        route.read(config)


def test_rejects_invalid_schema(config):
    for bad in ({}, {"schema": 2, "lcd": None, "sound": None},
                {"schema": 1, "lcd": "localhost", "sound": None}):
        with pytest.raises(route.RoutingError):
            route.save(bad, config)


def test_transport_test_fails_not_false_success(monkeypatch, config, capsys):
    monkeypatch.setenv("GWAY_LCD_SOUND_ROUTE_CONFIG", str(config))
    with pytest.raises(SystemExit) as err:
        route.main(["test"])
    assert err.value.code == 1
    assert "no remote routes configured" in capsys.readouterr().err
