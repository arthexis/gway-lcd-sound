"""Shared per-user GPIO serialization, including the shell cleanup."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time


def _private_dir(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("unsafe sound lock directory")
    return path


class PlaybackBusy(RuntimeError):
    """A bounded lock acquisition did not complete."""


@contextmanager
def playback_lock(name="gpio-playback", timeout=10, shared=False):
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    if not runtime.is_dir():
        runtime = _private_dir(Path(tempfile.gettempdir()) / f"gway-sound-{os.getuid()}")
    directory = _private_dir(runtime / "gway-sound")
    fd = os.open(directory / (name + ".lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("unsafe sound lock file")
        end = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise PlaybackBusy("sound playback busy")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


@contextmanager
def alert_playback():
    # Shared intent lock is held while waiting for and playing the alert.
    # Multiple waiting alerts prevent music from barging between them.
    with playback_lock("gpio-alert-intent", shared=True):
        with playback_lock():
            yield


@contextmanager
def music_slice(muted, timeout=30):
    """Acquire GPIO only when no alert has announced intent.

    Release the intent gate before playing the bounded slice, so an alert
    can announce itself and acquire GPIO as soon as this slice ends.
    """
    from contextlib import ExitStack
    end = time.monotonic() + timeout
    with ExitStack() as gpio:
        while not muted():
            try:
                with playback_lock("gpio-alert-intent", timeout=0):
                    gpio.enter_context(playback_lock(timeout=0))
                break
            except PlaybackBusy:
                if time.monotonic() >= end:
                    raise PlaybackBusy("music interrupted by sustained alert traffic")
                time.sleep(0.025)
        else:
            yield False
            return
        yield not muted()


def play_interruptible(pattern, play_slice, muted, quantum=0.2):
    """Resume after alerts, discard the remainder when muted."""
    if not 0 < quantum <= 0.2:
        raise ValueError("GPIO music slice must be at most 200 ms")
    for frequency, duration, pause in pattern:
        for pitch, remaining in ((frequency, duration), (0, pause)):
            while remaining > 1e-9:
                span = min(remaining, quantum)
                with music_slice(muted) as acquired:
                    if not acquired:
                        return False
                    play_slice(pitch, span)
                remaining -= span
    return not muted()


if __name__ == "__main__":
    try:
        with playback_lock(timeout=0):
            subprocess.run(["pinctrl", "set", str(int(sys.argv[1])), "ip", "pd"],
                           check=False, timeout=3, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        pass
