"""
test_sleep_hold.py — hold mode, PROXY protocol v2, banned addresses and the
protocol helpers, end to end on 127.0.0.1 with a fake Minecraft server.
"""
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import mc_protocol
import mc_proxy
import mc_sleep
from fakeserver import FakeServer
from mc_lang import T
from mc_protocol import packet, write_string, write_varint


def handshake(protocol=767, host="localhost", port=25565, state=2):
    return packet(0x00, write_varint(protocol) + write_string(host) + struct.pack(">H", port) + write_varint(state))


def login(name="Steve"):
    return packet(0x00, write_string(name) + b"\x00" * 16)


def read_packet(sock):
    return mc_protocol.read_packet_raw(sock)[:3]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_listener(hold=None, banned=None, on_login=None):
    listener = mc_sleep.SleepListener(
        "t", 0, lambda: ("zzz", 20, "1.21.1", None), on_login or (lambda p: "no"),
        bind_host="127.0.0.1", hold=hold, banned=banned)
    listener.start()
    assert listener.bound.wait(5)
    return listener


class TestProtocolHelpers(unittest.TestCase):

    def test_normalize_host(self):
        for raw, want in (("Play.Example.FR", "play.example.fr"),
                          ("play.example.fr.", "play.example.fr"),
                          ("play.example.fr\x00FML2\x00", "play.example.fr"),
                          ("play.example.fr\x00FORGE", "play.example.fr"),
                          ("  play.example.fr:25565 ", "play.example.fr"),
                          ("", "")):
            self.assertEqual(mc_protocol.normalize_host(raw), want)

    def test_proxy_v2_ipv4_header_matches_the_specification(self):
        header = mc_protocol.proxy_v2_header(("203.0.113.7", 51234), ("198.51.100.9", 25565))
        self.assertEqual(header[:12], b"\r\n\r\n\x00\r\nQUIT\n")
        self.assertEqual(header[12], 0x21)
        self.assertEqual(header[13], 0x11)
        self.assertEqual(struct.unpack(">H", header[14:16])[0], 12)
        self.assertEqual(header[16:20], socket.inet_aton("203.0.113.7"))
        self.assertEqual(header[20:24], socket.inet_aton("198.51.100.9"))
        self.assertEqual(struct.unpack(">HH", header[24:28]), (51234, 25565))
        self.assertEqual(len(header), 28)

    def test_proxy_v2_ipv6_and_round_trip(self):
        header = mc_protocol.proxy_v2_header(("2001:db8::1", 4000), ("2001:db8::2", 25565))
        self.assertEqual((header[12], header[13], len(header)), (0x21, 0x21, 16 + 36))
        a, b = socket.socketpair()
        a.sendall(header)
        self.assertEqual(mc_protocol.read_proxy_v2(b), (("2001:db8::1", 4000), ("2001:db8::2", 25565)))
        a.sendall(mc_protocol.proxy_v2_header(("1.2.3.4", 5), ("6.7.8.9", 10)))
        self.assertEqual(mc_protocol.read_proxy_v2(b), (("1.2.3.4", 5), ("6.7.8.9", 10)))
        a.sendall(b"GET / HTTP/1.1\r\n\r\n" * 2)
        with self.assertRaises(mc_protocol.ProtocolError):
            mc_protocol.read_proxy_v2(b)
        a.close()
        b.close()

    def test_read_hello_keeps_the_raw_bytes_and_the_player(self):
        a, b = socket.socketpair()
        payload = handshake(host="play.example.fr\x00FML2\x00") + login("Alex")
        a.sendall(payload)
        hello = mc_protocol.read_hello(b)
        self.assertEqual((hello.host, hello.player, hello.next_state), ("play.example.fr", "Alex", 2))
        self.assertEqual(hello.raw, payload)
        a.close()
        b.close()


class TestBannedIPs(unittest.TestCase):

    def test_reads_the_file_and_ignores_expired_bans(self):
        path = os.path.join(tempfile.mkdtemp(), "banned-ips.json")
        self.assertFalse(mc_proxy.BannedIPs(path).contains("1.2.3.4"))
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"ip": "1.2.3.4", "expires": "forever"},
                       {"ip": "5.6.7.8", "expires": "2001-01-01 00:00:00 +0000"},
                       {"ip": "9.9.9.9", "expires": "2999-01-01 00:00:00 +0000"}], f)
        banned = mc_proxy.BannedIPs(path)
        self.assertTrue(banned.contains("1.2.3.4"))
        self.assertFalse(banned.contains("5.6.7.8"))
        self.assertTrue(banned.contains("9.9.9.9"))
        self.assertTrue(banned.contains("::ffff:1.2.3.4"))


class TestHoldListener(unittest.TestCase):

    def setUp(self):
        self.things = []

    def tearDown(self):
        for thing in self.things:
            thing.stop()

    def _fake(self, **kw):
        fake = FakeServer(**kw)
        fake.start()
        self.things.append(fake)
        return fake

    def _listener(self, **kw):
        listener = start_listener(**kw)
        self.things.append(listener)
        return listener

    def _connect(self, listener):
        return socket.create_connection(("127.0.0.1", listener.port), timeout=10)

    def test_awake_server_gets_the_exact_bytes_both_ways(self):
        fake = self._fake()
        listener = self._listener(hold=mc_sleep.HoldPolicy(fake.port))
        client = self._connect(listener)
        sent = handshake(host="play.example.fr") + login("Steve")
        client.sendall(sent)
        pid, data, pos = read_packet(client)
        self.assertEqual((pid, data[pos:]), (2, b"welcome-fake"))
        blob = os.urandom(200000)
        client.sendall(blob)
        got = b""
        while len(got) < len(blob):
            chunk = client.recv(65536)
            self.assertTrue(chunk)
            got += chunk
        self.assertEqual(got, blob)
        self.assertEqual(fake.seen[0]["hello_raw"], sent)
        client.close()

    def test_status_of_an_awake_server_is_the_real_one(self):
        fake = self._fake(label="REAL")
        listener = self._listener(hold=mc_sleep.HoldPolicy(fake.port))
        client = self._connect(listener)
        client.sendall(handshake(state=1) + packet(0x00))
        _pid, data, pos = read_packet(client)
        self.assertEqual(json.loads(mc_protocol.read_string(data, pos)[0])["description"]["text"], "REAL")
        client.close()

    def test_proxy_protocol_header_carries_the_real_addresses(self):
        fake = self._fake(expect_proxy=True)
        listener = self._listener(hold=mc_sleep.HoldPolicy(fake.port, proxy_protocol=True))
        client = self._connect(listener)
        client.sendall(handshake() + login())
        read_packet(client)
        sent_from = client.getsockname()
        raw = fake.seen[0]["proxy_raw"]
        self.assertEqual(raw[:12], b"\r\n\r\n\x00\r\nQUIT\n")
        self.assertEqual((raw[12], raw[13]), (0x21, 0x11))
        self.assertEqual(struct.unpack(">H", raw[14:16])[0], 12)
        self.assertEqual(raw[16:20], socket.inet_aton("127.0.0.1"))
        self.assertEqual(raw[20:24], socket.inet_aton("127.0.0.1"))
        self.assertEqual(struct.unpack(">HH", raw[24:28]), (sent_from[1], listener.port))
        self.assertEqual(fake.seen[0]["hello_raw"], handshake() + login())
        client.close()

    def test_hold_relays_the_player_who_woke_the_server(self):
        port = free_port()
        asked = []
        policy = mc_sleep.HoldPolicy(port, timeout=20, on_hold=lambda p: (asked.append(p) or True, "waking"))
        listener = self._listener(hold=policy)
        client = self._connect(listener)
        sent = handshake() + login("Steve")
        client.sendall(sent)
        time.sleep(1.2)
        fake = self._fake(port=port)
        client.settimeout(15)
        pid, data, pos = read_packet(client)
        self.assertEqual((pid, data[pos:]), (2, b"welcome-fake"))
        client.sendall(b"ping-after-wake")
        self.assertEqual(client.recv(100), b"ping-after-wake")
        self.assertEqual(asked, ["Steve"])
        self.assertEqual(fake.seen[0]["hello_raw"], sent)
        client.close()

    def test_hold_waits_for_readiness_not_just_the_port(self):
        fake = self._fake()
        ready = threading.Event()
        policy = mc_sleep.HoldPolicy(fake.port, timeout=20, ready=ready.is_set,
                                     probe=lambda: mc_sleep.BACKEND_DOWN if not ready.is_set() else mc_sleep.BACKEND_UP,
                                     on_hold=lambda p: (True, "waking"))
        listener = self._listener(hold=policy)
        client = self._connect(listener)
        client.sendall(handshake() + login())
        client.settimeout(0.8)
        with self.assertRaises(socket.timeout):
            client.recv(10)
        self.assertEqual(fake.seen, [])
        ready.set()
        client.settimeout(10)
        self.assertEqual(read_packet(client)[0], 2)
        client.close()

    def test_refused_player_gets_the_text_and_nothing_is_held(self):
        policy = mc_sleep.HoldPolicy(free_port(), on_hold=lambda p: (False, "unknown player"))
        listener = self._listener(hold=policy)
        client = self._connect(listener)
        client.sendall(handshake() + login("scanner"))
        _pid, data, pos = read_packet(client)
        self.assertEqual(json.loads(mc_protocol.read_string(data, pos)[0])["text"], "unknown player")
        client.close()

    def test_hold_timeout_disconnects_politely(self):
        policy = mc_sleep.HoldPolicy(free_port(), timeout=1, on_hold=lambda p: (True, "waking"))
        listener = self._listener(hold=policy)
        client = self._connect(listener)
        client.sendall(handshake() + login())
        _pid, data, pos = read_packet(client)
        self.assertEqual(json.loads(mc_protocol.read_string(data, pos)[0])["text"], T["sleep_hold_timeout_text"])
        client.close()

    def test_sleeping_status_when_the_server_is_down(self):
        listener = self._listener(hold=mc_sleep.HoldPolicy(free_port()))
        client = self._connect(listener)
        client.sendall(handshake(state=1) + packet(0x00))
        _pid, data, pos = read_packet(client)
        self.assertEqual(json.loads(mc_protocol.read_string(data, pos)[0])["description"]["text"], "zzz")
        client.close()

    def test_a_silent_client_does_not_block_the_others(self):
        fake = self._fake()
        listener = self._listener(hold=mc_sleep.HoldPolicy(fake.port))
        silent = [self._connect(listener) for _ in range(3)]
        start = time.time()
        client = self._connect(listener)
        client.sendall(handshake() + login())
        self.assertEqual(read_packet(client)[0], 2)
        self.assertLess(time.time() - start, 2)
        client.close()
        for s in silent:
            s.close()

    def test_banned_address_is_refused_before_anything_is_read(self):
        path = os.path.join(tempfile.mkdtemp(), "banned-ips.json")
        with open(path, "w") as f:
            json.dump([{"ip": "127.0.0.1", "expires": "forever"}], f)
        logins = []
        listener = self._listener(banned=mc_proxy.BannedIPs(path), on_login=lambda p: logins.append(p) or "x")
        client = self._connect(listener)
        client.sendall(handshake() + login())
        client.settimeout(5)
        try:
            self.assertEqual(client.recv(10), b"")
        except ConnectionResetError:
            pass
        self.assertEqual(logins, [])
        client.close()


class TestHoldKeepalive(unittest.TestCase):

    def test_pings_are_answered_and_swallowed_before_the_replay(self):
        server_side, client = socket.socketpair()
        hello = mc_protocol.Hello(767, "h", 25565, 2, "Steve", handshake() + login())
        state = {"ready": False}

        def attempt():
            return object() if state["ready"] else None

        pings = []

        def client_loop():
            client.settimeout(5)
            while len(pings) < 2:
                pid, data, pos, _ = mc_protocol.read_packet_raw(client)
                self.assertEqual(pid, mc_protocol.LOGIN_PLUGIN_REQUEST)
                message_id, _ = mc_protocol.read_varint(data, pos)
                pings.append(message_id)
                client.sendall(packet(mc_protocol.LOGIN_PLUGIN_RESPONSE, write_varint(message_id) + b"\x00"))
            state["ready"] = True

        thread = threading.Thread(target=client_loop)
        thread.start()
        result = mc_proxy.hold(server_side, hello, attempt, timeout=10, keepalive=0.2, poll=0.05)
        thread.join()
        self.assertIsNotNone(result)
        self.assertEqual(len(pings), 2)
        server_side.settimeout(0.2)
        with self.assertRaises(socket.timeout):
            server_side.recv(10)
        server_side.close()
        client.close()


class TestHoldConfiguration(unittest.TestCase):

    def setUp(self):
        import mc_core
        import mc_config
        import mc_servers
        self.core, self.cfg = mc_core, mc_config
        self.tmp = tempfile.mkdtemp()
        self.folder = os.path.join(self.tmp, "a")
        os.makedirs(os.path.join(self.folder, "config"))
        with open(os.path.join(self.folder, "server.properties"), "w") as f:
            f.write("server-port=25570\nserver-ip=\nmax-tick-time=60000\n")
        with open(os.path.join(self.folder, "config", "paper-global.yml"), "w") as f:
            f.write("proxies:\n  proxy-protocol: false\n")
        self.config = {"dossier_serveur": self.folder, "port": 25570, "rcon_port": 25580,
                       "mcrcon_pass": "x", "sleep_enabled": 1, "loader": "paper"}
        patch = mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(self.tmp, "servers.json"))
        patch.start()
        self.addCleanup(patch.stop)
        with open(mc_servers.REGISTRY_FILE, "w") as f:
            json.dump({"active": "a", "servers": {"a": {"id": 1, "dossier_serveur": self.folder}}}, f)

    def _props(self):
        with open(os.path.join(self.folder, "server.properties")) as f:
            return f.read()

    def test_hold_moves_the_server_to_an_internal_port_and_back(self):
        status, _ = self.cfg.apply_join_mode(self.config, "a", "hold")
        self.assertEqual(status, "ok")
        self.assertEqual(self.config["internal_port"], 35570)
        self.assertIn("server-port=35570", self._props())
        self.assertIn("server-ip=127.0.0.1", self._props())
        self.assertEqual(self.core.game_port(self.config), 35570)
        self.assertTrue(self.core.use_proxy_protocol(self.config))
        with open(os.path.join(self.folder, "config", "paper-global.yml")) as f:
            self.assertIn("proxy-protocol: true", f.read())
        status, _ = self.cfg.apply_join_mode(self.config, "a", "kick")
        self.assertEqual(status, "ok")
        self.assertIn("server-port=25570", self._props())
        self.assertIn("server-ip=\n", self._props())
        with open(os.path.join(self.folder, "config", "paper-global.yml")) as f:
            self.assertIn("proxy-protocol: false", f.read())
        self.assertEqual(self.core.game_port(self.config), 25570)

    def test_hold_needs_sleep_and_refuses_proxies(self):
        self.config["sleep_enabled"] = 0
        self.assertEqual(self.cfg.apply_join_mode(self.config, "a", "hold")[0], "conflict")
        self.config.update(sleep_enabled=1, loader="Velocity")
        self.assertEqual(self.cfg.apply_join_mode(self.config, "a", "hold")[0], "conflict")

    def test_internal_port_skips_a_taken_port(self):
        with mock.patch("mc_servers.find_port_conflict", side_effect=lambda port=None, **kw: "b" if port == 35570 else None):
            self.cfg.apply_join_mode(self.config, "a", "hold")
        self.assertEqual(self.config["internal_port"], 35571)

    def test_freeze_needs_hold_and_relaxes_the_watchdog(self):
        self.assertEqual(self.cfg.apply_freeze(self.config, "a", True)[0], "conflict")
        self.cfg.apply_join_mode(self.config, "a", "hold")
        self.assertEqual(self.cfg.apply_freeze(self.config, "a", True)[0], "ok")
        self.assertIn("max-tick-time=-1", self._props())
        self.assertEqual(self.config["sleep_watchdog_previous"]["max-tick-time"], "60000")
        self.cfg.apply_freeze(self.config, "a", False)
        self.assertIn("max-tick-time=60000", self._props())

    def test_ports_are_validated_against_the_internal_one(self):
        self.cfg.apply_join_mode(self.config, "a", "hold")
        status, _ = self.cfg.set_value(self.config, "a", "port", "35570")
        self.assertEqual(status, "conflict")

    def test_suspend_flushes_then_stops_the_processes_and_resume_continues_them(self):
        core = self.core
        with mock.patch.object(core, "is_server_running", return_value=True), \
             mock.patch.object(core, "send_rcon", return_value=True) as rcon, \
             mock.patch.object(core, "_signal_server", return_value=True) as sig:
            self.assertEqual(core.suspend_server(self.config), (True, "suspended"))
            rcon.assert_called_once_with(self.config, "save-all flush")
            sig.assert_called_once_with(self.config, "suspend")
            self.assertTrue(core.is_suspended(self.config))
            self.assertEqual(core.suspend_server(self.config), (True, "already_suspended"))
            self.assertTrue(core.resume_server(self.config))
            sig.assert_called_with(self.config, "resume")
            self.assertFalse(core.is_suspended(self.config))
            self.assertFalse(core.resume_server(self.config))

    def test_a_failed_flush_never_stops_the_server(self):
        core = self.core
        with mock.patch.object(core, "is_server_running", return_value=True), \
             mock.patch.object(core, "send_rcon", return_value=False), \
             mock.patch.object(core, "_signal_server") as sig:
            self.assertEqual(core.suspend_server(self.config), (False, "rcon_error"))
            sig.assert_not_called()
            self.assertFalse(core.is_suspended(self.config))

    def test_stale_marker_of_a_dead_server_is_dropped(self):
        core = self.core
        with open(os.path.join(self.folder, core.SUSPENDED_MARKER), "w") as f:
            f.write("{}")
        with mock.patch.object(core, "is_server_running", return_value=False):
            self.assertFalse(core.is_suspended(self.config))
        self.assertFalse(os.path.exists(os.path.join(self.folder, core.SUSPENDED_MARKER)))

    def test_state_is_sleeping_while_suspended_and_wake_resumes(self):
        import mc_api
        core = self.core
        with open(os.path.join(self.folder, core.SUSPENDED_MARKER), "w") as f:
            f.write("{}")
        with mock.patch.object(core, "is_server_running", return_value=True):
            self.assertEqual(mc_api.server_state(self.config), "sleeping")
            with mock.patch.object(core, "_signal_server", return_value=True):
                res = mc_api.wake("a", self.config)
        self.assertEqual(res["code"], "resumed")

    def test_sleep_configure_validates_the_combination(self):
        import mc_api
        res = mc_api.sleep_configure("a", dict(self.config, sleep_enabled=0), join_mode="hold")
        self.assertFalse(res["ok"])
        res = mc_api.sleep_configure("a", self.config, freeze=True)
        self.assertFalse(res["ok"])
        res = mc_api.sleep_configure("a", self.config, join_mode="hold", hold_timeout_s=5)
        self.assertEqual(res["code"], "sleep_hold_timeout_range")
        res = mc_api.sleep_configure("a", self.config, join_mode="hold", hold_timeout_s=90)
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["join_mode"], res["hold_timeout_s"], res["internal_port"]), ("hold", 90, 35570))


if __name__ == "__main__":
    unittest.main(verbosity=2)
