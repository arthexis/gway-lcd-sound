"""Exercise the real Bash sound hook without audio hardware."""
from __future__ import annotations


def test_sound_name_volume_and_event_log(audio_harness):
    invoke, state, playback = audio_harness
    result = invoke("actions-job-start", "busy")
    assert result.returncode == 0
    assert playback.read_text().splitlines() == ["busy --volume 0.21"]
    log = (state / "events.log").read_text()
    assert "event=actions-job-start" in log
    assert "playback=ok" in log


def test_explicit_mute_skips_playback(audio_harness):
    invoke, state, playback = audio_harness
    state.mkdir(parents=True)
    (state / "silent").touch()
    assert invoke("actions-job-start", "busy").returncode == 0
    assert not playback.exists()
    assert "skipped=silent" in (state / "events.log").read_text()


def test_disabled_env_skips_playback(audio_harness):
    invoke, state, playback = audio_harness
    assert invoke("actions-job-start", "busy", extra={"CODEX_SOUND_HOOKS_DISABLED": "1"}).returncode == 0
    assert not playback.exists()
    assert "skipped=env-disabled" in (state / "events.log").read_text()


def test_playback_errors_are_nonfatal(audio_harness):
    invoke, state, playback = audio_harness
    assert invoke("actions-job-finish", "error", extra={"FAKE_SOUND_EXIT": "7"}).returncode == 0
    assert "playback=failed rc=7" in (state / "events.log").read_text()


def test_missing_sound_executable_does_not_fail_job(audio_harness):
    invoke, state, playback = audio_harness
    result = invoke("actions-job-start", "busy", extra={"CODEX_SOUND_HOOK_SOUND_BIN": "/nonexistent/sound"})
    assert result.returncode == 0
    assert not playback.exists()


def test_sound_aliases_and_thermal_levels(sound_monitor):
    aliases = sound_monitor.SOUND_ALIASES
    assert aliases["repo-upgrade-start"] == "busy"
    assert aliases["repo-upgrade-failed"] == "error"
    assert aliases["undervoltage"] == "undervoltage"
    assert sound_monitor.thermal_level(69.9) == "normal"
    assert sound_monitor.thermal_level(70) == "warm"
    assert sound_monitor.thermal_level(75) == "hot"
    assert sound_monitor.thermal_level(80) == "critical"
    assert sound_monitor.thermal_level(None) == "unknown"
