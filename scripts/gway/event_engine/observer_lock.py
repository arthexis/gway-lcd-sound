"""Exclusive single-writer ownership of observer state and notification journal."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path


class ObserverAlreadyRunning(RuntimeError):
    pass


class ObserverLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.fd: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ObserverAlreadyRunning(f"Observer already owns {self.path}") from exc
            self.fd = fd
            return self
        except BaseException:
            os.close(fd)
            raise

    def __exit__(self, _type, _value, _traceback):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
