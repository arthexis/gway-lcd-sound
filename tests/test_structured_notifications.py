"""Hermetic structured LCD operational notifications; no I2C or audio."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/gway"))
from lcd_engine.notifications import (
    parse_notice, valid_notice, render, store_notice, read_notices,
    current_payload, node_code,
)

NOW = datetime(2026, 11, 24, 7, 0, tzinfo=timezone.utc)


def agent(**extra):
    return dict({
        "schema": "gway-notification/v1", "system": "agentops",
        "origin_node": "gway-001", "target_node": "gway-001",
        "subject": {"type": "github_issue", "repository": "arthexis/gway-agent-ops",
                    "number": 107},
        "state": "codex_failed", "severity": "error", "reason_code": "CODEX_FAILED",
        "episode_id": "example-invocation", "expires_in": 120,
    }, **extra)


def fleet(**extra):
    return dict({
        "schema": "gway-notification/v1", "system": "fleet",
        "origin_node": "gway-001", "target_node": "ocpp-abb-1",
        "subject": {"type": "service", "name": "ocpp-reports"},
        "state": "down", "severity": "critical", "reason_code": "NO_HEARTBEAT",
        "episode_id": "failure-1", "expires_in": 120,
    }, **extra)


def deployment(**extra):
    return dict({
        "schema": "gway-notification/v1", "system": "deploy",
        "origin_node": "gway-001", "target_node": "ocpp-abb-1",
        "subject": {"type": "repository", "repository": "arthexis/ocpp-reports"},
        "state": "deploy-failed", "severity": "error", "reason_code": "HEALTH_FAILED",
        "episode_id": "7ac2f1abcd", "expires_in": 120,
    }, **extra)


def test_identity_pages_and_full_repository_coverage():
    pages = render(agent())
    assert pages[:2] == [("AGT@001 FAILED", "gway-agent-ops"),
                         ("ISSUE #107", "CODEX FAILED")]
    full = "".join(text for label, text in pages[2:] if label.startswith("REPO"))
    assert full == "arthexis/gway-agent-ops"
    assert len(pages) <= 8
    assert all(len(line1) <= 16 and len(line2) <= 16 for line1, line2 in pages)
    assert render(fleet()) == [("FLT>ABB1 DOWN", "ocpp-reports"),
                               ("MONITOR: 001", "NO HEARTBEAT")]
    assert render(deployment())[:2] == [
        ("DEP>ABB1 FAILED", "ocpp-reports"), ("DEP 7ac2f1ab", "HEALTH FAILED")]
    assert node_code("gelectriic.com") == "WT"


def test_different_repository_owner_retains_visible_disambiguation():
    a = agent()
    b = agent(subject={"type": "github_issue", "repository": "elsewhere/gway-agent-ops",
                       "number": 107})
    assert render(a) != render(b)


@pytest.mark.parametrize("changes", [
    {"schema": "v2"}, {"system": "other"}, {"origin_node": "unknown"},
    {"target_node": "gway-001;rm -rf /"}, {"reason_code": "leak secret"},
    {"episode_id": "../escape"}, {"expires_in": 301}, {"expires_in": 3},
    {"severity": "info"}, {"subject": {"type": "github_issue",
                                       "repository": "arthexis/gway-agent-ops", "number": -1}},
    {"subject": {"type": "service", "name": "ocpp-reports"}},
])
def test_invalid_messages_are_rejected(changes):
    with pytest.raises(ValueError):
        valid_notice(agent(**changes))


def test_private_atomic_store_and_grouped_rotation(tmp_path):
    a, b = agent(), fleet()
    store_notice(tmp_path, a, now=NOW)
    store_notice(tmp_path, b, now=NOW)
    assert len(read_notices([tmp_path], now=NOW)) == 2
    count = len(render(b))
    seen = [current_payload([tmp_path], now=NOW, monotonic=i*5)
            for i in range(count)]
    assert [p.line1 for p in seen] == ["FLT>ABB1 DOWN", "MONITOR: 001"]
    # Critical fleet incident remains ahead of operational AgentOps failure.
    assert current_payload([tmp_path], now=NOW, monotonic=60).label == "notice-critical"
    assert all(not p.is_symlink() and (p.stat().st_mode & 0o077) == 0
               for p in tmp_path.glob("lcd-notice-*.json"))
    # Updating the same episode/state renews TTL, never creates another file.
    store_notice(tmp_path, b, now=NOW + timedelta(seconds=60))
    assert len(list(tmp_path.glob("lcd-notice-*.json"))) == 2


def test_notice_expires_without_touching_normal_channels(tmp_path):
    store_notice(tmp_path, fleet(), now=NOW)
    assert current_payload([tmp_path], now=NOW + timedelta(seconds=119)) is not None
    assert current_payload([tmp_path], now=NOW + timedelta(seconds=121)) is None
    assert not (tmp_path / "lcd-event-remote-overlay.lck").exists()


def test_symlink_file_blocked(tmp_path):
    n = agent()
    p = store_notice(tmp_path, n, now=NOW)
    p.unlink()
    target = tmp_path / "unrelated"
    target.write_text("unchanged")
    p.symlink_to(target)
    with pytest.raises(PermissionError):
        store_notice(tmp_path, n, now=NOW)
    assert target.read_text() == "unchanged"


def test_publisher_payload_roundtrip():
    assert parse_notice(json.dumps(agent())) == agent()
    with pytest.raises(ValueError):
        parse_notice(json.dumps(agent()) + " " * 4096)
