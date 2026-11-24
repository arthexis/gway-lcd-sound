"""Hardware-free music parser and CLI contract tests."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1] / "scripts" / "gway"
sys.path.insert(0, str(ROOT))
from sound_music import load_music, parse_midi, parse_rtttl  # noqa: E402
from sound_gpio_lock import (playback_lock, alert_playback, play_interruptible, music_slice)  # noqa: E402
import route_send  # noqa: E402


def smf(*tracks, division=96, fmt=None):
    if fmt is None:
        fmt = int(len(tracks) > 1)
    return (b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), division)
            + b"".join(b"MTrk" + struct.pack(">I", len(t)) + t for t in tracks))


END = b"\x00\xff\x2f\x00"
NOTE = b"\x00\x90\x45\x40\x60\x80\x45\x00" + END


def test_midi_note_and_speed():
    music = parse_midi(smf(NOTE))
    assert music.kind == "midi"
    assert music.pattern == ((440.0, .5, 0),)
    assert parse_midi(smf(NOTE), tempo=2).seconds == .25


def test_midi_tempo_running_status_and_rest():
    track = (b"\x00\xff\x51\x03\x0f\x42\x40"  # 1 second per beat
             b"\x30\x90\x45\x40\x30\x45\x00"  # rest then A4
             + END)
    assert parse_midi(smf(track)).pattern == ((0, .5, 0), (440.0, .5, 0))


def test_midi_polyphony_and_track_selection():
    higher = b"\x00\x90\x4c\x40\x60\x4c\x00" + END
    drum = b"\x00\x99\x7f\x40\x60\x7f\x00" + END
    data = smf(NOTE, higher, drum)
    assert parse_midi(data).pattern[0][0] == pytest.approx(659.255)
    assert parse_midi(data, track=0).pattern == ((440.0, .5, 0),)
    assert parse_midi(data, track=2).pattern == ((0, .5, 0),)


@pytest.mark.parametrize("data", [
    b"", smf(NOTE)[:-1], smf(NOTE, division=0x8001),
    smf(NOTE, fmt=2), smf(b"\xff\xff\xff\xff\x00"),
    smf(b"\x00\x45\x40" + END), smf(NOTE + b"x"),
    smf(b"\x00\x90\xff\x40" + END),
    smf(b"\x00\xff\x51\x03\x00\x00\x00" + END),
])
def test_bad_midi(data):
    with pytest.raises(ValueError):
        parse_midi(data)


def test_rtttl_defaults_dots_rests():
    music = parse_rtttl(b"Test:d=4,o=5,b=120:a,8c#6.,p")
    assert music.pattern[0][0] == 880
    assert music.pattern[1][1] == .375
    assert music.pattern[2] == (0, .5, 0)
    assert music.seconds == 1.375


@pytest.mark.parametrize("data", [
    b"bad", b"a:d=0:a", b"a:b=0:a", b"a:o=9:a", b"a:b=120,b=100:a",
    b"a::x", b"a::a..", b"a::p#", b"a::a,",
])
def test_bad_rtttl(data):
    with pytest.raises(ValueError):
        parse_rtttl(data)


def test_regular_file_and_bounds(tmp_path):
    bad = tmp_path / "bad.mid"
    bad.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="regular file"):
        load_music(bad)
    with pytest.raises(ValueError, match="duration"):
        parse_rtttl(b"x:d=1,o=5,b=25:" + b",".join([b"a"] * 100))
    with pytest.raises(ValueError, match="track"):
        parse_midi(smf(NOTE), track=1)
    with pytest.raises(ValueError, match="tempo"):
        parse_rtttl(b"x::a", tempo=float("nan"))


def cli(tmp_path, *args):
    env = dict(os.environ, XDG_RUNTIME_DIR=str(tmp_path),
               GWAY_LCD_SOUND_FORCE_LOCAL="1")
    return subprocess.run(["bash", str(ROOT / "gway-lcd-sound"), "sound", "play", *args],
                          env=env, capture_output=True, text=True, timeout=10)


def test_cli_dry_run_no_state(tmp_path):
    f = tmp_path / "theme.mid"
    f.write_bytes(smf(NOTE))
    result = cli(tmp_path, "--file", str(f), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"format": "midi", "backend": "gpio",
                                        "track": None, "tracks": 1, "seconds": .5, "steps": 1}
    assert not (tmp_path / "gway-sound").exists()


def test_cli_rtttl_and_conflicting_selection(tmp_path):
    f = tmp_path / "theme.rtttl"
    f.write_text("Theme:d=8,o=5,b=120:a,b,c6")
    result = cli(tmp_path, "--file", str(f), "--backend", "audio", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["seconds"] == .75
    assert cli(tmp_path, "--file", str(f), "--track", "0", "--dry-run").returncode != 0
    assert cli(tmp_path, "--file", str(f), "--repeat", "2", "--dry-run").returncode != 0
    assert cli(tmp_path, "--file", str(f), "--event", "foo", "--dry-run").returncode != 0


def test_long_gpio_preview(tmp_path):
    f = tmp_path / "long.rtttl"
    f.write_text("Theme:d=1,o=5,b=60:a,b")
    result = cli(tmp_path, "--file", str(f), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["seconds"] == 8
    assert cli(tmp_path, "--file", str(f), "--backend", "audio", "--dry-run").returncode == 0


def test_route_rejects_paths_without_transport():
    def forbidden(*args, **kwargs):
        pytest.fail("must not dispatch music paths")
    with pytest.raises(ValueError, match="local-only"):
        route_send.execute("sound", ["play", "--file", "/tmp/theme.mid"],
                           route={"sound": "gway-001"}, runner=forbidden)
    with pytest.raises(ValueError, match="local-only"):
        route_send.event_for("sound", ["play", "--file", "/tmp/theme.mid"],
                             "gway-001", origin="gway-004")


def test_shared_lock_exclusion(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with playback_lock():
        with pytest.raises(RuntimeError, match="busy"):
            with playback_lock(timeout=0):
                pytest.fail("lock unexpectedly acquired")
    with playback_lock(timeout=0):
        pass



def test_interruptible_long_note_and_mute(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    played = []
    def emit(pitch, duration):
        played.append((pitch, duration))
    assert play_interruptible([(440, 6.5, .1)], emit, lambda: False)
    assert sum(duration for _, duration in played) == pytest.approx(6.6)
    assert max(duration for _, duration in played) <= .2
    played.clear()
    assert not play_interruptible([(440, 8, 0)], emit, lambda: len(played) >= 2)
    assert len(played) == 2


def test_operational_alert_has_priority(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    intent = threading.Event()
    order = []
    def alert():
        # Announce before waiting on the hardware, as alert_playback does.
        with playback_lock("gpio-alert-intent", shared=True):
            intent.set()
            with playback_lock():
                order.append("alert")
    with music_slice(lambda: False) as acquired:
        assert acquired
        worker = threading.Thread(target=alert)
        worker.start()
        assert intent.wait(2)
        order.append("slice1")
    with music_slice(lambda: False) as acquired:
        assert acquired
        order.append("slice2")
    worker.join(2)
    assert not worker.is_alive()
    assert order == ["slice1", "alert", "slice2"]


def test_waiting_music_respects_mute(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    polls = []
    def muted():
        polls.append(True)
        return len(polls) > 1
    with alert_playback():
        with music_slice(muted) as acquired:
            assert not acquired


def test_music_releases_locks_on_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    def fail(*args):
        raise RuntimeError("hardware fault")
    with pytest.raises(RuntimeError, match="hardware fault"):
        play_interruptible([(440, 1, 0)], fail, lambda: False)
    with alert_playback():
        pass
