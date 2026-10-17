import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plat_win_firewall as fw

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "windows")
OURS = "ps_fw_rules_list_en.json"


def fx(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return "".join(line for line in f if not line.startswith("##"))


class Fake:
    def __init__(self, listing="", list_rc=0, ps_rc=0, ps_err="", netsh=None):
        self.listing, self.list_rc, self.ps_rc, self.ps_err = listing, list_rc, ps_rc, ps_err
        self.netsh = netsh or (lambda cmd: (0, "", ""))
        self.scripts, self.cmds = [], []

    def ps(self, script, timeout=20):
        self.scripts.append(script)
        if "Get-NetFirewallRule" in script:
            return self.list_rc, self.listing, ""
        return self.ps_rc, "", self.ps_err

    def run(self, cmd, timeout=20, encoding="oem"):
        self.cmds.append(cmd)
        return self.netsh(cmd)

    def __enter__(self):
        self.ps_patch = mock.patch.object(fw.common, "run_powershell", self.ps)
        self.run_patch = mock.patch.object(fw.common, "run", self.run)
        self.ps_patch.start()
        self.run_patch.start()
        return self

    def __exit__(self, *a):
        self.ps_patch.stop()
        self.run_patch.stop()


class TestNames(unittest.TestCase):
    def test_rule_name(self):
        self.assertEqual(fw.rule_name("Survie", 25565, "TCP"), "MC Manager Survie 25565/tcp")

    def test_label_with_spaces_accents_quotes(self):
        name = fw.rule_name('Créatif "été" 100%', 25566, "tcp")
        self.assertEqual(name, "MC Manager Créatif _été_ 100_ 25566/tcp")
        self.assertEqual(fw.parse_rule_name(name)[1:], (25566, "tcp"))

    def test_only_prefixed_names_are_ours(self):
        self.assertTrue(fw.is_ours("MC Manager a b 1/udp"))
        self.assertFalse(fw.is_ours("MCManager - Port 25565"))
        self.assertFalse(fw.is_ours("Minecraft 25565/tcp"))
        self.assertFalse(fw.is_ours("MC Manager sans port"))

    def test_manual_command(self):
        self.assertEqual(fw.firewall_manual_command(25565, "tcp", "Mon Serveur"),
                         'netsh advfirewall firewall add rule name="MC Manager Mon Serveur 25565/tcp" '
                         "dir=in action=allow protocol=TCP localport=25565")

    def test_firewall_name(self):
        with mock.patch.object(fw.shutil, "which", return_value=None):
            self.assertIsNone(fw.firewall_name())
        with mock.patch.object(fw.shutil, "which", return_value="C:\\Windows\\netsh.exe"):
            self.assertEqual(fw.firewall_name(), "netsh")


class TestParsing(unittest.TestCase):
    def test_list(self):
        rules = fw.parse_powershell_rules(fx(OURS))
        self.assertEqual([r["name"] for r in rules],
                         ["MC Manager Survie 25565/tcp", "MC Manager Créatif été 24454/udp"])
        self.assertEqual(rules[0]["ports"], ["25565"])
        self.assertTrue(rules[0]["inbound"] and rules[0]["allow"] and rules[0]["enabled"])

    def test_bare_object(self):
        rules = fw.parse_powershell_rules(fx("ps_fw_rules_single_object.json"))
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["ports"], ["25565"])

    def test_empty_and_null(self):
        self.assertEqual(fw.parse_powershell_rules(""), [])
        self.assertEqual(fw.parse_powershell_rules("null"), [])
        self.assertEqual(fw.parse_powershell_rules("[]"), [])

    def test_netsh_en(self):
        rules = fw.parse_netsh_rules(fx("netsh_show_all_en.txt"))
        self.assertEqual([r["name"] for r in rules],
                         ["MC Manager Survie 25565/tcp", "Core Networking - Echo", "Bloque TCP 25570"])
        self.assertEqual(rules[0]["ports"], ["25565"])
        self.assertTrue(rules[0]["allow"])
        self.assertFalse(rules[2]["allow"])
        self.assertEqual(rules[1]["proto"], "icmpv4")

    def test_netsh_fr_structure_not_labels(self):
        rules = fw.parse_netsh_rules(fx("netsh_show_all_fr.txt"))
        self.assertEqual([r["name"] for r in rules], ["MC Manager Créatif 25566/tcp", "Règle désactivée"])
        self.assertTrue(rules[0]["enabled"] and rules[0]["allow"])
        self.assertFalse(rules[1]["enabled"])
        self.assertEqual(rules[0]["ports"], ["25566"])

    def test_netsh_none(self):
        self.assertEqual(fw.parse_netsh_rules(fx("netsh_none_fr.txt")), [])


class TestPortOpen(unittest.TestCase):
    def test_matches_manual_range(self):
        with Fake(fx("ps_fw_rules_allowing.json")):
            self.assertTrue(fw.firewall_port_open(30050, "tcp"))
            self.assertFalse(fw.firewall_port_open(30101, "tcp"))

    def test_any_port_udp_does_not_open_tcp(self):
        with Fake(fx("ps_fw_rules_allowing.json")):
            self.assertTrue(fw.firewall_port_open(1234, "udp"))
            self.assertFalse(fw.firewall_port_open(1234, "tcp"))

    def test_disabled_rule_does_not_count(self):
        with Fake(fx("ps_fw_rules_allowing.json")):
            self.assertFalse(fw.firewall_port_open(40000, "tcp"))

    def test_no_rule_at_all(self):
        with Fake("[]"):
            self.assertFalse(fw.firewall_port_open(25565))

    def test_single_object(self):
        with Fake(fx("ps_fw_rules_single_object.json")):
            self.assertTrue(fw.firewall_port_open(25565))

    def test_fallback_to_netsh_fr(self):
        with Fake(list_rc=1, netsh=lambda cmd: (0, fx("netsh_show_all_fr.txt"), "")) as f:
            self.assertTrue(fw.firewall_port_open(25566))
            self.assertFalse(fw.firewall_port_open(26000))
            self.assertFalse(fw.firewall_port_open(25570))
        self.assertEqual(f.cmds[0][:4], ["netsh", "advfirewall", "firewall", "show"])

    def test_netsh_blocking_rule_is_not_open(self):
        with Fake(list_rc=1, netsh=lambda cmd: (0, fx("netsh_show_all_en.txt"), "")):
            self.assertFalse(fw.firewall_port_open(25570))
            self.assertTrue(fw.firewall_port_open(25565))

    def test_unreadable(self):
        with Fake(list_rc=1, netsh=lambda cmd: (127, "", "")):
            self.assertIsNone(fw.firewall_port_open(25565))
        with Fake(list_rc=5, netsh=lambda cmd: (127, "", "")):
            self.assertIsNone(fw.firewall_port_open(25565))


class TestAdd(unittest.TestCase):
    def test_creates_rule(self):
        with Fake("[]") as f:
            self.assertEqual(fw.firewall_add(25565, "tcp", "Mon Serveur"), ("ok", ""))
        script = f.scripts[-1]
        self.assertIn("New-NetFirewallRule", script)
        self.assertIn("-DisplayName 'MC Manager Mon Serveur 25565/tcp'", script)
        self.assertIn("-Protocol TCP -LocalPort 25565", script)

    def test_idempotent(self):
        with Fake(fx(OURS)) as f:
            self.assertTrue(fw.firewall_allow(25565, "tcp", "Survie")[0])
        self.assertFalse(any("New-NetFirewallRule" in s for s in f.scripts))

    def test_quote_in_label_is_doubled(self):
        with Fake("[]") as f:
            fw.firewall_add(25565, "tcp", "L'ami")
        self.assertIn("'MC Manager L''ami 25565/tcp'", f.scripts[-1])

    def test_denied_gives_exact_admin_command(self):
        with Fake("[]", ps_rc=5, ps_err=fx("ps_denied_fr.txt")):
            code, detail = fw.firewall_add(25565, "tcp", "Survie")
        self.assertEqual(code, "no_permission")
        self.assertEqual(detail, fw.firewall_manual_command(25565, "tcp", "Survie"))

    def test_powershell_error_falls_back_to_netsh(self):
        with Fake("[]", ps_rc=1) as f:
            self.assertEqual(fw.firewall_add(25565, "udp", "Survie"), ("ok", ""))
        self.assertEqual(f.cmds[-1], ["netsh", "advfirewall", "firewall", "add", "rule",
                                      "name=MC Manager Survie 25565/udp", "dir=in", "action=allow",
                                      "protocol=UDP", "localport=25565"])

    def test_netsh_failure_not_elevated(self):
        with Fake("[]", ps_rc=1, netsh=lambda cmd: (1, "", "")), \
                mock.patch.object(fw.files, "is_elevated", return_value=False):
            self.assertEqual(fw.firewall_add(25565, "tcp", "S")[0], "no_permission")

    def test_netsh_failure_elevated_is_error(self):
        with Fake("[]", ps_rc=1, netsh=lambda cmd: (1, "boom", "")), \
                mock.patch.object(fw.files, "is_elevated", return_value=True):
            self.assertEqual(fw.firewall_add(25565, "tcp", "S"), ("error", "boom"))


class TestRemove(unittest.TestCase):
    def never(self, port, label):
        return False

    def test_removes_only_matching_prefixed_rule(self):
        with Fake(fx(OURS)) as f:
            self.assertTrue(fw.firewall_remove(25565, "tcp", "Survie", in_use_by_other=self.never))
        removals = [s for s in f.scripts if "Remove-NetFirewallRule" in s]
        self.assertEqual(len(removals), 1)
        self.assertIn("'MC Manager Survie 25565/tcp'", removals[0])

    def test_wrong_protocol_untouched(self):
        with Fake(fx(OURS)) as f:
            self.assertFalse(fw.firewall_remove(25565, "udp", "Survie", in_use_by_other=self.never))
        self.assertFalse(any("Remove-NetFirewallRule" in s for s in f.scripts))

    def test_rule_used_by_other_server_kept(self):
        with Fake(fx(OURS)) as f:
            self.assertFalse(fw.firewall_remove(25565, "tcp", "Survie", in_use_by_other=lambda p, l: True))
        self.assertEqual(f.scripts, [])

    def test_manual_rule_never_listed_never_removed(self):
        listing = ('[{"Name":"m","DisplayName":"Minecraft 25565/tcp","Enabled":"True","Direction":"Inbound",'
                   '"Action":"Allow","Protocol":"TCP","LocalPort":["25565"]}]')
        with Fake(listing) as f:
            self.assertFalse(fw.firewall_remove(25565, "tcp", "Survie", in_use_by_other=self.never))
        self.assertFalse(any("Remove-NetFirewallRule" in s for s in f.scripts))

    def test_absent_rule(self):
        with Fake(""):
            self.assertFalse(fw.firewall_remove(25565, "tcp", "S", in_use_by_other=self.never))

    def test_netsh_fallback_deletes_by_exact_name(self):
        def netsh(cmd):
            if cmd[3] == "show":
                return 0, fx("netsh_show_all_fr.txt"), ""
            return 0, "", ""

        with Fake(list_rc=1, ps_rc=1, netsh=netsh) as f:
            self.assertTrue(fw.firewall_remove(25566, "tcp", "Créatif", in_use_by_other=self.never))
        self.assertEqual(f.cmds[-1], ["netsh", "advfirewall", "firewall", "delete", "rule",
                                      "name=MC Manager Créatif 25566/tcp"])

    def test_default_guard_uses_registry(self):
        fake_mod = mock.Mock()
        fake_mod.find_port_conflict.return_value = "autre"
        with mock.patch.dict(sys.modules, {"mc_servers": fake_mod}):
            self.assertTrue(fw._used_by_other(25565, "x"))
        fake_mod.find_port_conflict.return_value = None
        with mock.patch.dict(sys.modules, {"mc_servers": fake_mod}):
            self.assertFalse(fw._used_by_other(25565, "x"))


if __name__ == "__main__":
    unittest.main()
