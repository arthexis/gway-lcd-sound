from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/gway/lcd-actions-runner-status"
RUNNER = runpy.run_path(str(ROOT / "scripts/gway/lcd_lockfile_runner.py"))


def test_actions_pr_lock_overrides_normal_rotation(tmp_path: Path):
    env = {**os.environ, "GWAY_LCD_LOCK_DIR": str(tmp_path)}
    subprocess.run(["bash", str(SCRIPT), "start", "142", "ci/trusted-pr-ocpp-simulator-e2e"], env=env, check=True)
    lock = tmp_path / "lcd-actions-runner"
    assert lock.exists()
    payload = RUNNER["active_runner_payload"]([tmp_path], now=datetime.now(timezone.utc))
    assert payload is not None
    assert payload.line1 == "Run PR #142"
    assert payload.line2 == "ci/trusted-pr-ocpp-simulator-e2e"
    assert payload.expires_at is not None

    subprocess.run(["bash", str(SCRIPT), "stop"], env=env, check=True)
    assert RUNNER["active_runner_payload"]([tmp_path], now=datetime.now(timezone.utc)) is None


def test_bad_pr_never_publishes(tmp_path: Path):
    env = {**os.environ, "GWAY_LCD_LOCK_DIR": str(tmp_path)}
    result = subprocess.run(
        ["bash", str(SCRIPT), "start", "not-a-number", "branch"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / "lcd-actions-runner").exists()


def test_expired_lock_is_ignored(tmp_path: Path):
    (tmp_path / "lcd-actions-runner").write_text(
        "Run PR #42\nbranch\n2000-01-01T00:00:00Z\n", encoding="utf-8"
    )
    assert RUNNER["active_runner_payload"]([tmp_path], now=datetime.now(timezone.utc)) is None
    assert not (tmp_path / "lcd-actions-runner").exists()
