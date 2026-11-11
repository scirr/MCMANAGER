import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_core
import mc_java


class TestEnsureServerJava(unittest.TestCase):
    def test_server_from_2x_gets_the_java_its_version_needs(self):
        config = {"mc_version": "1.21.1"}
        ok = {"ok": True, "code": "java_installed"}

        def fake(cfg, ver):
            cfg["java_path"] = "C:\\java21\\bin\\java.exe"
            return ok

        with mock.patch.object(mc_java, "ensure_for_server", side_effect=fake) as ensure, \
                mock.patch.object(mc_core.mc_config, "save_config") as save:
            mc_core._ensure_server_java(config)
        ensure.assert_called_once_with(config, "1.21.1")
        save.assert_called_once_with(config)
        self.assertEqual(config["java_path"], "C:\\java21\\bin\\java.exe")

    def test_download_failure_keeps_the_system_java(self):
        config = {"mc_version": "1.21.1"}
        with mock.patch.object(mc_java, "ensure_for_server", return_value={"ok": False, "code": "offline"}), \
                mock.patch.object(mc_core.mc_config, "save_config") as save:
            mc_core._ensure_server_java(config)
        save.assert_not_called()
        self.assertNotIn("java_path", config)


if __name__ == "__main__":
    unittest.main()
