"""
test_shared_registry.py — Portable, cross-OS server paths.

Verifies that server folders living under the registry directory are stored as
relative, forward-slash paths (so the same servers.json resolves on Windows and
Linux from a shared disk) and that everything else stays absolute.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_servers


class SharedRegistryPathTests(unittest.TestCase):
    def setUp(self):
        # Pretend the registry lives on a shared disk mounted here.
        self._saved_dir = mc_servers.REGISTRY_DIR
        mc_servers.REGISTRY_DIR = "/mnt/shared/MCData"

    def tearDown(self):
        mc_servers.REGISTRY_DIR = self._saved_dir

    def test_under_registry_is_stored_relative(self):
        stored = mc_servers.to_portable("/mnt/shared/MCData/Servers/survie/Server")
        self.assertEqual(stored, "Servers/survie/Server")

    def test_outside_registry_stays_absolute(self):
        stored = mc_servers.to_portable("/home/cris/other/Server")
        self.assertEqual(stored, "/home/cris/other/Server")
        self.assertTrue(os.path.isabs(stored))

    def test_relative_resolves_against_registry_dir(self):
        resolved = mc_servers.resolve_path("Servers/survie/Server")
        self.assertEqual(resolved, "/mnt/shared/MCData/Servers/survie/Server")

    def test_relative_resolves_per_mount(self):
        # Same stored string, different registry dir (different OS mount).
        mc_servers.REGISTRY_DIR = "/run/media/cris/DISK/MCData"
        resolved = mc_servers.resolve_path("Servers/survie/Server")
        self.assertEqual(resolved, "/run/media/cris/DISK/MCData/Servers/survie/Server")

    def test_windows_backslashes_are_normalised(self):
        resolved = mc_servers.resolve_path("Servers\\survie\\Server")
        self.assertEqual(resolved, "/mnt/shared/MCData/Servers/survie/Server")

    def test_windows_absolute_path_left_untouched(self):
        # A drive-letter path only means something on Windows; on Linux it must
        # not be joined against the registry dir.
        self.assertEqual(mc_servers.resolve_path("X:\\MCData\\Servers\\s"),
                         "X:\\MCData\\Servers\\s")

    def test_round_trip(self):
        original = "/mnt/shared/MCData/Servers/survie/Server"
        self.assertEqual(mc_servers.resolve_path(mc_servers.to_portable(original)),
                         original)

    def test_empty(self):
        self.assertEqual(mc_servers.to_portable(""), "")
        self.assertEqual(mc_servers.resolve_path(""), "")


class NextFreeIdTests(unittest.TestCase):
    """Server numbers fill removed gaps and restart at 1, never grow forever."""

    def _servers(self, *ids):
        return {f"s{i}": {"id": i} for i in ids}

    def test_empty_starts_at_one(self):
        self.assertEqual(mc_servers._next_free_id({}), 1)

    def test_sequential(self):
        self.assertEqual(mc_servers._next_free_id(self._servers(1)), 2)
        self.assertEqual(mc_servers._next_free_id(self._servers(1, 2)), 3)

    def test_fills_gap(self):
        self.assertEqual(mc_servers._next_free_id(self._servers(1, 3)), 2)
        self.assertEqual(mc_servers._next_free_id(self._servers(2, 3)), 1)

    def test_reuses_after_removal(self):
        # remove the only server -> next one is 1 again, not an ever-growing number
        self.assertEqual(mc_servers._next_free_id(self._servers()), 1)


if __name__ == "__main__":
    unittest.main()
