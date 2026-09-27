"""
test_firewall.py — ufw / firewalld detection and rules (2.7.0).
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_firewall

UFW = """Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
25565/tcp                  ALLOW       Anywhere                   # MC Manager survie
25600                      ALLOW       Anywhere
25700:25710/tcp            ALLOW       Anywhere
25800/udp                  ALLOW       Anywhere
25900/tcp                  LIMIT       Anywhere
25565/tcp (v6)             ALLOW       Anywhere (v6)              # MC Manager survie
25575/tcp                  DENY        Anywhere
"""


def _done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


class TestUfwParsing(unittest.TestCase):

    def test_ports(self):
        self.assertTrue(mc_firewall.parse_ufw_status(UFW, 25565))
        self.assertTrue(mc_firewall.parse_ufw_status(UFW, 25600))      # no protocol = tcp+udp
        self.assertTrue(mc_firewall.parse_ufw_status(UFW, 25705))      # range
        self.assertTrue(mc_firewall.parse_ufw_status(UFW, 25900))      # LIMIT still allows
        self.assertFalse(mc_firewall.parse_ufw_status(UFW, 25800))     # udp only
        self.assertFalse(mc_firewall.parse_ufw_status(UFW, 25575))     # DENY
        self.assertFalse(mc_firewall.parse_ufw_status(UFW, 25566))

    def test_inactive_is_unknown(self):
        self.assertIsNone(mc_firewall.parse_ufw_status("Status: inactive\n", 25565))


class TestBackends(unittest.TestCase):

    def test_detect_order(self):
        with mock.patch.object(mc_firewall, "_ufw_enabled", return_value=True), \
             mock.patch.object(mc_firewall, "_firewalld_running", return_value=True):
            self.assertEqual(mc_firewall.detect(), "ufw")
        with mock.patch.object(mc_firewall, "_ufw_enabled", return_value=False), \
             mock.patch.object(mc_firewall, "_firewalld_running", return_value=True):
            self.assertEqual(mc_firewall.detect(), "firewalld")
        with mock.patch.object(mc_firewall, "_ufw_enabled", return_value=False), \
             mock.patch.object(mc_firewall, "_firewalld_running", return_value=False):
            self.assertIsNone(mc_firewall.detect())

    def test_ufw_rules_unreadable_without_root(self):
        with mock.patch.object(mc_firewall, "_run", return_value=_done("ERROR: You need to be root", 1)):
            self.assertIsNone(mc_firewall.port_open(25565, "ufw"))

    def test_ufw_add_with_comment_and_port_change(self):
        calls = []

        def run(args, root=False):
            calls.append(args)
            if args[:2] == ["ufw", "status"]:
                return _done("Status: active\n")
            return _done()
        with mock.patch.object(mc_firewall, "detect", return_value="ufw"), \
             mock.patch.object(mc_firewall, "_run", side_effect=run):
            self.assertEqual(mc_firewall.ensure_game_port_rule(25566, old_port=25565, name="survie"), (True, None))
        self.assertIn(["ufw", "delete", "allow", "25565/tcp"], calls)
        self.assertIn(["ufw", "allow", "25566/tcp", "comment", "MC Manager survie"], calls)

    def test_already_open_adds_nothing(self):
        calls = []

        def run(args, root=False):
            calls.append(args)
            return _done(UFW)
        with mock.patch.object(mc_firewall, "detect", return_value="ufw"), \
             mock.patch.object(mc_firewall, "_run", side_effect=run):
            self.assertEqual(mc_firewall.ensure_game_port_rule(25565, name="survie"), (True, None))
        self.assertEqual(calls, [["ufw", "status"]])

    def test_failure_returns_manual_command(self):
        with mock.patch.object(mc_firewall, "detect", return_value="ufw"), \
             mock.patch.object(mc_firewall, "_run", return_value=None):
            ok, manual = mc_firewall.ensure_game_port_rule(25565, name="survie")
        self.assertFalse(ok)
        self.assertEqual(manual, "sudo ufw allow 25565/tcp comment 'MC Manager survie'")
        self.assertIn("firewall-cmd", mc_firewall.manual_command(25565, backend="firewalld"))

    def test_firewalld_query(self):
        with mock.patch.object(mc_firewall, "_run", return_value=_done("yes\n")):
            self.assertTrue(mc_firewall.port_open(25565, "firewalld"))
        with mock.patch.object(mc_firewall, "_run", return_value=_done("no\n", 1)):
            self.assertFalse(mc_firewall.port_open(25565, "firewalld"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
