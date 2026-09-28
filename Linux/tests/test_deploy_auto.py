"""
test_deploy_auto.py — 'mc deploy --yes': refusals, defaults, registration,
nothing interactive.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_config
import mc_deploy
import mc_servers


class TestDeployAuto(unittest.TestCase):

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.patches = [
            mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(self.data, "servers.json")),
            mock.patch.object(mc_servers, "REGISTRY_DIR", self.data),
            mock.patch.object(mc_servers, "DATA_ROOT", os.path.join(self.data, "Servers")),
            mock.patch("mc_firewall.ensure_game_port_rule", return_value=(True, None)),
            mock.patch("builtins.input", side_effect=AssertionError("must not prompt")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _fake_deploy(self, folder, version):
        with open(os.path.join(folder, "server.jar"), "w") as f:
            f.write("jar")
        return "server.jar"

    def _run(self, **kw):
        types = {"2": ("Paper", self._fake_deploy)}
        with mock.patch.object(mc_deploy, "SERVER_TYPES", types):
            return mc_deploy.run_deploy_auto(**kw)

    def test_refusals(self):
        self.assertEqual(self._run(name="a")["code"], "eula_required")
        self.assertEqual(self._run(name="", accept_eula=True)["code"], "name_required")
        self.assertEqual(self._run(name="a", loader="Bukkit", accept_eula=True)["code"], "unknown_loader")
        self.assertEqual(self._run(name="a", ram="lots", accept_eula=True)["code"], "invalid_ram")

    def test_deploys_registers_and_provisions(self):
        res = self._run(name="Survie", version="1.21.1", accept_eula=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["server"], res["port"], res["rcon_port"]), ("survie", 25565, 25575))
        folder = res["path"]
        config = mc_config.load_config(folder)
        self.assertEqual(len(config["mcrcon_pass"]), 32)
        self.assertEqual(config["jar_name"], "server.jar")
        with open(os.path.join(folder, "eula.txt")) as f:
            self.assertIn("eula=true", f.read())
        with open(os.path.join(folder, "server.properties")) as f:
            props = f.read()
        self.assertIn("server-port=25565", props)
        self.assertIn("rcon.port=25575", props)
        self.assertEqual(mc_servers.list_servers()["survie"]["port"], 25565)

    def test_second_server_gets_free_ports(self):
        self._run(name="One", version="1.21.1", accept_eula=True)
        res = self._run(name="Two", version="1.21.1", accept_eula=True)
        self.assertEqual((res["port"], res["rcon_port"]), (25566, 25576))
        self.assertEqual(self._run(name="Three", version="1.21.1", port=25565, accept_eula=True)["code"], "port_taken")

    def test_failed_download_leaves_no_folder(self):
        with mock.patch.object(mc_deploy, "SERVER_TYPES", {"2": ("Paper", lambda f, v: None)}):
            res = mc_deploy.run_deploy_auto(name="x", version="1.21.1", accept_eula=True)
        self.assertEqual(res["code"], "download_failed")
        self.assertFalse(os.path.exists(os.path.join(self.data, "Servers", "x", "Server")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
