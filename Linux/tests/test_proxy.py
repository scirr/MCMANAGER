import io
import os
import socket
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_protocol
import mc_proxy


class BytesSocket:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def recv(self, count):
        return self.stream.read(count)


class TestProxy(unittest.TestCase):
    def test_limits_release_and_global_cap(self):
        tracker = mc_proxy.ConnectionTracker(3, 2)
        self.assertTrue(tracker.take("a"))
        self.assertTrue(tracker.take("a"))
        self.assertFalse(tracker.take("a"))
        self.assertTrue(tracker.take("b"))
        self.assertFalse(tracker.take("c"))
        tracker.release("a")
        self.assertTrue(tracker.take("c"))
        self.assertEqual(tracker.counts(), (3, {"a": 1, "b": 1, "c": 1}))

    def test_sliding_rate_window_and_independent_addresses(self):
        clock = mock.Mock(return_value=100)
        limiter = mc_proxy.RateLimiter(2, clock=clock)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))
        clock.return_value = 101
        self.assertTrue(limiter.allow("a"))

    def test_cidr_deny_wins_and_mapped_addresses(self):
        access = mc_proxy.AccessList(["192.0.2.0/24", "2001:db8::/32"], ["192.0.2.9/32"])
        for ip in ("192.0.2.8", "::ffff:192.0.2.8", "2001:db8::1"):
            self.assertTrue(access.permits(ip))
        for ip in ("192.0.2.9", "::ffff:192.0.2.9", "198.51.100.1", "invalid"):
            self.assertFalse(access.permits(ip))

    def test_v2_ipv4_ipv6_exact_layout(self):
        for src, dst, family, length in (("192.0.2.1", "198.51.100.1", 0x11, 12),
                                         ("2001:db8::1", "2001:db8::2", 0x21, 36)):
            header = mc_protocol.proxy_v2_header((src, 1234), (dst, 2345))
            self.assertEqual(header[:16], b"\r\n\r\n\x00\r\nQUIT\n" + bytes((0x21, family)) + struct.pack(">H", length))
            self.assertEqual(len(header), 16 + length)
            self.assertEqual(mc_protocol.read_proxy_v2(BytesSocket(header)), ((src, 1234), (dst, 2345)))

    def test_v2_rejects_unknown_commands_families_and_truncation(self):
        header = mc_protocol.proxy_v2_header(("192.0.2.1", 1), ("192.0.2.2", 2))
        for bad in (header[:12] + b"\x22" + header[13:], header[:13] + b"\x12" + header[14:],
                    header[:-1], b"bad" + header[3:]):
            with self.assertRaises(mc_protocol.ProtocolError):
                mc_protocol.read_proxy_v2(BytesSocket(bad))

    def test_hold_does_not_replay_before_plugin_replies(self):
        conn = mock.Mock()
        hello = mc_protocol.Hello(767, "h", 1, 2)
        attempt = mock.Mock(return_value=None)
        clock = mock.Mock(side_effect=[0, 0, 1, 1, 2, 2, 7])
        with mock.patch.object(mc_proxy.select, "select", return_value=([], [], [])):
            result = mc_proxy.hold(conn, hello, attempt, 10, clock=clock, keepalive=1)
        self.assertIsNone(result)
        self.assertEqual(attempt.call_count, 1)
        self.assertGreaterEqual(conn.sendall.call_count, 1)

    def test_hold_cancelled_without_opening_backend(self):
        halt = mock.Mock()
        halt.is_set.return_value = True
        attempt = mock.Mock()
        self.assertIsNone(mc_proxy.hold(mock.Mock(), mc_protocol.Hello(767, "h", 1, 2), attempt, 10, stop=halt))
        attempt.assert_not_called()
