import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_lang
import mc_update


class PackagedInstallTests(unittest.TestCase):
    def _marker(self, content):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "installed-by-package")
        if content is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        return mock.patch.object(mc_update, "PACKAGE_MARKER", path)

    def test_no_marker_means_zip_install(self):
        with self._marker(None):
            self.assertIsNone(mc_update.package_manager())

    def test_unknown_marker_is_ignored(self):
        with self._marker("pacman\n"):
            self.assertIsNone(mc_update.package_manager())

    def test_update_refused_before_any_network_access(self):
        with self._marker("apt\n"), mock.patch.object(mc_update, "_fetch_release") as fetch:
            res = mc_update.perform_update()
        fetch.assert_not_called()
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "managed_by_package")
        self.assertIn("apt", res["command"])

    def test_rollback_refused(self):
        with self._marker("dnf\n"):
            res = mc_update.rollback()
        self.assertEqual(res["code"], "managed_by_package")
        self.assertIn("dnf", res["command"])

    def test_message_exists_in_both_languages(self):
        for table in (mc_lang._FR, mc_lang._EN):
            text = table["upd_managed_by_package"].format(command="x")
            self.assertIn("x", text)


if __name__ == "__main__":
    unittest.main()
