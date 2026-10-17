"""
test_metrics.py — Prometheus exposition, TPS parsers, sampling cache, HTTP
endpoint (127.0.0.1, ephemeral port) and local-only listening.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_metrics

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def sample(name="survie", state="running", **extra):
    base = {"name": name, "state": state, "loader": "Paper", "version": "1.21.1",
            "players_online": 2, "players_max": 20, "players": ["a", "b"],
            "rss_bytes": 4294967296, "cpu_seconds": 123.45, "uptime_s": 3600,
            "tps": 19.98, "backup_ts": 1760000000.0}
    base.update(extra)
    return base


class TestTpsParsers(unittest.TestCase):

    def test_paper(self):
        self.assertEqual(mc_metrics.parse_tps("TPS from last 1m, 5m, 15m: 20.0, 19.5, 18.2"), 20.0)

    def test_paper_with_color_codes_and_star(self):
        text = "§6TPS from last 1m, 5m, 15m: §a*20.0§r, §a19.9§r, §e18.7"
        self.assertEqual(mc_metrics.parse_tps(text), 20.0)

    def test_purpur_lower_value(self):
        self.assertEqual(mc_metrics.parse_tps("§6TPS from last 1m, 5m, 15m: §e17.31, §a19.0, §a20.0"), 17.31)

    def test_neoforge_overall_wins(self):
        text = ("Overworld: Mean tick time: 12.345 ms. Mean TPS: 20.000\n"
                "The Nether: Mean tick time: 0.5 ms. Mean TPS: 20.000\n"
                "Overall: Mean tick time: 13.1 ms. Mean TPS: 19.500")
        self.assertEqual(mc_metrics.parse_tps(text), 19.5)

    def test_forge_dimension_lines_without_overall(self):
        text = ("Dim minecraft:the_nether (minecraft:the_nether): Mean tick time: 0.4 ms. Mean TPS: 20.000\n"
                "Dim minecraft:overworld (minecraft:overworld): Mean tick time: 61.2 ms. Mean TPS: 16.340")
        self.assertEqual(mc_metrics.parse_tps(text), 16.34)

    def test_neoforge_overworld_preferred_over_others(self):
        text = ("Overworld: Mean tick time: 12.0 ms. Mean TPS: 20.000\n"
                "The End: Mean tick time: 90.0 ms. Mean TPS: 11.100")
        self.assertEqual(mc_metrics.parse_tps(text), 20.0)

    def test_unknown_command_reply(self):
        self.assertIsNone(mc_metrics.parse_tps("Unknown or incomplete command, see below for error"))
        self.assertIsNone(mc_metrics.parse_tps(""))
        self.assertIsNone(mc_metrics.parse_tps(None))

    def test_command_per_loader(self):
        self.assertEqual(mc_metrics.tps_command("Paper"), "tps")
        self.assertEqual(mc_metrics.tps_command("purpur"), "tps")
        self.assertEqual(mc_metrics.tps_command("NeoForge"), "neoforge tps")
        self.assertEqual(mc_metrics.tps_command("Forge"), "forge tps")
        self.assertIsNone(mc_metrics.tps_command("Fabric"))
        self.assertIsNone(mc_metrics.tps_command("Vanilla"))
        self.assertIsNone(mc_metrics.tps_command(None))


class TestExposition(unittest.TestCase):

    def setUp(self):
        self.text = mc_metrics.exposition([sample(), sample("creatif", "sleeping", players_online=None,
                                                            players_max=None, rss_bytes=None, cpu_seconds=None,
                                                            uptime_s=None, tps=None, backup_ts=None)])

    def test_ends_with_newline_and_has_help_type_once_per_family(self):
        self.assertTrue(self.text.endswith("\n"))
        for family in ("mcm_server_up", "mcm_server_state", "mcm_jvm_cpu_seconds_total"):
            self.assertEqual(self.text.count(f"# HELP {family} "), 1)
            self.assertEqual(self.text.count(f"# TYPE {family} "), 1)

    def test_types(self):
        self.assertIn("# TYPE mcm_jvm_cpu_seconds_total counter", self.text)
        self.assertIn("# TYPE mcm_server_up gauge", self.text)

    def test_every_sample_line_is_valid_and_labelled(self):
        pattern = re.compile(r'^[a-zA-Z_:][a-zA-Z0-9_:]*\{server="[^"]*"(,[a-z_]+="[^"]*")*\} -?[0-9.e+]+$')
        seen = set()
        for line in self.text.splitlines():
            if line.startswith("#"):
                continue
            self.assertRegex(line, pattern)
            series = line.rsplit(" ", 1)[0]
            self.assertNotIn(series, seen, "duplicate series")
            seen.add(series)

    def test_state_is_one_hot(self):
        self.assertIn('mcm_server_state{server="survie",state="running"} 1', self.text)
        self.assertIn('mcm_server_state{server="survie",state="sleeping"} 0', self.text)
        self.assertIn('mcm_server_state{server="creatif",state="sleeping"} 1', self.text)
        ones = [l for l in self.text.splitlines() if l.startswith('mcm_server_state{server="creatif"') and l.endswith(" 1")]
        self.assertEqual(len(ones), 1)

    def test_values(self):
        self.assertIn('mcm_server_up{server="survie"} 1', self.text)
        self.assertIn('mcm_server_up{server="creatif"} 0', self.text)
        self.assertIn('mcm_players_online{server="survie"} 2', self.text)
        self.assertIn('mcm_jvm_rss_bytes{server="survie"} 4294967296', self.text)
        self.assertIn('mcm_jvm_cpu_seconds_total{server="survie"} 123.45', self.text)
        self.assertIn('mcm_tps{server="survie"} 19.98', self.text)
        self.assertIn('mcm_uptime_seconds{server="survie"} 3600', self.text)
        self.assertIn('mcm_backup_last_success_timestamp{server="survie"} 1760000000.0', self.text)

    def test_unavailable_metrics_are_absent(self):
        self.assertNotIn('mcm_players_online{server="creatif"}', self.text)
        self.assertNotIn('mcm_tps{server="creatif"}', self.text)
        self.assertNotIn('mcm_jvm_rss_bytes{server="creatif"}', self.text)

    def test_labels_are_escaped(self):
        text = mc_metrics.exposition([sample('we"ird\\na\nme')])
        self.assertIn('server="we\\"ird\\\\na\\nme"', text)
        self.assertEqual(len([l for l in text.splitlines() if l.startswith("mcm_server_up")]), 1)

    def test_no_servers_gives_empty_but_valid_text(self):
        self.assertEqual(mc_metrics.exposition([]), "\n")


class TestCollectorCache(unittest.TestCase):

    def test_sampled_once_within_ttl(self):
        calls = []
        clock = [1000.0]
        collector = mc_metrics.Collector(lambda n, c: calls.append(n) or sample(n), lambda: clock[0], ttl=10)
        collector.sample("a", {})
        clock[0] += 9
        collector.sample("a", {})
        self.assertEqual(calls, ["a"])
        clock[0] += 2
        collector.sample("a", {})
        self.assertEqual(calls, ["a", "a"])

    def test_unreadable_server_is_skipped(self):
        collector = mc_metrics.Collector(lambda n, c: sample(n))
        with tempfile.TemporaryDirectory() as good:
            with open(os.path.join(good, "config.json"), "w") as f:
                json.dump({}, f)
            bad = os.path.join(good, "missing")
            got = collector.samples({"ok": {"dossier_serveur": good}, "ko": {"dossier_serveur": bad}})
        self.assertEqual([s["name"] for s in got], ["ok"])


class TestSampleServer(unittest.TestCase):

    def test_running_server_collects_players_and_tps(self):
        replies = {"tps": (True, "TPS from last 1m, 5m, 15m: 19.5, 20.0, 20.0")}
        with mock.patch.object(mc_metrics.mc_api, "server_state", return_value="running"), \
             mock.patch.object(mc_metrics.mc_api, "_main_pid", return_value=4242), \
             mock.patch.object(mc_metrics.mc_api, "_uptime_seconds", return_value=77), \
             mock.patch.object(mc_metrics.mc_core, "proc_memory", return_value=(2048, 0)), \
             mock.patch.object(mc_metrics, "proc_cpu_seconds", return_value=9.5), \
             mock.patch.object(mc_metrics.mc_api, "query_players",
                               return_value=(True, {"online": 1, "max": 10, "players": ["x"]})), \
             mock.patch.object(mc_metrics.mc_api, "rcon_exec", side_effect=lambda c, cmd: replies[cmd]):
            s = mc_metrics.sample_server("srv", {"loader": "Paper", "mc_version": "1.21.1"})
        self.assertEqual((s["players_online"], s["players_max"], s["tps"]), (1, 10, 19.5))
        self.assertEqual((s["rss_bytes"], s["cpu_seconds"], s["uptime_s"]), (2048 * 1024, 9.5, 77))

    def test_fabric_has_no_tps_and_issues_no_command(self):
        with mock.patch.object(mc_metrics.mc_api, "server_state", return_value="running"), \
             mock.patch.object(mc_metrics.mc_api, "_main_pid", return_value=None), \
             mock.patch.object(mc_metrics.mc_api, "query_players",
                               return_value=(True, {"online": 0, "max": 5, "players": []})), \
             mock.patch.object(mc_metrics.mc_api, "rcon_exec") as rcon:
            s = mc_metrics.sample_server("srv", {"loader": "Fabric", "mc_version": "1.21.1"})
        rcon.assert_not_called()
        self.assertIsNone(s["tps"])

    def test_stopped_server_does_not_touch_rcon(self):
        with mock.patch.object(mc_metrics.mc_api, "server_state", return_value="stopped"), \
             mock.patch.object(mc_metrics.mc_api, "query_players") as players:
            s = mc_metrics.sample_server("srv", {"loader": "Paper"})
        players.assert_not_called()
        self.assertIsNone(s["players_online"])

    def test_cpu_seconds_from_proc_stat(self):
        stat = "1 (java) S 1 1 1 0 -1 4194560 0 0 0 0 150 50 0 0 20 0 30 0 1000 0 0\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=stat)), \
             mock.patch("os.sysconf", return_value=100):
            self.assertEqual(mc_metrics.proc_cpu_seconds(1), 2.0)

    def test_last_backup_timestamp_picks_newest_zip(self):
        with tempfile.TemporaryDirectory() as root:
            for day, name, t in (("2026-10-01", "backup_a.zip", 1000), ("2026-10-02", "backup_b.zip", 3000),
                                 ("2026-10-02", "notes.txt", 9000)):
                os.makedirs(os.path.join(root, day), exist_ok=True)
                path = os.path.join(root, day, name)
                open(path, "w").close()
                os.utime(path, (t, t))
            self.assertEqual(mc_metrics.last_backup_timestamp({"dossier_backup": root}), 3000)
            self.assertIsNone(mc_metrics.last_backup_timestamp({"dossier_backup": root + "/none"}))


class TestBind(unittest.TestCase):

    def test_parse(self):
        self.assertEqual(mc_metrics.parse_bind("127.0.0.1:9225"), ("127.0.0.1", 9225))
        self.assertEqual(mc_metrics.parse_bind("[::1]:80"), ("::1", 80))
        for bad in ("9225", "host", "1.2.3.4:99999", "", "a:b"):
            with self.assertRaises(ValueError):
                mc_metrics.parse_bind(bad)

    def test_locality(self):
        for host in ("127.0.0.1", "localhost", "::1", "127.5.5.5"):
            self.assertTrue(mc_metrics.is_local_host(host))
        for host in ("0.0.0.0", "", "192.168.1.5", "example.org", "::"):
            self.assertFalse(mc_metrics.is_local_host(host))

    def test_remote_refused_without_flag(self):
        with self.assertRaises(PermissionError):
            mc_metrics.make_server("0.0.0.0:0")
        with self.assertRaises(PermissionError):
            mc_metrics.make_server(":0")

    def test_remote_allowed_with_flag(self):
        server = mc_metrics.make_server("0.0.0.0:0", allow_remote=True)
        server.server_close()


class TestHttp(unittest.TestCase):

    def setUp(self):
        self.body = lambda: mc_metrics.exposition([sample()])
        self.server = mc_metrics.make_server("127.0.0.1:0", body=lambda: self.body())
        import threading
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5)

    def test_metrics_endpoint(self):
        with self.get("/metrics") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "text/plain; version=0.0.4; charset=utf-8")
            text = response.read().decode()
        self.assertIn('mcm_players_online{server="survie"} 2', text)
        print("\n--- /metrics (test output) ---\n" + text)

    def test_other_paths_are_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/")
        self.assertEqual(ctx.exception.code, 404)

    def test_rendering_failure_is_500_not_a_crash(self):
        def boom():
            raise RuntimeError("x")
        self.body = boom
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/metrics")
        self.assertEqual(ctx.exception.code, 500)
        self.body = lambda: "ok\n"
        with self.get("/metrics") as response:
            self.assertEqual(response.read(), b"ok\n")


class TestDaemonEndpoint(unittest.TestCase):

    def make_servers(self, root, **config):
        folder = os.path.join(root, "s")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "config.json"), "w") as f:
            json.dump(config, f)
        return {"s": {"dossier_serveur": folder}}

    def test_serves_only_while_the_key_is_set_and_follows_changes(self):
        made = []

        class Fake:
            def __init__(self, bind, remote):
                made.append((bind, remote))
                self.closed = False
            def serve_forever(self):
                pass
            def shutdown(self):
                pass
            def server_close(self):
                self.closed = True

        endpoint = mc_metrics.DaemonEndpoint(maker=Fake)
        with tempfile.TemporaryDirectory() as root:
            endpoint.sync(self.make_servers(root))
            self.assertEqual(made, [])
            servers = self.make_servers(root, metrics_bind="127.0.0.1:9300")
            endpoint.sync(servers)
            endpoint.sync(servers)
            self.assertEqual(made, [("127.0.0.1:9300", False)])
            endpoint.sync(self.make_servers(root, metrics_bind="127.0.0.1:9301", metrics_allow_remote=1))
            self.assertEqual(made[-1], ("127.0.0.1:9301", True))
            endpoint.sync(self.make_servers(root))
            self.assertIsNone(endpoint.server)

    def test_refused_bind_is_logged_once_not_retried(self):
        attempts = []

        def refuse(bind, remote):
            attempts.append(bind)
            raise PermissionError(bind)

        endpoint = mc_metrics.DaemonEndpoint(maker=refuse)
        with tempfile.TemporaryDirectory() as root:
            servers = self.make_servers(root, metrics_bind="0.0.0.0:9300")
            endpoint.sync(servers)
            endpoint.sync(servers)
        self.assertEqual(attempts, ["0.0.0.0:9300"])
        self.assertIsNone(endpoint.server)


class TestCli(unittest.TestCase):

    def run_mc(self, *args):
        env = dict(os.environ, MCMANAGER_DATA_DIR=tempfile.mkdtemp(), NO_COLOR="1")
        return subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), *args], capture_output=True,
                              text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)

    def test_remote_bind_refused_with_usage_code(self):
        result = self.run_mc("metrics", "serve", "--bind", "0.0.0.0:9225", "--json")
        self.assertEqual(result.returncode, 2)
        doc = json.loads(result.stdout)
        self.assertEqual((doc["schema"], doc["ok"], doc["code"]), (1, False, "metrics_remote_refused"))

    def test_malformed_bind_is_usage_error(self):
        result = self.run_mc("metrics", "serve", "--bind", "nonsense", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["code"], "metrics_bind_invalid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
