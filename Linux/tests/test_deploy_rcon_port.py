"""
test_deploy_rcon_port.py — 'mc deploy' proposes the next free RCON port
instead of one a registered server already uses.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_deploy
import mc_servers


class TestRconDefault(unittest.TestCase):

    def setUp(self):
        data = tempfile.mkdtemp()
        for p in (mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(data, "servers.json")),
                  mock.patch.object(mc_servers, "REGISTRY_DIR", data),
                  mock.patch.object(mc_servers, "DATA_ROOT", os.path.join(data, "Servers")),
                  mock.patch("mc_core._port_in_use", return_value=False),
                  mock.patch.object(mc_deploy, "pr")):
            p.start()
            self.addCleanup(p.stop)
        self.data = data

    def _proposed(self, config, folder):
        proposed = []

        def fake_ask(prompt, default="", secret=False):
            return default

        def fake_ask_int(prompt, default, validate=None, error_key=""):
            proposed.append(default)
            return default

        with mock.patch.object(mc_deploy, "ask", side_effect=fake_ask), \
             mock.patch.object(mc_deploy, "ask_int", side_effect=fake_ask_int):
            mc_deploy.setup_rcon(folder, config)
        return proposed[0]

    def test_free_port_after_a_taken_one(self):
        mc_servers.register_server("One", os.path.join(self.data, "one"), port=25565, rcon_port=25575)
        self.assertEqual(self._proposed({"port": 25566}, os.path.join(self.data, "two")), 25576)

    def test_skips_the_game_port(self):
        self.assertEqual(self._proposed({"port": 25575}, os.path.join(self.data, "two")), 25576)

    def test_inherited_conflicting_port_is_replaced(self):
        mc_servers.register_server("One", os.path.join(self.data, "one"), port=25565, rcon_port=25576)
        self.assertEqual(self._proposed({"port": 25566, "rcon_port": 25576}, os.path.join(self.data, "two")), 25575)


if __name__ == "__main__":
    unittest.main(verbosity=2)
