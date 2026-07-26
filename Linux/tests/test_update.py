"""
test_update.py — Version comparison for the auto-updater.

is_newer must correctly order semantic versions (with or without a leading 'v')
so the "update available" notice never fires on an equal or older release.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_update


class ParseVersionTests(unittest.TestCase):
    def test_strips_v_prefix(self):
        self.assertEqual(mc_update.parse_version("v2.3.0"), (2, 3, 0))
        self.assertEqual(mc_update.parse_version("2.3.0"), (2, 3, 0))

    def test_two_component(self):
        self.assertEqual(mc_update.parse_version("2.3"), (2, 3))

    def test_non_numeric_degrades(self):
        self.assertEqual(mc_update.parse_version("2.3.0-beta"), (2, 3, 0))


class IsNewerTests(unittest.TestCase):
    def test_patch_bump_is_newer(self):
        self.assertTrue(mc_update.is_newer("2.3.1", "2.3.0"))

    def test_minor_bump_is_newer(self):
        self.assertTrue(mc_update.is_newer("2.4.0", "2.3.9"))

    def test_major_bump_is_newer(self):
        self.assertTrue(mc_update.is_newer("3.0.0", "2.9.9"))

    def test_equal_is_not_newer(self):
        self.assertFalse(mc_update.is_newer("2.3.0", "2.3.0"))
        self.assertFalse(mc_update.is_newer("v2.3.0", "2.3.0"))

    def test_older_is_not_newer(self):
        self.assertFalse(mc_update.is_newer("2.2.9", "2.3.0"))

    def test_double_digit_ordering(self):
        self.assertTrue(mc_update.is_newer("2.10.0", "2.9.0"))
        self.assertFalse(mc_update.is_newer("2.9.0", "2.10.0"))


if __name__ == "__main__":
    unittest.main()
