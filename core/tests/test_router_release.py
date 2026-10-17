"""
test_router_release.py — leaving the router gives a server its public port
back, a restart is announced, and the address shown to players is the one they
really connect to.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_api
import mc_config
import mc_core
import mc_router
import mc_servers


class RouterRelease(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patch = mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(self.tmp, "servers.json"))
        patch.start()
        self.addCleanup(patch.stop)
        servers = {}
        for i, (name, port) in enumerate((("a", 25570), ("b", 25571)), 1):
            folder = os.path.join(self.tmp, name)
            os.makedirs(folder)
            with open(os.path.join(folder, "config.json"), "w") as f:
                json.dump({"port": port, "rcon_port": port + 10, "mcrcon_pass": "x", "nom_serveur": name}, f)
            with open(os.path.join(folder, "server.properties"), "w") as f:
                f.write(f"server-port={port}\nserver-ip=\nmotd=hi\n")
            servers[name] = {"id": i, "dossier_serveur": folder, "port": port, "rcon_port": port + 10}
        mc_servers.save_registry({"active": "a", "servers": servers})
        self.folders = {n: i["dossier_serveur"] for n, i in servers.items()}

    def config(self, name):
        return mc_config.load_config(self.folders[name])

    def props(self, name):
        with open(os.path.join(self.folders[name], "server.properties")) as f:
            return dict(line.strip().split("=", 1) for line in f if "=" in line)

    def test_route_remove_restores_the_public_port(self):
        mc_api.router_command("route", ["add", "a.example.fr", "a"])
        self.assertEqual(self.props("a")["server-ip"], "127.0.0.1")
        self.assertEqual(self.props("a")["server-port"], "35570")
        res = mc_api.router_command("route", ["remove", "a.example.fr"])
        self.assertEqual(res["released"], ["a"])
        self.assertNotIn("router_backend", self.config("a"))
        self.assertNotIn("internal_port", self.config("a"))
        self.assertEqual((self.props("a")["server-port"], self.props("a")["server-ip"]), ("25570", ""))
        self.assertEqual(self.props("a")["motd"], "hi")
        self.assertTrue(any("25570" in note for note in res["notes"]))

    def test_a_server_still_routed_is_kept(self):
        mc_api.router_command("route", ["add", "a.example.fr", "a"])
        mc_api.router_command("route", ["add", "alias.example.fr", "a"])
        res = mc_api.router_command("route", ["remove", "alias.example.fr"])
        self.assertEqual(res["released"], [])
        self.assertTrue(self.config("a")["router_backend"])
        mc_api.router_command("default", ["b"])
        mc_api.router_command("route", ["remove", "a.example.fr"])
        self.assertTrue(self.config("b")["router_backend"])

    def test_disable_releases_everything_and_enable_attaches_again(self):
        mc_api.router_command("route", ["add", "a.example.fr", "a"])
        mc_api.router_command("default", ["b"])
        res = mc_api.router_command("disable")
        self.assertEqual(sorted(res["released"]), ["a", "b"])
        for name, port in (("a", "25570"), ("b", "25571")):
            self.assertNotIn("router_backend", self.config(name))
            self.assertEqual(self.props(name)["server-port"], port)
        res = mc_api.router_command("enable", port=25599)
        self.assertTrue(res["ok"], res)
        self.assertTrue(self.config("a")["router_backend"])
        self.assertTrue(self.config("b")["router_backend"])
        self.assertEqual(self.props("a")["server-ip"], "127.0.0.1")

    def test_hold_mode_server_keeps_its_internal_port(self):
        config = self.config("a")
        config.update(sleep_enabled=1, sleep_join_mode="hold", internal_port=35570, dossier_serveur=self.folders["a"])
        mc_config.save_config(config)
        mc_api.router_command("route", ["add", "a.example.fr", "a"])
        mc_api.router_command("route", ["remove", "a.example.fr"])
        after = self.config("a")
        self.assertNotIn("router_backend", after)
        self.assertEqual(after["internal_port"], 35570)
        self.assertEqual(self.props("a")["server-port"], "35570")
        self.assertEqual(self.props("a")["server-ip"], "127.0.0.1")

    def test_restart_is_announced_for_a_running_server(self):
        with mock.patch.object(mc_api, "restart_pending", return_value=True):
            added = mc_api.router_command("route", ["add", "a.example.fr", "a"])
            self.assertTrue(added["restart_required"])
            self.assertEqual(added["pending_restart"], ["a", "b"])
            removed = mc_api.router_command("route", ["remove", "a.example.fr"])
            self.assertTrue(removed["restart_required"])
            status = mc_api.router_command("status")
            self.assertEqual((status["restart_required"], status["pending_restart"]), (False, ["a", "b"]))
            self.assertEqual(mc_api.router_command("route", ["list"])["pending_restart"], ["a", "b"])
        with mock.patch.object(mc_api, "restart_pending", return_value=False):
            self.assertFalse(mc_api.router_command("default", ["a"])["restart_required"])

    def test_restart_pending_compares_start_time_with_the_properties_file(self):
        config = self.config("a")
        config["dossier_serveur"] = self.folders["a"]
        path = os.path.join(self.folders["a"], "server.properties")
        now = time.time()

        def pending(uptime, mtime, running=True):
            os.utime(path, (mtime, mtime))
            with mock.patch.object(mc_core, "is_server_running", return_value=running), \
                 mock.patch.object(mc_api, "_main_pid", return_value=1), \
                 mock.patch.object(mc_api, "_uptime_seconds", return_value=uptime):
                return mc_api.restart_pending(config)

        self.assertFalse(pending(3600, now - 7200))
        self.assertTrue(pending(3600, now - 60))
        self.assertFalse(pending(3600, now - 60, running=False))


class PublicPort(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patch = mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(self.tmp, "servers.json"))
        patch.start()
        self.addCleanup(patch.stop)

    def test_display_address_uses_the_port_players_connect_to(self):
        config = {"port": 25570, "domaine": "play.example.fr", "internal_port": 35570, "sleep_enabled": 1,
                  "sleep_join_mode": "hold"}
        self.assertEqual(mc_core._display_address(config), "play.example.fr:25570")
        routed = dict(config, router_backend=True, sleep_join_mode="kick", sleep_enabled=0)
        self.assertEqual(mc_core._display_address(routed), "play.example.fr:25570")
        mc_router.save(dict(mc_router.load(), enabled=True, port=25565))
        self.assertEqual(mc_core._display_address(routed), "play.example.fr")
        mc_router.save(dict(mc_router.load(), enabled=True, port=25599))
        self.assertEqual(mc_core._display_address(routed), "play.example.fr:25599")
        self.assertEqual(mc_core._display_address({"port": 25577}), "Port 25577 (Local/Public IP)")

    def test_proxy_bind_uses_the_port_the_process_listens_on(self):
        folder = os.path.join(self.tmp, "v")
        os.makedirs(folder)
        toml = os.path.join(folder, "velocity.toml")
        with open(toml, "w") as f:
            f.write('bind = "0.0.0.0:1"\n')
        config = {"dossier_serveur": folder, "loader": "Velocity", "port": 25577, "internal_port": 35577,
                  "router_backend": True}
        self.assertTrue(mc_core.sync_proxy_port(config))
        with open(toml) as f:
            self.assertIn("0.0.0.0:35577", f.read())


if __name__ == "__main__":
    unittest.main()
