"""
test_shared_registry_windows.py — Portable server paths under Windows path rules.

Verifies that server folders living under the registry directory are stored as
relative, forward-slash paths (so the same servers.json resolves on Windows and
Linux from a shared disk) and that everything else stays absolute.
"""
import sys
import os
import ntpath
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_servers

# The module is exercised under Windows path rules whatever the host OS: the
# registry dir and the drives below are fixed, and mc_servers sees ntpath.
_CWD_DRIVE = "C:"
_MOCK_REG_DIR = _CWD_DRIVE + "\\MCData"
_NT_OS = types.SimpleNamespace(path=ntpath, sep="\\", pardir="..")


class WindowsRegistryPathTests(unittest.TestCase):
    def setUp(self):
        self._saved_dir = mc_servers.REGISTRY_DIR
        mc_servers.REGISTRY_DIR = _MOCK_REG_DIR
        patcher = mock.patch.object(mc_servers, "os", _NT_OS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        mc_servers.REGISTRY_DIR = self._saved_dir

    def test_under_registry_is_stored_relative(self):
        path = ntpath.join(_MOCK_REG_DIR, "Servers", "survie", "Server")
        stored = mc_servers.to_portable(path)
        self.assertEqual(stored, "Servers/survie/Server")

    def test_sibling_of_registry_stays_absolute(self):
        # A path alongside (not under) the registry dir → relpath starts with ".."
        sibling = _CWD_DRIVE + "\\OtherData\\Server"
        stored = mc_servers.to_portable(sibling)
        self.assertTrue(ntpath.isabs(stored))

    def test_cross_drive_stays_absolute(self):
        other_path = "D:\\OtherData\\Server"
        stored = mc_servers.to_portable(other_path)
        self.assertTrue(ntpath.isabs(stored))

    def test_relative_resolves_against_registry_dir(self):
        resolved = mc_servers.resolve_path("Servers/survie/Server")
        expected = ntpath.join(_MOCK_REG_DIR, "Servers", "survie", "Server")
        self.assertEqual(ntpath.normcase(resolved), ntpath.normcase(expected))

    def test_relative_resolves_per_mount(self):
        # Same stored string, different registry dir (different mount point).
        alt_reg = _CWD_DRIVE + "\\MCDataAlt"
        mc_servers.REGISTRY_DIR = alt_reg
        resolved = mc_servers.resolve_path("Servers/survie/Server")
        expected = ntpath.join(alt_reg, "Servers", "survie", "Server")
        self.assertEqual(ntpath.normcase(resolved), ntpath.normcase(expected))

    def test_backslashes_normalised(self):
        resolved_bs = mc_servers.resolve_path("Servers\\survie\\Server")
        resolved_fs = mc_servers.resolve_path("Servers/survie/Server")
        self.assertEqual(ntpath.normcase(resolved_bs), ntpath.normcase(resolved_fs))

    def test_posix_absolute_path_left_untouched(self):
        # A POSIX absolute path written by Linux for a server outside the shared
        # disk must be returned as-is so it shows up as "folder not found" on Windows.
        posix_path = "/home/cris/other/Server"
        self.assertEqual(mc_servers.resolve_path(posix_path), posix_path)

    def test_round_trip(self):
        original = ntpath.join(_MOCK_REG_DIR, "Servers", "survie", "Server")
        stored = mc_servers.to_portable(original)
        resolved = mc_servers.resolve_path(stored)
        self.assertEqual(ntpath.normcase(resolved), ntpath.normcase(original))

    def test_empty(self):
        self.assertEqual(mc_servers.to_portable(""), "")
        self.assertEqual(mc_servers.resolve_path(""), "")


if __name__ == "__main__":
    unittest.main()
