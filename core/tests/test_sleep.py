"""
test_sleep.py — Sleep listener (Minecraft protocol), known players, idle
detection and the daemon's wake decision.
"""
import json
import os
import socket
import struct
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_sleep
from mc_sleep import packet, write_string, write_varint, read_varint


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _handshake(protocol, port, next_state):
    return packet(0x00, write_varint(protocol) + write_string("localhost")
                  + struct.pack(">H", port) + write_varint(next_state))


def _read_packet(sock):
    length = mc_sleep.read_varint_sock(sock)
    data = mc_sleep._recv_exact(sock, length)
    pid, pos = read_varint(data, 0)
    return pid, data, pos


class TestProtocol(unittest.TestCase):

    def test_varint_round_trip(self):
        for value in (0, 1, 127, 128, 255, 25565, 2097151, 2147483647, -1):
            self.assertEqual(read_varint(write_varint(value), 0)[0], value)

    def test_handshake_parse(self):
        pkt = _handshake(767, 25565, 2)
        pid, data, pos = None, pkt, 0
        _length, pos = read_varint(data, 0)
        pid, pos = read_varint(data, pos)
        self.assertEqual(pid, 0)
        self.assertEqual(mc_sleep.parse_handshake(data, pos), (767, "localhost", 25565, 2))

    def test_known_players(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "usercache.json"), "w", encoding="utf-8-sig") as f:
            json.dump([{"name": "Steve", "uuid": "x"}], f)
        with open(os.path.join(tmp, "ops.json"), "w") as f:
            json.dump([{"name": "Admin", "uuid": "y", "level": 4}], f)
        with open(os.path.join(tmp, "whitelist.json"), "w") as f:
            f.write("{broken")
        self.assertEqual(mc_sleep.known_players([tmp, "/nope"], ["Guest"]), {"steve", "admin", "guest"})


class TestListener(unittest.TestCase):

    def setUp(self):
        self.port = _free_port()
        self.logins = []

        def on_login(name):
            self.logins.append(name)
            return "wake" if name == "Steve" else "unknown"

        self.listener = mc_sleep.SleepListener(
            "test", self.port, lambda: ("zzz", 20, "1.21.1", None), on_login)
        self.listener.start()
        self.assertTrue(self.listener.bound.wait(5))

    def tearDown(self):
        self.listener.stop()

    def _connect(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        return s

    def test_status_copies_protocol_and_answers_ping(self):
        s = self._connect()
        s.sendall(_handshake(767, self.port, 1) + packet(0x00))
        pid, data, pos = _read_packet(s)
        self.assertEqual(pid, 0)
        doc = json.loads(mc_sleep.read_string(data, pos)[0])
        self.assertEqual(doc["version"]["protocol"], 767)
        self.assertEqual(doc["players"]["online"], 0)
        self.assertEqual(doc["players"]["max"], 20)
        self.assertEqual(doc["description"]["text"], "zzz")
        s.sendall(packet(0x01, struct.pack(">q", 123456789)))
        pid, data, pos = _read_packet(s)
        self.assertEqual((pid, data[pos:]), (1, struct.pack(">q", 123456789)))
        s.close()

    def _login(self, name):
        s = self._connect()
        s.sendall(_handshake(767, self.port, 2) + packet(0x00, write_string(name) + b"\x00" * 16))
        pid, data, pos = _read_packet(s)
        s.close()
        return pid, json.loads(mc_sleep.read_string(data, pos)[0])["text"]

    def test_login_asks_the_decision_and_disconnects(self):
        self.assertEqual(self._login("Steve"), (0, "wake"))
        self.assertEqual(self._login("scanner"), (0, "unknown"))
        self.assertEqual(self.logins, ["Steve", "scanner"])

    def test_garbage_and_legacy_ping_are_ignored(self):
        for payload in (b"\xfe\x01", b"GET / HTTP/1.1\r\n\r\n"):
            s = self._connect()
            s.sendall(payload)
            s.settimeout(mc_sleep.IO_TIMEOUT + 3)
            try:
                self.assertEqual(s.recv(10), b"")
            except ConnectionResetError:
                pass
            s.close()
        self.assertEqual(self.logins, [])
        self.assertEqual(self._login("Steve"), (0, "wake"))  # still serving


class TestIdleAndWake(unittest.TestCase):

    def setUp(self):
        import mc_daemon
        self.d = mc_daemon
        self.config = {"dossier_serveur": tempfile.mkdtemp(), "sleep_enabled": 1,
                       "sleep_after": 600, "always_on": 1, "mcrcon_pass": "x"}
        self.state = self.d._new_state()

    def _tick(self, online, now, frozen=False):
        with mock.patch("mc_api.query_players", return_value=(True, {"online": online, "max": 20, "players": []})), \
             mock.patch("mc_api.is_frozen", return_value=frozen), \
             mock.patch("mc_api.stop", return_value={"ok": True, "code": "stopped"}) as stop:
            slept = self.d._put_to_sleep_if_idle("a", self.config, self.state, now=now)
        return slept, stop

    def test_sleeps_only_after_the_delay_without_players(self):
        self.assertEqual(self._tick(0, 1000)[0], False)      # idle clock starts
        self.assertEqual(self._tick(0, 1500)[0], False)
        self.assertEqual(self._tick(1, 1590)[0], False)      # a player resets it
        self.assertEqual(self._tick(0, 1600)[0], False)
        slept, stop = self._tick(0, 2200)
        self.assertTrue(slept)
        stop.assert_called_once_with("a", self.config, reason="sleep")

    def test_never_sleeps_while_frozen_or_disabled(self):
        self._tick(0, 0)
        self.assertFalse(self._tick(0, 5000, frozen=True)[0])
        self.config["sleep_enabled"] = 0
        self.assertFalse(self._tick(0, 9000)[0])

    def test_wake_decision(self):
        manager = self.d.SleepManager()
        manager._known, manager._known_at = {"steve"}, time.time()
        dossier = self.config["dossier_serveur"]
        cfg = {"mode_maintenance": 1, "stop_reason": "sleep", "always_on": 1}
        with open(os.path.join(dossier, "config.json"), "w") as f:
            json.dump(cfg, f)
        T = self.d.T
        self.assertEqual(manager.decide("a", dossier, "scanner"), T["sleep_kick_unknown"])
        with mock.patch("mc_api.is_frozen", return_value=True):
            self.assertEqual(manager.decide("a", dossier, "Steve"), T["sleep_kick_backup"])
        self.assertEqual(manager.decide("a", dossier, "Steve"), T["sleep_kick_waking"])
        self.assertEqual(manager.pop_wakes(), ["a"])
        # a manual stop is never woken
        cfg["stop_reason"] = "user"
        with open(os.path.join(dossier, "config.json"), "w") as f:
            json.dump(cfg, f)
        manager.decide("a", dossier, "Steve")
        self.assertEqual(manager.pop_wakes(), [])

    def test_listen_only_when_sleeping(self):
        should = self.d.SleepManager.should_listen
        with mock.patch("mc_core.is_server_running", return_value=False):
            self.assertTrue(should({"sleep_enabled": 1, "mode_maintenance": 1, "stop_reason": "sleep"}))
            self.assertFalse(should({"sleep_enabled": 1, "mode_maintenance": 1, "stop_reason": "user"}))
            self.assertFalse(should({"sleep_enabled": 0, "mode_maintenance": 1, "stop_reason": "sleep"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
