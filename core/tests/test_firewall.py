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
import platform_linux

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


NUMBERED = """Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere                   # SSH
[ 2] 25565/tcp                  ALLOW IN    Anywhere                   # Minecraft
[ 3] 25584/tcp                  ALLOW IN    Anywhere                   # MC Manager vanillaa
[ 4] 25570/tcp                  ALLOW IN    Anywhere
[ 8] 25584/tcp (v6)             ALLOW IN    Anywhere (v6)              # MC Manager vanillaa
[ 9] 25565/tcp (v6)             ALLOW IN    Anywhere (v6)              # Minecraft
[10] 25565/tcp                  ALLOW IN    Anywhere                   # MC Manager survie
[11] 25565/tcp (v6)             ALLOW IN    Anywhere (v6)              # MC Manager survie
"""


def _as(backend):
    return mock.patch.object(platform_linux, "firewall_name", return_value=backend)


def _done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


class TestUfwParsing(unittest.TestCase):

    def test_ports(self):
        self.assertTrue(platform_linux.parse_ufw_status(UFW, 25565))
        self.assertTrue(platform_linux.parse_ufw_status(UFW, 25600))      # no protocol = tcp+udp
        self.assertTrue(platform_linux.parse_ufw_status(UFW, 25705))      # range
        self.assertTrue(platform_linux.parse_ufw_status(UFW, 25900))      # LIMIT still allows
        self.assertFalse(platform_linux.parse_ufw_status(UFW, 25800))     # udp only
        self.assertFalse(platform_linux.parse_ufw_status(UFW, 25575))     # DENY
        self.assertFalse(platform_linux.parse_ufw_status(UFW, 25566))

    def test_inactive_is_unknown(self):
        self.assertIsNone(platform_linux.parse_ufw_status("Status: inactive\n", 25565))


class TestUfwRemoval(unittest.TestCase):

    def _remove(self, port, other_server=None, status=NUMBERED):
        calls = []

        def run(args, root=False):
            calls.append(args)
            return _done(status) if args == ["ufw", "status", "numbered"] else _done()
        with _as("ufw"), mock.patch.object(platform_linux, "_run", side_effect=run), \
             mock.patch("mc_servers.find_port_conflict", return_value=other_server):
            result = mc_firewall.remove_rule(port, "ufw", "vanillaa")
        return result, [c for c in calls if "delete" in c]

    def test_parse_picks_only_mc_manager_rules_in_descending_order(self):
        self.assertEqual(platform_linux.parse_ufw_numbered(NUMBERED, 25584), [8, 3])
        self.assertEqual(platform_linux.parse_ufw_numbered(NUMBERED, 25565), [11, 10])
        self.assertEqual(platform_linux.parse_ufw_numbered(NUMBERED, 25570), [])

    def test_manual_rule_on_the_port_survives(self):
        manual_only = NUMBERED.split("[10]")[0]
        result, deletes = self._remove(25565, status=manual_only)
        self.assertEqual((result, deletes), (False, []))

    def test_deletes_by_number_highest_first(self):
        result, deletes = self._remove(25565)
        self.assertTrue(result)
        self.assertEqual(deletes, [["ufw", "--force", "delete", "11"],
                                   ["ufw", "--force", "delete", "10"]])

    def test_port_still_used_by_another_server_is_kept(self):
        result, deletes = self._remove(25565, other_server="survie")
        self.assertEqual((result, deletes), (False, []))

    def test_unreadable_rules_delete_nothing(self):
        with _as("ufw"), mock.patch.object(platform_linux, "_run", return_value=None), \
             mock.patch("mc_servers.find_port_conflict", return_value=None):
            self.assertFalse(mc_firewall.remove_rule(25565, "ufw", "vanillaa"))


class TestBackends(unittest.TestCase):

    def test_detect_order(self):
        with mock.patch.object(platform_linux, "_ufw_enabled", return_value=True), \
             mock.patch.object(platform_linux, "_firewalld_running", return_value=True):
            self.assertEqual(mc_firewall.detect(), "ufw")
        with mock.patch.object(platform_linux, "_ufw_enabled", return_value=False), \
             mock.patch.object(platform_linux, "_firewalld_running", return_value=True):
            self.assertEqual(mc_firewall.detect(), "firewalld")
        with mock.patch.object(platform_linux, "_ufw_enabled", return_value=False), \
             mock.patch.object(platform_linux, "_firewalld_running", return_value=False):
            self.assertIsNone(mc_firewall.detect())

    def test_ufw_rules_unreadable_without_root(self):
        with _as("ufw"), mock.patch.object(platform_linux, "_run", return_value=_done("ERROR: You need to be root", 1)):
            self.assertIsNone(mc_firewall.port_open(25565, "ufw"))

    def test_ufw_add_with_comment_and_port_change(self):
        calls = []

        def run(args, root=False):
            calls.append(args)
            if args == ["ufw", "status", "numbered"]:
                return _done(NUMBERED)
            if args[:2] == ["ufw", "status"]:
                return _done("Status: active\n")
            return _done()
        with mock.patch.object(platform_linux, "firewall_name", return_value="ufw"), \
             mock.patch.object(platform_linux, "_run", side_effect=run), \
             mock.patch("mc_servers.find_port_conflict", return_value=None):
            self.assertEqual(mc_firewall.ensure_game_port_rule(25566, old_port=25565, name="survie"), (True, None))
        self.assertNotIn(["ufw", "delete", "allow", "25565/tcp"], calls)
        self.assertIn(["ufw", "--force", "delete", "11"], calls)
        self.assertIn(["ufw", "allow", "25566/tcp", "comment", "MC Manager survie"], calls)

    def test_already_open_adds_nothing(self):
        calls = []

        def run(args, root=False):
            calls.append(args)
            return _done(UFW)
        with mock.patch.object(platform_linux, "firewall_name", return_value="ufw"), \
             mock.patch.object(platform_linux, "_run", side_effect=run):
            self.assertEqual(mc_firewall.ensure_game_port_rule(25565, name="survie"), (True, None))
        self.assertEqual(calls, [["ufw", "status"]])

    def test_failure_returns_manual_command(self):
        with mock.patch.object(platform_linux, "firewall_name", return_value="ufw"), \
             mock.patch.object(platform_linux, "_run", return_value=None):
            ok, manual = mc_firewall.ensure_game_port_rule(25565, name="survie")
        self.assertFalse(ok)
        self.assertEqual(manual, "sudo ufw allow 25565/tcp comment 'MC Manager survie'")
        with _as("firewalld"):
            self.assertIn("firewall-cmd", mc_firewall.manual_command(25565, backend="firewalld"))

    def test_firewalld_keeps_port_used_by_another_server(self):
        calls = []
        with _as("firewalld"), mock.patch.object(platform_linux, "_run", side_effect=lambda a, root=False: calls.append(a) or _done()), \
             mock.patch("mc_servers.find_port_conflict", return_value="survie"):
            self.assertFalse(mc_firewall.remove_rule(25565, "firewalld", "vanillaa"))
        self.assertEqual(calls, [])
        with _as("firewalld"), mock.patch.object(platform_linux, "_run", side_effect=lambda a, root=False: calls.append(a) or _done()), \
             mock.patch("mc_servers.find_port_conflict", return_value=None):
            self.assertTrue(mc_firewall.remove_rule(25565, "firewalld", "vanillaa"))
        self.assertIn(["firewall-cmd", "--permanent", "--remove-port=25565/tcp"], calls)

    def test_firewalld_query(self):
        with _as("firewalld"), mock.patch.object(platform_linux, "_run", return_value=_done("yes\n")):
            self.assertTrue(mc_firewall.port_open(25565, "firewalld"))
        with _as("firewalld"), mock.patch.object(platform_linux, "_run", return_value=_done("no\n", 1)):
            self.assertFalse(mc_firewall.port_open(25565, "firewalld"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
