"""Regression: the public sound entry point must work through symlinks."""
from pathlib import Path
import subprocess


def test_sound_help_via_external_symlink(tmp_path):
    source = Path(__file__).resolve().parents[1] / "scripts/gway/sound.sh"
    public = tmp_path / "sound"
    public.symlink_to(source)
    result = subprocess.run([str(public), "--help"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "--motif" in result.stdout
