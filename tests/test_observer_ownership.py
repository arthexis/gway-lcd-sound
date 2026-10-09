"""6B: observer ownership requires an explicit, non-default cutover."""
import pytest

import gway_app_observer


def test_observer_mode_requires_all_ownership_inputs(tmp_path):
    with pytest.raises(SystemExit) as exc:
        gway_app_observer.main(["--notification-mode", "observer", "--once"])
    assert exc.value.code == 2


def test_shadow_conflicts_with_live_mode():
    with pytest.raises(SystemExit) as exc:
        gway_app_observer.main(["--shadow", "--notification-mode", "observer", "--once"])
    assert exc.value.code == 2


def test_bad_ownership_acknowledgement_rejected(tmp_path):
    token = tmp_path / "ownership"
    token.write_text("legacy-still-owns-notifications\n")
    sound = tmp_path / "sound"
    sound.write_text("#!/bin/sh\nexit 0\n")
    sound.chmod(0o700)
    with pytest.raises(SystemExit) as exc:
        gway_app_observer.main(["--notification-mode", "observer", "--once",
                                "--lcd-dir", str(tmp_path),
                                "--sound-command", str(sound),
                                "--ownership-file", str(token)])
    assert exc.value.code == 2


def test_live_sound_hook_receives_event_then_sound(monkeypatch, tmp_path):
    """Exercise the observer adapter without invoking real sound or LCD hardware."""
    from event_engine.model import Event

    token = tmp_path / "ownership"
    token.write_text("observer-owns-notifications\n")
    sound = tmp_path / "codex-sound-hook"
    sound.write_text("#!/bin/sh\nexit 0\n")
    sound.chmod(0o700)
    event = Event("codex-turn", "session", "completed", "2026-10-09T12:00:00Z",
                  event_id="codex-jsonl:session:100")
    monkeypatch.setattr(gway_app_observer, "poll_codex_sessions",
                        lambda store, root, *, deliver: deliver(event))
    calls = []
    monkeypatch.setattr(gway_app_observer.subprocess, "run",
                        lambda argv, **kwargs: calls.append((argv, kwargs)))
    assert gway_app_observer.main([
        "--notification-mode", "observer", "--once", "--no-processes",
        "--state", str(tmp_path / "state.json"),
        "--lcd-dir", str(tmp_path),
        "--sound-command", str(sound),
        "--ownership-file", str(token),
    ]) == 0
    assert calls == [([str(sound), "observer-notification", "ok"],
                      {"check": True, "timeout": 20})]
