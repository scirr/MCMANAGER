import fnmatch
import json
import os
import unittest
from unittest import mock

import winfix
import plat_win_common as common
import plat_win_firewall as fw
import plat_win_net as net
import plat_win_process as proc
import plat_win_service as svc
import platform_windows as pw

REAL = os.path.join(winfix.HERE, "fixtures", "windows", "real_fr")


def raw(name):
    with open(os.path.join(REAL, name), "rb") as f:
        return f.read()


def text(name, encoding="oem"):
    return common.decode_output(raw(name), encoding)


class TestDecode(unittest.TestCase):
    def test_utf8_first_then_cp850(self):
        self.assertEqual(common.decode_output("é".encode("utf-8")), "é")
        self.assertEqual(common.decode_output("é".encode("cp850")), "é")
        self.assertEqual(common.decode_output(b"\xff"), "\xa0")

    def test_never_raises(self):
        for data in (b"", None, b"\x81\xff\x00\xc3", bytes(range(256))):
            self.assertIsInstance(common.decode_output(data), str)
            self.assertIsInstance(common.decode_output(data, "no-such-codec"), str)

    def test_both_netsh_variants_decode_equal(self):
        a = text("netsh_rule_mcmanager_cp850.txt")
        b = text("netsh_rule_mcmanager_utf8.txt")
        self.assertEqual(a, b)
        self.assertIn("Nom de la règle\u00a0:", a)


class TestNetstatReal(unittest.TestCase):
    def test_tcp(self):
        rows = net.parse_netstat(text("netstat_tcp_cp850.txt"))
        self.assertEqual([(r["port"], r["pid"]) for r in rows if r["listening"]],
                         [(135, 1796), (445, 4), (23130, 6176), (27015, 16140), (49763, 15984)])
        self.assertTrue(all(r["proto"] == "tcp" for r in rows))

    def test_udp(self):
        rows = net.parse_netstat(text("netstat_udp_cp850.txt"))
        self.assertEqual([(r["address"], r["port"], r["pid"]) for r in rows],
                         [("0.0.0.0", 123, 18344), ("0.0.0.0", 49161, 15548),
                          ("127.0.0.1", 1900, 9116), ("127.0.0.1", 49170, 16140)])

    def test_netstat_fallback_through_run(self):
        with mock.patch.object(net, "run_powershell", return_value=(1, "", "")), \
                mock.patch.object(net, "run", return_value=(0, text("netstat_tcp_cp850.txt"), "")):
            self.assertEqual(net.listeners(445)[0]["pid"], 4)
            self.assertTrue(net.listens_on_all_interfaces(445))
            self.assertFalse(net.listens_on_all_interfaces(27015))

    def test_powershell_json(self):
        rows = net.parse_net_json(text("nettcp_listen_ps51.json", "utf-8"))
        self.assertEqual([(r["address"], r["port"], r["pid"]) for r in rows],
                         [("::", 49769, 4), ("::", 23132, 6176)])
        rows = net.parse_net_json(text("netudp_endpoint_ps51.json", "utf-8"))
        self.assertEqual([r["port"] for r in rows], [63529, 1900])


class TestProcessReal(unittest.TestCase):
    def rows(self):
        return json.loads(text("cim_process_ps51.json", "utf-8"))

    def test_creation_date_forms(self):
        row = self.rows()[0]
        self.assertAlmostEqual(proc._parse_start(row["CreationDate"]), 1792299900.406, places=3)
        iso = proc._parse_start("2026-10-18T06:25:00.406+00:00")
        self.assertAlmostEqual(iso, 1792304700.406, places=3)
        self.assertAlmostEqual(proc._parse_start("2026-10-18T06:25:00Z"), 1792304700.0, places=3)
        self.assertIsNone(proc._parse_start("hier"))

    def test_uptime_from_creation_date(self):
        row = self.rows()[0]
        with mock.patch.object(proc, "_cim_info", return_value=row), \
                mock.patch.object(proc, "_now", return_value=1792299900.406 + 120):
            self.assertAlmostEqual(proc.process_uptime(9100), 120.0, places=2)

    def test_memory_and_cpu(self):
        row = self.rows()[0]
        with mock.patch.object(proc, "_cim_info", return_value=row):
            self.assertEqual(proc.process_memory(9100), (243154944 // 1024, None))
            self.assertAlmostEqual(proc.process_cpu_seconds(9100), (30312500 + 25156250) / 1e7)

    def test_tasklist_csv(self):
        out = text("tasklist_explorer_cp850.csv")
        self.assertEqual(proc.parse_tasklist_csv(out), [("explorer.exe", 9100)])
        self.assertEqual(proc.parse_tasklist_memory(out), [("explorer.exe", 9100, 237676)])

    def test_tasklist_narrow_nbsp(self):
        out = '"java.exe","12","Console","1","1\u202f237\u202f676 Ko"\n'
        self.assertEqual(proc.parse_tasklist_memory(out), [("java.exe", 12, 1237676)])

    def test_tasklist_alive(self):
        with mock.patch.object(proc, "_alive_ctypes", return_value=None), \
                mock.patch.object(proc, "run", return_value=(0, text("tasklist_explorer_cp850.csv"), "")):
            self.assertTrue(proc.process_alive(9100))
            self.assertFalse(proc.process_alive(1))


class TestServiceReal(unittest.TestCase):
    def test_installed_daemon_running_via_sc(self):
        with mock.patch.object(svc.common, "run_powershell", return_value=(1, "", "")), \
                mock.patch.object(svc.common, "run", return_value=(0, text("sc_query_mcmanager_cp850.txt"), "")):
            self.assertEqual(svc.service_state(), "running")
            self.assertTrue(svc.service_installed())
            self.assertTrue(svc.service_running())

    def test_installed_daemon_running_via_powershell(self):
        out = text("service_dnscache_ps51.json", "utf-8").replace("Dnscache", svc.SERVICE_NAME)
        with mock.patch.object(svc.common, "run_powershell", return_value=(0, out, "")):
            self.assertTrue(svc.service_installed())
            self.assertTrue(svc.service_running())

    def test_numeric_enumerations(self):
        data = text("service_dnscache_ps51.json", "utf-8")
        self.assertEqual(svc.parse_powershell_state(data, "Dnscache"), "running")
        self.assertEqual(json.loads(data)["StartType"], 2)
        self.assertEqual(svc.parse_start_type(2), "automatic")
        self.assertEqual(svc.parse_start_type(3), "manual")
        self.assertEqual(svc.parse_start_type(4), "disabled")
        self.assertEqual(svc.parse_start_type("Automatic"), "automatic")
        self.assertEqual(svc.parse_start_type("Disabled"), "disabled")

    def test_status_numbers_and_words(self):
        for value, state in ((1, "stopped"), (2, "pending"), (3, "pending"), (4, "running"),
                             ("Running", "running"), ("StartPending", "pending"), ("4", "running")):
            doc = json.dumps({"Name": svc.SERVICE_NAME, "Status": value})
            self.assertEqual(svc.parse_powershell_state(doc), state, value)

    def test_sc_query_real(self):
        self.assertEqual(svc.parse_sc_query(text("sc_query_mcmanager_cp850.txt")), "running")


class TestFirewallReal(unittest.TestCase):
    def test_ps51_numeric_enumerations(self):
        rules = fw.parse_powershell_rules(text("firewall_rules_ps51.json", "utf-8"))
        self.assertEqual(len(rules), 2)
        for r in rules:
            self.assertTrue(r["enabled"] and r["inbound"] and r["allow"])
        doc = json.dumps([{"DisplayName": "x", "Enabled": 2, "Direction": 2, "Action": 4}])
        r = fw.parse_powershell_rules(doc)[0]
        self.assertFalse(r["enabled"] or r["inbound"] or r["allow"])

    def test_ps7_text_enumerations(self):
        doc = json.dumps([{"DisplayName": "x", "Enabled": "True", "Direction": "Inbound",
                           "Action": "Allow", "Protocol": "TCP", "LocalPort": "25565"}])
        r = fw.parse_powershell_rules(doc)[0]
        self.assertTrue(r["enabled"] and r["inbound"] and r["allow"])
        doc = json.dumps([{"Enabled": "False", "Direction": "Outbound", "Action": "Block"}])
        r = fw.parse_powershell_rules(doc)[0]
        self.assertFalse(r["enabled"] or r["inbound"] or r["allow"])

    def test_netsh_variants(self):
        for suffix in ("cp850", "utf8"):
            rules = fw.parse_netsh_rules(text(f"netsh_rule_mcmanager_{suffix}.txt"))
            self.assertEqual(len(rules), 1)
            r = rules[0]
            self.assertEqual(r["name"], "MCManager - Port 25565")
            self.assertTrue(r["enabled"] and r["inbound"] and r["allow"])
            self.assertEqual((r["proto"], r["ports"]), ("tcp", ["25565"]))
            many = fw.parse_netsh_rules(text(f"netsh_rules_inbound_{suffix}.txt"))
            self.assertEqual([m["name"] for m in many], ["Example\u00a0Browser (mDNS-In)", "Example App"])
            self.assertEqual(many[0]["ports"], ["5353"])
            self.assertEqual(many[1]["ports"], ["Tout"])

    def test_netsh_block_and_outbound(self):
        body = text("netsh_rule_mcmanager_utf8.txt").replace("Autoriser", "Bloquer").replace("Actif", "Sortant")
        r = fw.parse_netsh_rules(body)[0]
        self.assertFalse(r["allow"])
        self.assertFalse(r["inbound"])

    def test_existing_install_is_ours_and_open(self):
        self.assertTrue(fw.is_ours("MCManager - Port 25565"))
        self.assertEqual(fw.parse_rule_name("MCManager - Port 25565"), ("MCManager", 25565, "tcp"))
        for variant in ("cp850", "utf8"):
            listing = text(f"netsh_rule_mcmanager_{variant}.txt")
            with mock.patch.object(fw.common, "run_powershell", return_value=(1, "", "boom")), \
                    mock.patch.object(fw.common, "run", return_value=(0, listing, "")):
                self.assertIs(fw.firewall_port_open(25565), True)
                ours = fw.list_rules(only_ours=True)
                self.assertEqual([r["name"] for r in ours], ["MCManager - Port 25565"])
                self.assertTrue(all(fw.is_ours(r["name"]) for r in ours))

    def test_other_port_not_open_without_catch_all(self):
        listing = text("netsh_rule_mcmanager_utf8.txt")
        with mock.patch.object(fw.common, "run_powershell", return_value=(1, "", "")), \
                mock.patch.object(fw.common, "run", return_value=(0, listing, "")):
            self.assertIs(fw.firewall_port_open(25566), False)
            self.assertIs(fw.firewall_port_open(25565, "udp"), False)


class TestJavaPaths(unittest.TestCase):
    JAVA = r"C:\Program Files\Eclipse Adoptium\jdk-21.0.10.7-hotspot\bin\java.exe"

    def matches(self, pattern, path):
        pp, tp = pattern.split("\\"), path.split("\\")
        return len(pp) == len(tp) and all(fnmatch.fnmatchcase(t, p) for p, t in zip(pp, tp))

    def test_finds_temurin(self):
        with mock.patch.dict(os.environ, {"ProgramFiles": r"C:\Program Files"}, clear=True):
            patterns = pw.java_search_paths()
        self.assertTrue(any(self.matches(p, self.JAVA) for p in patterns))
        self.assertTrue(any(fnmatch.fnmatchcase(self.JAVA, p) for p in patterns))
