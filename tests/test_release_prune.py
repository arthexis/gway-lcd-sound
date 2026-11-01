"""Owner-only pruning of immutable releases, no service or data mutation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/release_prune.py"
spec = importlib.util.spec_from_file_location("owner_prune_test", SCRIPT)
prune = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune)


class ReleasePruneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / ".local/share" / prune.OWNER
        self.releases = self.root / "releases"
        self.releases.mkdir(parents=True)
        n = 40 if prune.OWNER == "gway-rfid" else 12
        self.active, self.prev, self.old = ("a"*n, "b"*n, "c"*n)
        for name in (self.active, self.prev, self.old):
            (self.releases / name).mkdir()
            (self.releases / name / "marker").write_text("release")
        (self.root / "current").symlink_to(self.releases / self.active)
        if prune.HAS_PREVIOUS:
            (self.root / "previous").symlink_to(self.releases / self.prev)

    def test_read_only_and_apply_keep_active_and_rollback(self):
        data = self.root / "database.sqlite"
        data.write_text("persistent")
        with patch.object(prune.os, "geteuid", return_value=self.root.stat().st_uid):
            preview = prune.inventory(self.root)
            self.assertEqual(preview["status"], "candidates_ready")
            self.assertIn(self.old, [item["name"] for item in preview["candidates"]])
            self.assertTrue((self.releases / self.old).exists())
            result = prune.execute(self.root)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(set(result["deleted"]), {self.old} if prune.HAS_PREVIOUS else {self.old, self.prev})
        self.assertTrue((self.releases / self.active).exists())
        self.assertTrue((self.releases / self.prev).exists() if prune.HAS_PREVIOUS else True)
        self.assertEqual(data.read_text(), "persistent")

    def test_pointer_switch_prevents_deletion(self):
        with patch.object(prune.os, "geteuid", return_value=self.root.stat().st_uid):
            original = prune.inventory
            calls = 0
            def changed(root):
                nonlocal calls
                calls += 1
                if calls == 2:
                    (self.root / "current").unlink()
                    (self.root / "current").symlink_to(self.releases / self.old)
                return original(root)
            with patch.object(prune, "inventory", side_effect=changed):
                result = prune.execute(self.root)
        self.assertNotIn(self.old, result["deleted"])
        self.assertTrue((self.releases / self.old).exists())

    def test_symlink_release_and_unknown_names_block_apply(self):
        outside = self.home / "elsewhere"
        outside.mkdir()
        (self.releases / ("d" * len(self.old))).symlink_to(outside, target_is_directory=True)
        with patch.object(prune.os, "geteuid", return_value=self.root.stat().st_uid):
            report = prune.execute(self.root)
        self.assertEqual(report["deleted"], [])
        self.assertTrue(outside.exists())
        self.assertTrue((self.releases / self.old).exists())


if __name__ == "__main__":
    unittest.main()
