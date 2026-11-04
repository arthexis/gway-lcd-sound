"""A new deployment stage must preempt the cached LCD event immediately."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile

from scripts.gway import lcd_lockfile_runner as runner


def test_atomic_event_replacement_preempts_unexpired_stage():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        path = folder / "lcd-event-deployment.lck"
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=30)).isoformat()
        path.write_text(f"gway-remote\nactivated\n{expires}\n")
        instance = runner.Runner(SimpleNamespace(lock_dir=[str(folder)]))
        first = instance.active_event(now)
        assert first is not None and first.lines[1] == "activated"
        # Same filename, different inode: the producer uses os.replace.
        replacement = folder / ".new-deployment"
        replacement.write_text(f"gway-remote\nverified\n{expires}\n")
        replacement.replace(path)
        second = instance.active_event(now + timedelta(seconds=1))
        assert second is not None and second.lines[1] == "verified"
        assert second is not first
        assert instance.event_file_signature(path) == instance.event_signature


def test_missing_cached_event_does_not_replay_old_message():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        path = folder / "lcd-event-deployment.lck"
        now = datetime.now(timezone.utc)
        path.write_text(f"gway-remote\nstarted\n{(now + timedelta(seconds=30)).isoformat()}\n")
        instance = runner.Runner(SimpleNamespace(lock_dir=[str(folder)]))
        assert instance.active_event(now) is not None
        path.unlink()
        assert instance.active_event(now + timedelta(seconds=1)) is None
