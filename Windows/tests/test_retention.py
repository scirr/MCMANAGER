"""
test_retention.py — Backup retention pruning (_prune_old_backups).

Daily backup folders (YYYY-MM-DD) older than the retention window must be
removed; recent folders, non-date folders and loose files must never be touched.
"""
import sys
import os
import datetime
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_core


def _day_folder(base, days_ago):
    name = (datetime.datetime.now() - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d")
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path


class PruneOldBackupsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_zero_retention_disables_pruning(self):
        old = _day_folder(self.base, 400)
        removed = mc_core._prune_old_backups(self.base, 0)
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.isdir(old))

    def test_negative_retention_disables_pruning(self):
        old = _day_folder(self.base, 400)
        removed = mc_core._prune_old_backups(self.base, -5)
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.isdir(old))

    def test_old_folder_removed_recent_kept(self):
        old = _day_folder(self.base, 40)
        recent = _day_folder(self.base, 2)
        removed = mc_core._prune_old_backups(self.base, 30)
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(recent))

    def test_non_date_folder_never_touched(self):
        keeper = os.path.join(self.base, "manual-save")
        os.makedirs(keeper)
        removed = mc_core._prune_old_backups(self.base, 1)
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.isdir(keeper))

    def test_loose_file_never_touched(self):
        loose = os.path.join(self.base, "2000-01-01")  # file, not a folder
        with open(loose, "w") as f:
            f.write("x")
        removed = mc_core._prune_old_backups(self.base, 1)
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.isfile(loose))

    def test_missing_backup_dir_is_noop(self):
        removed = mc_core._prune_old_backups(os.path.join(self.base, "nope"), 30)
        self.assertEqual(removed, 0)

    def test_folder_exactly_at_cutoff_is_kept(self):
        # A folder aged exactly `retention` days sits after the cutoff
        # instant (midnight vs. now) and must survive.
        boundary = _day_folder(self.base, 30)
        removed = mc_core._prune_old_backups(self.base, 30)
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.isdir(boundary))

    def test_multiple_old_folders_all_removed(self):
        for days in (35, 60, 365):
            _day_folder(self.base, days)
        recent = _day_folder(self.base, 1)
        removed = mc_core._prune_old_backups(self.base, 30)
        self.assertEqual(removed, 3)
        self.assertTrue(os.path.isdir(recent))


if __name__ == "__main__":
    unittest.main()
