"""
test_statuspage.py — document content, privacy, HTML validity, atomic
writing, publisher cadence and the enable/disable API.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_api
import mc_metrics
import mc_statuspage

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def sample(**extra):
    base = {"name": "survie", "state": "running", "loader": "Paper", "version": "1.21.1",
            "players_online": 2, "players_max": 20, "players": ["Steve", "Alex"],
            "rss_bytes": 1, "cpu_seconds": 1.0, "uptime_s": 10, "tps": 20.0, "backup_ts": None}
    base.update(extra)
    return base


def read(path):
    with open(path) as f:
        return f.read()


class Checker(HTMLParser):
    VOID = {"meta", "link", "br", "img", "hr", "input"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.tags = [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(tag)


def make_config(folder, motd="A §6Fancy§r server", **extra):
    with open(os.path.join(folder, "server.properties"), "w") as f:
        f.write(f"motd={motd}\nmax-players=30\nrcon.password=hunter2\nserver-ip=10.1.2.3\nserver-port=25565\n")
    config = {"dossier_serveur": folder, "nom_serveur": "Survie", "mcrcon_pass": "hunter2",
              "rcon_port": 25575, "domaine": "play.example.org"}
    config.update(extra)
    return config


class TestDocument(unittest.TestCase):

    def test_motd_loses_formatting_and_decodes_escapes(self):
        self.assertEqual(mc_statuspage.clean_motd("\\u00a76Hello\\u00a7r  world\\nline2"), "Hello world line2")
        self.assertEqual(mc_statuspage.clean_motd("§aGreen §lBold"), "Green Bold")
        self.assertEqual(mc_statuspage.clean_motd(None), "")

    def test_document_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = mc_statuspage.build_document(make_config(folder), sample(), now=1760000000)
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(doc["name"], "Survie")
        self.assertEqual((doc["state"], doc["online"]), ("running", True))
        self.assertEqual(doc["players"], {"online": 2, "max": 20})
        self.assertEqual(doc["motd"], "A Fancy server")
        self.assertEqual(doc["version"], "1.21.1")
        self.assertEqual(doc["updated"], "2025-10-09T08:53:20Z")

    def test_offline_uses_max_players_property_and_zero_online(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = mc_statuspage.build_document(
                make_config(folder), sample(state="stopped", players_online=None, players_max=None, players=[]))
        self.assertEqual((doc["online"], doc["players"]), (False, {"online": 0, "max": 30}))

    def test_no_secret_address_or_player_name_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = mc_statuspage.build_document(make_config(folder), sample())
        blob = json.dumps(doc) + mc_statuspage.render_html(doc)
        for forbidden in ("hunter2", "10.1.2.3", "25575", "25565", "play.example.org", "Steve", "Alex"):
            self.assertNotIn(forbidden, blob)
        self.assertNotIn("names", doc["players"])

    def test_names_only_with_show_players(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = mc_statuspage.build_document(make_config(folder), sample(), show_players=True)
        self.assertEqual(doc["players"]["names"], ["Steve", "Alex"])
        page = mc_statuspage.render_html(doc)
        self.assertIn("Steve, Alex", page)
        self.assertNotIn("hunter2", page)


class TestHtml(unittest.TestCase):

    def render(self, **kw):
        with tempfile.TemporaryDirectory() as folder:
            doc = mc_statuspage.build_document(make_config(folder, **kw.pop("cfg", {})), sample(**kw))
        return mc_statuspage.render_html(doc)

    def test_well_formed_and_accessible(self):
        page = self.render()
        checker = Checker()
        checker.feed(page)
        self.assertEqual(checker.errors, [])
        self.assertEqual(checker.stack, [])
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        tags = {t: a for t, a in checker.tags}
        self.assertIn("lang", tags["html"])
        self.assertEqual(tags["meta"].get("charset") or "utf-8", "utf-8")
        self.assertTrue(any(a.get("name") == "viewport" for t, a in checker.tags if t == "meta"))

    def test_no_external_resource(self):
        page = self.render()
        for needle in ("http://", "https://", "<script", "<link", "<img", "@import", "url("):
            self.assertNotIn(needle, page)

    def test_escapes_hostile_text(self):
        page = self.render(cfg={"nom_serveur": "<script>alert(1)</script>"})
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_motd_without_section_signs_in_page(self):
        self.assertNotIn("§", self.render())

    def test_mentions_state_players_version_and_time(self):
        page = self.render()
        for needle in ("Paper 1.21.1", "2/20", "<time datetime="):
            self.assertIn(needle, page)


class TestWriting(unittest.TestCase):

    def test_atomic_replace_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "web", "status")
            with tempfile.TemporaryDirectory() as srv:
                doc = mc_statuspage.build_document(make_config(srv), sample())
            mc_statuspage.write_page(folder, doc)
            mc_statuspage.write_page(folder, doc)
            self.assertEqual(sorted(os.listdir(folder)), ["index.html", "status.json"])
            with open(os.path.join(folder, "status.json")) as f:
                self.assertEqual(json.load(f)["name"], "Survie")

    def test_failed_write_keeps_the_previous_page(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as srv:
            doc = mc_statuspage.build_document(make_config(srv), sample())
            mc_statuspage.write_page(root, doc)
            before = read(os.path.join(root, "index.html"))
            with mock.patch("os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    mc_statuspage.write_page(root, dict(doc, name="Other"))
            self.assertEqual(read(os.path.join(root, "index.html")), before)


class TestPublisher(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.server = os.path.join(self.root, "srv")
        os.makedirs(self.server)
        self.out = os.path.join(self.root, "out")
        config = make_config(self.server, status_page_dir=self.out, status_page_interval=60)
        config.pop("dossier_serveur")
        with open(os.path.join(self.server, "config.json"), "w") as f:
            json.dump(config, f)
        self.servers = {"survie": {"dossier_serveur": self.server}}
        self.clock = [1000.0]
        self.collector = mc_metrics.Collector(lambda n, c: sample(), lambda: self.clock[0], ttl=0)
        self.publisher = mc_statuspage.Publisher(self.collector, lambda: self.clock[0])

    def test_regenerates_at_the_configured_interval(self):
        self.publisher.run(self.servers)
        path = os.path.join(self.out, "status.json")
        first = os.stat(path).st_mtime_ns
        os.remove(path)
        self.clock[0] += 30
        self.publisher.run(self.servers)
        self.assertFalse(os.path.exists(path))
        self.clock[0] += 31
        self.publisher.run(self.servers)
        self.assertTrue(os.path.exists(path))
        self.assertGreaterEqual(os.stat(path).st_mtime_ns, first)

    def test_server_without_the_key_is_left_alone(self):
        with open(os.path.join(self.server, "config.json"), "w") as f:
            json.dump({"nom_serveur": "x"}, f)
        self.publisher.run(self.servers)
        self.assertFalse(os.path.exists(self.out))

    def test_write_failure_does_not_raise_and_backs_off(self):
        with mock.patch.object(mc_statuspage, "write_page", side_effect=OSError("ro")):
            self.publisher.run(self.servers)
        self.assertGreater(self.publisher.due["survie"], self.clock[0])


class TestEnableDisable(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.config = make_config(self.root)
        with open(os.path.join(self.root, "config.json"), "w") as f:
            json.dump({"nom_serveur": "Survie"}, f)
        self.stub = mock.patch.object(mc_metrics.COLLECTOR, "sample", lambda n, c: sample())
        self.stub.start()
        self.addCleanup(self.stub.stop)

    def test_enable_writes_page_and_persists_settings(self):
        out = os.path.join(self.root, "www")
        res = mc_api.statuspage_enable("survie", self.config, out, 30, True)
        self.assertEqual((res["ok"], res["code"]), (True, "status_page_enabled"))
        self.assertTrue(os.path.exists(os.path.join(out, "index.html")))
        saved = json.loads(read(os.path.join(self.root, "config.json")))
        self.assertEqual((saved["status_page_dir"], saved["status_page_interval"], saved["status_page_players"]),
                         (out, 30, 1))

    def test_default_folder_and_interval(self):
        res = mc_api.statuspage_enable("survie", self.config)
        self.assertEqual(res["path"], os.path.join(self.root, "status_page"))
        self.assertEqual(res["interval"], 60)

    def test_interval_too_short_changes_nothing(self):
        res = mc_api.statuspage_enable("survie", self.config, None, 5)
        self.assertEqual(res["code"], "status_page_interval_too_short")
        self.assertNotIn("status_page_dir", json.loads(read(os.path.join(self.root, "config.json"))))

    def test_unwritable_folder(self):
        blocker = os.path.join(self.root, "file")
        open(blocker, "w").close()
        res = mc_api.statuspage_enable("survie", self.config, os.path.join(blocker, "sub"))
        self.assertEqual((res["ok"], res["code"]), (False, "status_page_unwritable"))

    def test_disable_removes_files_and_keys(self):
        out = os.path.join(self.root, "www")
        mc_api.statuspage_enable("survie", self.config, out)
        res = mc_api.statuspage_disable("survie", self.config)
        self.assertEqual(res["code"], "status_page_disabled")
        self.assertEqual(os.listdir(out), [])
        self.assertNotIn("status_page_dir", json.loads(read(os.path.join(self.root, "config.json"))))
        self.assertEqual(mc_api.statuspage_disable("survie", self.config)["code"], "status_page_already_off")


class TestCli(unittest.TestCase):

    def test_unknown_server_is_not_found_and_bad_interval_is_usage(self):
        env = dict(os.environ, MCMANAGER_DATA_DIR=tempfile.mkdtemp(), NO_COLOR="1")
        def run(*a):
            return subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), *a], capture_output=True,
                                                text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(run("status-page", "enable", "zz", "--json").returncode, 3)
        self.assertEqual(run("status-page", "enable", "--interval", "abc").returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
