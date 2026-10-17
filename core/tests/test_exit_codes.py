"""
test_exit_codes.py — any command that prints a "[!]" outcome without having
done what was asked must exit non-zero (F9). Runs the real CLI against a
throwaway data directory, one command per failure situation.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

FAILING = [
    ["datapack", "enable", "terra"],
    ["datapack", "disable", "nope"],
    ["datapack", "list", "zz"],
    ["datapack", "enable"],
    ["mod", "remove", "nope"],
    ["mod", "add", "/nonexistent/x.jar"],
    ["mod", "list", "zz"],
    ["rcon", "list"],
    ["console"],
    ["config", "set", "port", "abc"],
    ["config", "set", "nokey", "1"],
    ["config", "get", "nokey"],
    ["switch", "zz"],
    ["use", "zz"],
    ["start", "zz"],
    ["stop", "zz"],
    ["status", "zz"],
    ["doctor", "zz"],
    ["logs", "zz"],
    ["open", "zz"],
    ["backup", "zz"],
    ["resume", "zz"],
    ["mode", "always-on", "zz"],
    ["schedule", "25", "0", "3", "0"],
    ["schedule", "20", "0", "20", "0"],
    ["sleep", "wake"],
    ["router", "route", "add", "x"],
    ["router", "allow", "add", "nope"],
    ["router", "status", "--port", "5"],
    ["sleep", "enable", "--after", "1m"],
    ["sleep", "enable", "--after", "nonsense"],
    ["freeze", "--max", "nonsense"],
    ["image", "add", "/nonexistent/icon.png"],
    ["backup", "restore", "nope", "--yes"],
    ["backup", "restore", "latest"],
    ["backup", "remote", "test"],
    ["backup", "remote", "remove", "nope"],
    ["alert", "remove", "nope"],
    ["alert", "test"],
    ["alert", "add", "sms"],
    ["announce"],
    ["metrics", "serve", "--bind", "0.0.0.0:9225"],
    ["metrics", "serve", "--bind", "nonsense"],
    ["status-page", "enable", "zz"],
    ["status-page", "disable", "zz"],
    ["fingerprint"],
]


class TestFailuresExitNonZero(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp()
        cls.folder = tempfile.mkdtemp()
        with open(os.path.join(cls.folder, "config.json"), "w") as f:
            json.dump({"port": 1, "rcon_port": 2, "mcrcon_pass": "x", "always_on": 1,
                       "nom_serveur": "a"}, f)
        os.makedirs(os.path.join(cls.folder, "world", "datapacks"))
        with open(os.path.join(cls.data, "servers.json"), "w") as f:
            json.dump({"active": "a", "servers": {"a": {"id": 1, "dossier_serveur": cls.folder}}}, f)
        cls.env = dict(os.environ, MCMANAGER_DATA_DIR=cls.data, NO_COLOR="1")
        cls.env.pop("MCMANAGER_DEBUG", None)

    def _mc(self, *args):
        return subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), *args],
                              capture_output=True, text=True, env=self.env,
                              stdin=subprocess.DEVNULL, timeout=60)

    def test_failed_commands_do_not_exit_zero(self):
        wrong = []
        for args in FAILING:
            result = self._mc(*args)
            if result.returncode == 0:
                wrong.append((" ".join(args), (result.stdout + result.stderr).strip()[:120]))
        self.assertEqual(wrong, [], "these commands reported a failure but exited 0")

    def test_a_warning_line_never_comes_with_exit_zero(self):
        for args in FAILING + [["status"], ["players"], ["datapack", "list"], ["mod", "list"]]:
            result = self._mc(*args)
            if "[!]" in result.stdout + result.stderr:
                self.assertNotEqual(result.returncode, 0, f"mc {' '.join(args)} printed [!] and exited 0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
