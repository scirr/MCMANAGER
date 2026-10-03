"""
test_firewall.py — the old game-port rule survives while another registered
server still uses that port.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_firewall


class TestOldRule(unittest.TestCase):

    def _ensure(self, other):
        with mock.patch.object(mc_firewall, "remove_rule") as rm, \
             mock.patch.object(mc_firewall, "rule_exists", return_value=True), \
             mock.patch("mc_servers.find_port_conflict", return_value=other):
            mc_firewall.ensure_game_port_rule(25566, old_port=25565, name="a")
        return rm

    def test_removed_when_unused(self):
        self._ensure(None).assert_called_once_with("MCManager - Port 25565")

    def test_kept_when_another_server_uses_it(self):
        self._ensure("b").assert_not_called()


if __name__ == "__main__":
    unittest.main()
