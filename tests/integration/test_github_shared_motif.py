"""GitHub motif identity and persistent database compatibility contracts."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOUND = ROOT / "scripts/gway/sound.sh"


def sound(db, *args):
    return subprocess.run(
        ["bash", str(SOUND), "--event-db", str(db), *args],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "XDG_RUNTIME_DIR": str(db.parent)},
    )


def test_github_sources_share_one_motif_without_merging_event_mappings(tmp_path):
    db = tmp_path / "events.sqlite3"
    first = sound(db, "--list-motifs")
    assert first.returncode == 0, first.stderr
    names = json.loads(first.stdout)
    assert "github" in names
    assert "github-actions" not in names

    actions = sound(db, "--event", "job-started", "--source", "github-actions", "--dry-run")
    assert actions.returncode == 0, actions.stderr
    assert json.loads(actions.stdout)["motif"] is True

    # An unregistered GitHub integration must not acquire an event mapping.
    other = sound(db, "--resolve", "--event", "job-started", "--source", "github-issues")
    assert other.returncode == 0, other.stderr
    assert json.loads(other.stdout)["sound"] is None


def test_existing_actions_motif_customization_migrates(tmp_path):
    db = tmp_path / "events.sqlite3"
    assert sound(db, "--list-motifs").returncode == 0
    notes = json.dumps([[440, 0.1, 0.0]])
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM motifs WHERE source='github'")
        conn.execute("INSERT INTO motifs(source,notes,cooldown_seconds) VALUES(?,?,?)",
                     ("github-actions", notes, 20))
    result = sound(db, "--list-motifs")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT notes,cooldown_seconds FROM motifs WHERE source='github'").fetchone() == (notes, 20)
        assert conn.execute("SELECT COUNT(*) FROM motifs WHERE source='github-actions'").fetchone()[0] == 0
    # Explicit legacy motif names still resolve to the new shared identity.
    legacy = sound(db, "notice", "--motif", "github-actions", "--dry-run")
    assert legacy.returncode == 0, legacy.stderr
