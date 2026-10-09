"""End-to-end observer to rules to shadow output, without devices."""
import importlib.util
import json
from pathlib import Path

from event_engine.model import Event


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/gway/gway_app_observer.py"


def load_cli():
    spec = importlib.util.spec_from_file_location("gway_app_observer_shadow_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shadow_emits_observation_and_notification(monkeypatch, tmp_path, capsys):
    cli = load_cli()
    event = Event("codex-turn", "session-1", "completed", "2026-10-09T12:00:00Z")
    monkeypatch.setattr(cli, "poll_codex_sessions", lambda store, root, *, deliver: deliver(event))
    assert cli.main(["--once", "--shadow", "--no-processes", "--state", str(tmp_path / "state.json")]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(output) == 2
    assert output[0]["state"] == "completed"
    assert output[1]["mode"] == "shadow"
    assert output[1]["sound"] == "ok"
    assert output[1]["lcd_lines"] == ["Codex completed", "session-1"]
    assert not (tmp_path / "lcd-event.lck").exists()


def test_default_observer_does_not_emit_notification(monkeypatch, tmp_path, capsys):
    cli = load_cli()
    event = Event("codex-turn", "session-1", "completed", "2026-10-09T12:00:00Z")
    monkeypatch.setattr(cli, "poll_codex_sessions", lambda store, root, *, deliver: deliver(event))
    assert cli.main(["--once", "--no-processes", "--state", str(tmp_path / "state.json")]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(output) == 1
    assert output[0]["state"] == "completed"


def test_shadow_ignores_unmapped_events(monkeypatch, tmp_path, capsys):
    cli = load_cli()
    event = Event("codex", "123", "not-visible", "2026-10-09T12:00:00Z")
    monkeypatch.setattr(cli, "poll_codex_sessions", lambda store, root, *, deliver: deliver(event))
    assert cli.main(["--once", "--shadow", "--no-processes", "--state", str(tmp_path / "state.json")]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(output) == 1
