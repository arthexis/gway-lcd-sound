"""Regression tests for the factory source-motif rhythm migration."""
import json
import os
import pathlib
import sqlite3
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOUND = ROOT / "scripts/gway/sound.sh"


def invoke(db, *args):
    env = os.environ.copy()
    env["GWAY_SOUND_EVENT_DB"] = str(db)
    return subprocess.run(["bash", str(SOUND), "--event", "connected",
                           "--source", "wifi", "--dry-run", *args],
                          env=env, text=True, capture_output=True, check=True)


def test_factory_rhythms_and_wifi_handshake(tmp_path):
    db = tmp_path / "events.sqlite3"
    invoke(db)
    with sqlite3.connect(db) as conn:
        rows = dict(conn.execute("SELECT source, notes FROM motifs"))
    assert set(("codex", "wifi", "ssh", "github", "gway-monitor", "gway-remote")) <= rows.keys()
    wifi = json.loads(rows["wifi"])
    assert len(wifi) == 5
    assert len({note[0] for note in wifi}) >= 4
    assert sum(note[1] + note[2] for note in wifi) < 0.8
    for notes_json in rows.values():
        notes = json.loads(notes_json)
        assert all(80 <= hz <= 4000 and 0.01 <= duration <= 0.4
                   and 0 <= pause <= 0.4 for hz, duration, pause in notes)


def test_migration_preserves_custom_and_is_idempotent(tmp_path):
    db = tmp_path / "events.sqlite3"
    invoke(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE motifs SET notes=? WHERE source='codex'",
                     (json.dumps([[700, 0.2, 0.0]]),))
        conn.execute("UPDATE motifs SET notes=? WHERE source='wifi'",
                     (json.dumps([[523, 0.06, 0.035], [784, 0.06, 0.0]]),))
        conn.commit()
    invoke(db)
    with sqlite3.connect(db) as conn:
        assert json.loads(conn.execute("SELECT notes FROM motifs WHERE source='codex'").fetchone()[0]) == [[700, 0.2, 0.0]]
        upgraded = json.loads(conn.execute("SELECT notes FROM motifs WHERE source='wifi'").fetchone()[0])
        assert len(upgraded) == 5
    invoke(db)
    with sqlite3.connect(db) as conn:
        assert json.loads(conn.execute("SELECT notes FROM motifs WHERE source='wifi'").fetchone()[0]) == upgraded
