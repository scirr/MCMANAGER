"""
test_router.py — hostname routing end to end on 127.0.0.1 with fake servers,
plus the router configuration file and the `mc router` API.
"""
import json
import os
import socket
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import mc_api
import mc_protocol
import mc_router
import mc_servers
import mc_sleep
from fakeserver import FakeServer
from mc_lang import T
from test_sleep_hold import handshake, login, read_packet


def target_for(fake, **policy):
    return mc_router.Target(mc_sleep.HoldPolicy(fake.port, **policy), lambda: ("zzz", 20, "1.21.1", None))


class RouterCase(unittest.TestCase):

    def setUp(self):
        self.things = []

    def tearDown(self):
        for thing in self.things:
            thing.stop()

    def fake(self, **kw):
        fake = FakeServer(**kw)
        fake.start()
        self.things.append(fake)
        return fake

    def router(self, resolve, **config):
        listener = mc_router.RouterListener(dict({"port": 0, "bind_host": "127.0.0.1"}, **config), resolve)
        listener.start()
        self.assertTrue(listener.bound.wait(5))
        self.things.append(listener)
        return listener

    def connect(self, listener):
        return socket.create_connection(("127.0.0.1", listener.port), timeout=10)

    def welcome(self, listener, host, name="Steve", suffix=""):
        client = self.connect(listener)
        client.sendall(handshake(host=host + suffix) + login(name))
        try:
            pid, data, pos = read_packet(client)
        except (mc_protocol.ProtocolError, OSError):
            return None, client
        return data[pos:], client


class TestRouting(RouterCase):

    def test_hostname_picks_the_server_and_bytes_are_intact(self):
        survie, creatif = self.fake(label="survie"), self.fake(label="creatif")
        table = {"survie": target_for(survie), "creatif": target_for(creatif)}
        listener = self.router(table.get, routes={"play.example.fr": "survie", "crea.example.fr": "creatif"})
        sent = handshake(host="crea.example.fr") + login("Alex")
        client = self.connect(listener)
        client.sendall(sent)
        pid, data, pos = read_packet(client)
        self.assertEqual(data[pos:], b"welcome-creatif")
        blob = os.urandom(150000)
        client.sendall(blob)
        got = b""
        while len(got) < len(blob):
            chunk = client.recv(65536)
            self.assertTrue(chunk)
            got += chunk
        self.assertEqual(got, blob)
        self.assertEqual(creatif.seen[0]["hello_raw"], sent)
        self.assertEqual(survie.seen, [])
        client.close()

    def test_suffixes_case_and_trailing_dot_are_normalised(self):
        survie = self.fake(label="survie")
        listener = self.router({"survie": target_for(survie)}.get, routes={"play.example.fr": "survie"})
        for suffix in ("\x00FML\x00", "\x00FORGE", "\x00FML2\x00", "\x00FML3\x00", "."):
            reply, client = self.welcome(listener, "Play.Example.FR", suffix=suffix)
            self.assertEqual(reply, b"welcome-survie", suffix)
            client.close()
        self.assertEqual(len(survie.seen), 5)

    def test_default_server_and_unknown_host(self):
        survie = self.fake(label="survie")
        table = {"survie": target_for(survie)}
        listener = self.router(table.get, routes={"play.example.fr": "survie"}, default="survie")
        reply, client = self.welcome(listener, "other.example.org")
        self.assertEqual(reply, b"welcome-survie")
        client.close()
        listener = self.router(table.get, routes={"play.example.fr": "survie"})
        client = self.connect(listener)
        client.sendall(handshake(host="other.example.org") + login())
        _pid, data, pos = read_packet(client)
        self.assertIn(T["router_unavailable"], mc_protocol.read_string(data, pos)[0])
        client.close()
        self.assertEqual(len(survie.seen), 1)

    def test_status_of_an_awake_routed_server_is_its_own(self):
        survie = self.fake(label="REAL")
        listener = self.router({"survie": target_for(survie)}.get, default="survie")
        client = self.connect(listener)
        client.sendall(handshake(host="x", state=1) + mc_protocol.packet(0x00))
        _pid, data, pos = read_packet(client)
        self.assertEqual(json.loads(mc_protocol.read_string(data, pos)[0])["description"]["text"], "REAL")
        client.close()

    def test_sleeping_server_answers_status_with_its_own_motd(self):
        down = mc_router.Target(
            mc_sleep.HoldPolicy(1, probe=lambda: mc_sleep.BACKEND_DOWN),
            lambda: ("endormi", 20, "1.21.1", None))
        listener = self.router({"s": down}.get, default="s")
        client = self.connect(listener)
        client.sendall(handshake(host="x", state=1) + mc_protocol.packet(0x00))
        _pid, data, pos = read_packet(client)
        self.assertEqual(json.loads(mc_protocol.read_string(data, pos)[0])["description"]["text"], "endormi")
        client.close()

    def test_proxy_v2_out_carries_the_real_addresses(self):
        survie = self.fake(expect_proxy=True)
        listener = self.router({"s": target_for(survie)}.get, default="s", proxy_out=True)
        reply, client = self.welcome(listener, "x")
        self.assertEqual(reply, b"welcome-fake")
        raw = survie.seen[0]["proxy_raw"]
        self.assertEqual(raw[:12], mc_protocol.PROXY_V2_SIGNATURE)
        self.assertEqual((raw[12], raw[13]), (0x21, 0x11))
        self.assertEqual(raw[16:20], socket.inet_aton("127.0.0.1"))
        client.close()

    def test_proxy_v2_in_from_a_trusted_balancer_gives_the_real_client(self):
        survie = self.fake(expect_proxy=True)
        listener = self.router({"s": target_for(survie)}.get, default="s", proxy_in=True,
                               trusted_proxies=["127.0.0.0/8"], proxy_out=True)
        client = self.connect(listener)
        header = mc_protocol.proxy_v2_header(("203.0.113.9", 40000), ("198.51.100.1", 25565))
        client.sendall(header + handshake(host="x") + login())
        read_packet(client)
        raw = survie.seen[0]["proxy_raw"]
        self.assertEqual(raw[16:20], socket.inet_aton("203.0.113.9"))
        self.assertEqual(survie.seen[0]["hello_raw"], handshake(host="x") + login())
        client.close()

    def test_proxy_v2_in_refused_from_an_untrusted_peer_or_without_header(self):
        survie = self.fake()
        listener = self.router({"s": target_for(survie)}.get, default="s", proxy_in=True,
                               trusted_proxies=["10.0.0.0/8"])
        reply, client = self.welcome(listener, "x")
        self.assertIsNone(reply)
        client.close()
        listener = self.router({"s": target_for(survie)}.get, default="s", proxy_in=True,
                               trusted_proxies=["127.0.0.0/8"])
        reply, client = self.welcome(listener, "x")
        self.assertIsNone(reply)
        client.close()
        self.assertEqual(survie.seen, [])


class TestRouterLimits(RouterCase):

    def test_deny_and_allow_lists(self):
        survie = self.fake()
        table = {"s": target_for(survie)}
        listener = self.router(table.get, default="s", deny=["127.0.0.0/8"])
        reply, client = self.welcome(listener, "x")
        self.assertIsNone(reply)
        client.close()
        listener = self.router(table.get, default="s", allow=["10.0.0.0/8"])
        reply, client = self.welcome(listener, "x")
        self.assertIsNone(reply)
        client.close()
        listener = self.router(table.get, default="s", allow=["127.0.0.0/8"], deny=["10.0.0.0/8"])
        reply, client = self.welcome(listener, "x")
        self.assertEqual(reply, b"welcome-fake")
        client.close()

    def test_per_ip_concurrency_limit(self):
        survie = self.fake()
        listener = self.router({"s": target_for(survie)}.get, default="s", per_ip=2)
        held = []
        for _ in range(2):
            reply, client = self.welcome(listener, "x")
            self.assertEqual(reply, b"welcome-fake")
            held.append(client)
        reply, client = self.welcome(listener, "x")
        self.assertIsNone(reply)
        client.close()
        held[0].close()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            reply, client = self.welcome(listener, "x")
            client.close()
            if reply:
                break
            time.sleep(0.1)
        self.assertEqual(reply, b"welcome-fake")
        held[1].close()

    def test_rate_limit_per_second(self):
        survie = self.fake()
        listener = self.router({"s": target_for(survie)}.get, default="s", per_second=2, per_ip=16)
        results = []
        for _ in range(4):
            reply, client = self.welcome(listener, "x")
            results.append(reply)
            client.close()
        self.assertEqual(results[:2], [b"welcome-fake"] * 2)
        self.assertIn(None, results[2:])

    def test_banned_address_of_the_target_server_is_refused(self):
        survie = self.fake()
        banned = mock.Mock()
        banned.contains = lambda ip: ip == "127.0.0.1"
        target = mc_router.Target(mc_sleep.HoldPolicy(survie.port), lambda: ("z", 1, "1", None), banned)
        listener = self.router({"s": target}.get, default="s")
        reply, client = self.welcome(listener, "x")
        self.assertIsNone(reply)
        client.close()
        self.assertEqual(survie.seen, [])

    def test_a_silent_client_does_not_block_the_others(self):
        survie = self.fake()
        listener = self.router({"s": target_for(survie)}.get, default="s")
        idle = [self.connect(listener) for _ in range(3)]
        reply, client = self.welcome(listener, "x")
        self.assertEqual(reply, b"welcome-fake")
        client.close()
        for sock in idle:
            sock.close()

    def test_garbage_does_not_reach_a_server(self):
        survie = self.fake()
        listener = self.router({"s": target_for(survie)}.get, default="s")
        client = self.connect(listener)
        client.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n" * 3)
        client.settimeout(5)
        try:
            self.assertEqual(client.recv(100), b"")
        except ConnectionResetError:
            pass
        client.close()
        self.assertEqual(survie.seen, [])


class TestRouterHold(RouterCase):

    def test_player_who_wakes_a_routed_server_is_relayed_to_it(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        asked = []
        policy = mc_sleep.HoldPolicy(port, timeout=20, on_hold=lambda p: (asked.append(p) or True, "waking"))
        listener = self.router({"s": mc_router.Target(policy, lambda: ("z", 1, "1", None))}.get, default="s")
        client = self.connect(listener)
        sent = handshake(host="play.example.fr") + login("Steve")
        client.sendall(sent)
        time.sleep(1.2)
        fake = self.fake(port=port)
        client.settimeout(15)
        pid, data, pos = read_packet(client)
        self.assertEqual(data[pos:], b"welcome-fake")
        client.sendall(b"hello-after-wake")
        self.assertEqual(client.recv(100), b"hello-after-wake")
        self.assertEqual(asked, ["Steve"])
        self.assertEqual(fake.seen[0]["hello_raw"], sent)
        client.close()

    def test_refused_wake_gets_the_reason(self):
        policy = mc_sleep.HoldPolicy(1, probe=lambda: mc_sleep.BACKEND_DOWN,
                                     on_hold=lambda p: (False, "pas pour toi"))
        listener = self.router({"s": mc_router.Target(policy, lambda: ("z", 1, "1", None))}.get, default="s")
        client = self.connect(listener)
        client.sendall(handshake() + login())
        _pid, data, pos = read_packet(client)
        self.assertIn("pas pour toi", mc_protocol.read_string(data, pos)[0])
        client.close()


class TestRouterConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patch = mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(self.tmp, "servers.json"))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_defaults_and_atomic_private_save(self):
        config = mc_router.load()
        self.assertFalse(config["enabled"])
        config["routes"] = {"Play.Example.FR.": "a"}
        mc_router.save(config)
        self.assertEqual(mc_router.load()["routes"], {"play.example.fr": "a"})
        mode = stat.S_IMODE(os.stat(mc_router.path()).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(os.listdir(self.tmp), ["router.json"])

    def test_invalid_values_are_rejected(self):
        for bad in ({"port": 0}, {"port": "x"}, {"routes": {"bad host": "a"}}, {"allow": ["nope"]},
                    {"proxy_in": True}, {"per_ip": 0}, {"bind_host": "x"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                mc_router.validate(bad)

    def test_corrupt_file_is_reported(self):
        with open(mc_router.path(), "w") as f:
            f.write("{nope")
        with self.assertRaises(mc_servers.DataFileError):
            mc_router.load()


class TestRouterApi(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patch = mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(self.tmp, "servers.json"))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.saved = []
        self.server = {"dossier_serveur": os.path.join(self.tmp, "a"), "port": 25570, "rcon_port": 25580}
        os.makedirs(self.server["dossier_serveur"])
        patches = [
            mock.patch("mc_api.load_server", side_effect=lambda n: ((n, self.server), None) if n == "a"
                       else (None, mc_api.result(False, "server_not_found", server=n))),
            mock.patch("mc_api.mc_config.save_config", side_effect=lambda c: self.saved.append(dict(c))),
            mock.patch("mc_api.mc_core.sync_server_properties", return_value=[]),
            mock.patch("mc_api.mc_servers.list_servers", return_value={}),
            mock.patch("mc_api.mc_servers.find_port_conflict", return_value=None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_route_default_allow_deny_cycle(self):
        res = mc_api.router_command("route", ["add", "Play.Example.FR", "a"])
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["config"]["routes"], {"play.example.fr": "a"})
        self.assertTrue(self.saved[-1]["router_backend"])
        self.assertEqual(self.saved[-1]["internal_port"], 35570)
        self.assertTrue(mc_api.router_command("default", ["a"])["ok"])
        self.assertEqual(mc_router.load()["default"], "a")
        self.assertTrue(mc_api.router_command("allow", ["add", "10.0.0.5/8"])["ok"])
        self.assertTrue(mc_api.router_command("deny", ["add", "192.0.2.0/24"])["ok"])
        listed = mc_api.router_command("route", ["list"])["config"]
        self.assertEqual((listed["allow"], listed["deny"]), (["10.0.0.0/8"], ["192.0.2.0/24"]))
        self.assertTrue(mc_api.router_command("allow", ["remove", "10.0.0.0/8"])["ok"])
        self.assertTrue(mc_api.router_command("route", ["remove", "play.example.fr"])["ok"])
        status = mc_api.router_command("status")["config"]
        self.assertEqual((status["routes"], status["allow"], status["deny"]), ({}, [], ["192.0.2.0/24"]))

    def test_enable_disable_and_usage_errors(self):
        res = mc_api.router_command("enable", port=25599, per_ip=3)
        self.assertTrue(res["ok"])
        config = mc_router.load()
        self.assertEqual((config["enabled"], config["port"], config["per_ip"]), (True, 25599, 3))
        self.assertTrue(mc_api.router_command("disable")["ok"])
        self.assertFalse(mc_router.load()["enabled"])
        for action, args in (("route", ["add", "x"]), ("allow", ["add", "nope"]), ("default", []),
                             ("route", ["add", "bad host", "a"]), ("status", ["extra"])):
            self.assertEqual(mc_api.router_command(action, args)["code"], "router_usage", (action, args))
        self.assertFalse(mc_api.router_command("route", ["add", "x.fr", "ghost"])["ok"])

    def test_enable_refuses_a_port_used_by_a_server(self):
        with mock.patch("mc_api.mc_servers.list_servers", return_value={"a": {"dossier_serveur": self.server["dossier_serveur"]}}), \
             mock.patch("mc_api.mc_config.load_config", return_value=self.server):
            res = mc_api.router_command("enable", port=25570)
        self.assertEqual(res["code"], "router_port_conflict")


if __name__ == "__main__":
    unittest.main()
