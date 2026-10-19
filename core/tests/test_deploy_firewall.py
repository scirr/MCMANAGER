"""
test_deploy_firewall.py — the firewall step of 'mc deploy' goes through the
ufw/firewalld detection and says which firewall it used.
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_deploy
import mc_servers


class TestDeployFirewall(unittest.TestCase):

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.calls = []
        self.ufw_allow_code = 0
        import mc_platform
        import platform_linux
        saved = mc_platform._Lazy._impl
        mc_platform.use(platform_linux)
        self.addCleanup(mc_platform.use, saved)
        patches = [
            mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(self.data, "servers.json")),
            mock.patch.object(mc_servers, "REGISTRY_DIR", self.data),
            mock.patch.object(mc_servers, "DATA_ROOT", os.path.join(self.data, "Servers")),
            mock.patch("mc_core._port_in_use", return_value=False),
            mock.patch("mc_java.install", return_value={"ok": False, "code": "java_download_failed"}),
            mock.patch("builtins.input", side_effect=AssertionError("must not prompt")),
            mock.patch("platform_linux.firewall_name", return_value="ufw"),
            mock.patch("platform_linux._run", side_effect=self._fake_run),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _fake_run(self, args, root=False):
        self.calls.append(list(args))
        if args[:2] == ["ufw", "allow"]:
            return subprocess.CompletedProcess(args, self.ufw_allow_code, "", "denied")
        out = "Status: active\n" if args[:2] == ["ufw", "status"] else ""
        return subprocess.CompletedProcess(args, 0, out, "")

    def _deploy(self):
        def fake(folder, version):
            open(os.path.join(folder, "server.jar"), "w").close()
            return "server.jar"
        out = io.StringIO()
        with mock.patch.object(mc_deploy, "SERVER_TYPES", {"2": ("Paper", fake)}), \
             contextlib.redirect_stdout(out):
            res = mc_deploy.run_deploy_auto(name="Survie", version="1.21.1", accept_eula=True)
        return res, out.getvalue()

    def test_game_port_opened_through_ufw_with_comment(self):
        res, out = self._deploy()
        self.assertTrue(res["ok"], res)
        self.assertIn(["ufw", "allow", "25565/tcp", "comment", "MC Manager Survie"], self.calls)
        self.assertFalse(any("25575" in " ".join(c) for c in self.calls))
        self.assertIn("ufw", out)
        self.assertNotIn("firewalld", out)

    def test_failure_names_the_backend_and_gives_the_command(self):
        self.ufw_allow_code = 1
        res, out = self._deploy()
        self.assertTrue(res["ok"], res)
        self.assertIn("ufw", out)
        self.assertIn("sudo ufw allow 25565/tcp", out)
        self.assertNotIn("firewalld", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
