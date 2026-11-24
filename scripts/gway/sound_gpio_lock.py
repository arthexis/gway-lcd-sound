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


@contextmanager
def playback_lock(name="gpio-playback", timeout=10):
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
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise RuntimeError("sound playback busy")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        with playback_lock():
            subprocess.run(["pinctrl", "set", str(int(sys.argv[1])), "ip", "pd"],
                           check=False, timeout=3, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        pass
