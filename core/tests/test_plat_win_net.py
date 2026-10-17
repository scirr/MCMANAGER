import socket
import unittest
from unittest import mock

import winfix
import plat_win_net as net


def ps(out, rc=0):
    return mock.patch.object(net, "run_powershell", return_value=(rc, out, ""))


def netstat(fixture, rc=0):
    return mock.patch.object(net, "run", return_value=(rc, winfix.load(fixture), ""))


NAMES = mock.patch.object(net, "_name_of", side_effect=lambda pid: {4128: "java.exe"}.get(pid))


class TestParseNetstat(unittest.TestCase):
    def test_english(self):
        rows = net.parse_netstat(winfix.load("netstat_en.txt"))
        listen = {(r["proto"], r["port"]): r["pid"] for r in rows if r["listening"]}
        self.assertEqual(listen[("tcp", 25565)], 4128)
        self.assertEqual(listen[("tcp", 25566)], 5000)
        self.assertEqual(listen[("udp", 24454)], 4128)
        self.assertNotIn(("tcp", 50122), listen)
        self.assertNotIn(("tcp", 49700), listen)

    def test_translated_states(self):
        rows = net.parse_netstat(winfix.load("netstat_fr_translated.txt"))
        listen = [(r["proto"], r["port"], r["pid"]) for r in rows if r["listening"]]
        self.assertEqual(sorted(listen), [("tcp", 25565, 4128), ("tcp", 25566, 5000),
                                          ("udp", 24454, 4128)])

    def test_ipv6_address_parsed(self):
        rows = net.parse_netstat("  TCP    [::1]:49700   [::1]:25565   ESTABLISHED   7760\n")
        self.assertEqual((rows[0]["address"], rows[0]["port"]), ("::1", 49700))
        self.assertFalse(rows[0]["listening"])

    def test_junk(self):
        self.assertEqual(net.parse_netstat(""), [])
        self.assertEqual(net.parse_netstat("Active Connections\n\n  Proto  Local\n"), [])


class TestPortListener(unittest.TestCase):
    def setUp(self):
        NAMES.start()
        self.addCleanup(NAMES.stop)

    def test_powershell_list(self):
        with ps(winfix.load("nettcp_list.json")), mock.patch.object(net, "run") as r:
            self.assertEqual(net.port_listener(25565), (4128, "java.exe"))
            r.assert_not_called()

    def test_powershell_single_object(self):
        with ps(winfix.load("nettcp_single.json")):
            self.assertEqual(net.port_listener(8080), (3300, None))
            self.assertFalse(net.listens_on_all_interfaces(8080))

    def test_udp(self):
        with ps(winfix.load("netudp_single.json")) as p:
            self.assertEqual(net.port_listener(24454, "udp"), (4128, "java.exe"))
        self.assertIn("Get-NetUDPEndpoint", p.call_args[0][0])

    def test_tcp_command(self):
        with ps("") as p:
            net.port_listener(25565)
        self.assertIn("Get-NetTCPConnection -State Listen -LocalPort 25565", p.call_args[0][0])

    def test_free_port(self):
        with ps(""), mock.patch.object(net, "run") as r:
            self.assertIsNone(net.port_listener(25565))
            self.assertIsNone(net.listens_on_all_interfaces(25565))
            r.assert_not_called()
        with ps("[]"):
            self.assertIsNone(net.port_listener(25565))

    def test_fallback_netstat_en_fr(self):
        for fixture in ("netstat_en.txt", "netstat_fr_translated.txt"):
            with ps("", rc=1), netstat(fixture) as r:
                self.assertEqual(net.port_listener(25565), (4128, "java.exe"))
            self.assertEqual(r.call_args[0][0], ["netstat", "-ano"])
            self.assertEqual(r.call_args[1]["encoding"], "oem")

    def test_fallback_on_garbage_json(self):
        with ps("Access denied"), netstat("netstat_en.txt"):
            self.assertEqual(net.port_listener(25566), (5000, None))

    def test_fallback_ipv6_and_udp(self):
        with ps("", rc=1), netstat("netstat_en.txt"):
            self.assertEqual(net.port_listener(25566)[0], 5000)
            self.assertEqual(net.port_listener(24454, "udp")[0], 4128)
            self.assertTrue(net.listens_on_all_interfaces(25566))
            self.assertFalse(net.listens_on_all_interfaces(8080))

    def test_established_is_not_listening(self):
        with ps("", rc=1), netstat("netstat_en.txt"):
            self.assertIsNone(net.port_listener(50122))

    def test_both_sources_fail(self):
        with ps("", rc=1), mock.patch.object(net, "run", return_value=(1, "", "x")):
            self.assertIsNone(net.port_listener(25565))

    def test_pid_zero_is_unreadable(self):
        with ps('{"LocalAddress":"0.0.0.0","LocalPort":9,"OwningProcess":0}'):
            self.assertEqual(net.port_listener(9), (None, None))


class TestPortInUse(unittest.TestCase):
    def test_real_bind_detection(self):
        held = socket.socket()
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        try:
            port = held.getsockname()[1]
            self.assertTrue(net.port_in_use(port, host="127.0.0.1"))
        finally:
            held.close()
        self.assertFalse(net.port_in_use(port, host="127.0.0.1"))

    def test_windows_uses_exclusive_option(self):
        sock = mock.Mock()
        with mock.patch.object(net, "_new_socket", return_value=sock), \
                mock.patch.object(net, "is_windows", return_value=True), \
                mock.patch.object(net.socket, "SO_EXCLUSIVEADDRUSE", -5, create=True):
            self.assertFalse(net.port_in_use(25565))
        sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET, -5, 1)
        sock.bind.assert_called_once_with(("0.0.0.0", 25565))
        sock.close.assert_called_once()

    def test_linux_uses_reuseaddr(self):
        sock = mock.Mock()
        sock.bind.side_effect = OSError(98, "in use")
        with mock.patch.object(net, "_new_socket", return_value=sock), \
                mock.patch.object(net, "is_windows", return_value=False):
            self.assertTrue(net.port_in_use(1))
        sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
