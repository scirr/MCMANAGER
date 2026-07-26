"""
test_shared_registry.py — Portable, cross-OS server paths (Windows).

Verifies that server folders living under the registry directory are stored as
relative, forward-slash paths (so the same servers.json resolves on Windows and
Linux from a shared disk) and that everything else stays absolute.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_servers

# Build a mock registry dir on the same drive as the current working directory
# so relative-path arithmetic works without needing a second physical drive.
_CWD_DRIVE = os.path.splitdrive(os.getcwd())[0] or "C:"
_MOCK_REG_DIR = _CWD_DRIVE + "\\MCData"


class SharedRegistryPathTests(unittest.TestCase):
    def setUp(self):
        self._saved_dir = mc_servers.REGISTRY_DIR
        mc_servers.REGISTRY_DIR = _MOCK_REG_DIR

    def tearDown(self):
        mc_servers.REGISTRY_DIR = self._saved_dir

    def test_under_registry_is_stored_relative(self):
        path = os.path.join(_MOCK_REG_DIR, "Servers", "survie", "Server")
        stored = mc_servers.to_portable(path)
        self.assertEqual(stored, "Servers/survie/Server")

    def test_sibling_of_registry_stays_absolute(self):
        # A path alongside (not under) the registry dir → relpath starts with ".."
        sibling = _CWD_DRIVE + "\\OtherData\\Server"
        stored = mc_servers.to_portable(sibling)
        self.assertTrue(os.path.isabs(stored))

    def test_cross_drive_stays_absolute(self):
        other_drives = [
            d + ":\\" for d in "DEFGHIJKLMNOPQRSTUVWXYZ"
            if (d + ":").upper() != _CWD_DRIVE.upper()
        ]
        if not other_drives:
            self.skipTest("No second drive available for cross-drive test")
        other_path = other_drives[0] + "OtherData\\Server"
        stored = mc_servers.to_portable(other_path)
        self.assertTrue(os.path.isabs(stored))

    def test_relative_resolves_against_registry_dir(self):
        resolved = mc_servers.resolve_path("Servers/survie/Server")
        expected = os.path.join(_MOCK_REG_DIR, "Servers", "survie", "Server")
        self.assertEqual(os.path.normcase(resolved), os.path.normcase(expected))

    def test_relative_resolves_per_mount(self):
        # Same stored string, different registry dir (different mount point).
        alt_reg = _CWD_DRIVE + "\\MCDataAlt"
        mc_servers.REGISTRY_DIR = alt_reg
        resolved = mc_servers.resolve_path("Servers/survie/Server")
        expected = os.path.join(alt_reg, "Servers", "survie", "Server")
        self.assertEqual(os.path.normcase(resolved), os.path.normcase(expected))

    def test_backslashes_normalised(self):
        resolved_bs = mc_servers.resolve_path("Servers\\survie\\Server")
        resolved_fs = mc_servers.resolve_path("Servers/survie/Server")
        self.assertEqual(os.path.normcase(resolved_bs), os.path.normcase(resolved_fs))

    def test_posix_absolute_path_left_untouched(self):
        # A POSIX absolute path written by Linux for a server outside the shared
        # disk must be returned as-is so it shows up as "folder not found" on Windows.
        posix_path = "/home/cris/other/Server"
        self.assertEqual(mc_servers.resolve_path(posix_path), posix_path)

    def test_round_trip(self):
        original = os.path.join(_MOCK_REG_DIR, "Servers", "survie", "Server")
        stored = mc_servers.to_portable(original)
        resolved = mc_servers.resolve_path(stored)
        self.assertEqual(os.path.normcase(resolved), os.path.normcase(original))

    def test_empty(self):
        self.assertEqual(mc_servers.to_portable(""), "")
        self.assertEqual(mc_servers.resolve_path(""), "")


if __name__ == "__main__":
    unittest.main()
