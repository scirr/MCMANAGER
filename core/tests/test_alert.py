"""
test_alert.py — Alert channels: validation, event filtering, transports
(SMTP and HTTP simulated), secrets, the mc_api operations and the CLI.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_alert
import mc_api
import mc_config
import mc_core

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class FakeSMTP:
    instances = []

    def __init__(self, host, port):
        self.host, self.port, self.calls, self.sent = host, port, [], None
        FakeSMTP.instances.append(self)

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.calls.append("send")
        self.sent = (msg, from_addr, to_addrs)

    def quit(self):
        self.calls.append("quit")


class Posts:
    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, url, body, headers):
        self.calls.append((url, body, headers))
        if self.fail:
            raise OSError("connection refused: " + url)


class AlertBase(unittest.TestCase):
    def setUp(self):
        self.posts = Posts()
        FakeSMTP.instances = []
        for target, value in (("http_post", self.posts), ("smtp_connect", FakeSMTP)):
            p = mock.patch.object(mc_alert, target, value)
            p.start()
            self.addCleanup(p.stop)


class TestEvents(unittest.TestCase):

    def test_parse(self):
        self.assertEqual(mc_alert.parse_events(None), ["*"])
        self.assertEqual(mc_alert.parse_events("*"), ["*"])
        self.assertEqual(mc_alert.parse_events("start, crash,start"), ["start", "crash"])
        self.assertIsNone(mc_alert.parse_events("start,boom"))

    def test_every_event_has_both_texts(self):
        from mc_lang import T
        for event in mc_alert.EVENTS:
            self.assertIn(f"alert_title_{event}", T)
            self.assertIn(f"alert_text_{event}", T)

    def test_urls(self):
        self.assertTrue(mc_alert.valid_url("https://ntfy.sh"))
        self.assertTrue(mc_alert.valid_url("http://127.0.0.1:8080/x"))
        self.assertFalse(mc_alert.valid_url("http://example.com/x"))
        self.assertFalse(mc_alert.valid_url("ftp://example.com"))
        self.assertFalse(mc_alert.valid_url("https://"))


class TestValidation(unittest.TestCase):

    def test_each_type(self):
        self.assertEqual(mc_alert.validate("nope", {}), "bad_type")
        self.assertEqual(mc_alert.validate("email", {"sender": "a@b", "to": ["c@d"]}), "missing_host")
        self.assertEqual(mc_alert.validate("email", {"host": "h", "to": ["c@d"]}), "missing_addresses")
        self.assertEqual(mc_alert.validate("email", {"host": "h", "sender": "a", "to": ["c"], "port": "x"}), "bad_port")
        self.assertIsNone(mc_alert.validate("email", {"host": "h", "sender": "a", "to": ["c"]}))
        self.assertEqual(mc_alert.validate("telegram", {"token": "t"}), "missing_telegram")
        self.assertEqual(mc_alert.validate("ntfy", {}), "missing_topic")
        self.assertEqual(mc_alert.validate("ntfy", {"topic": "t", "server": "http://x.example"}), "bad_url")
        self.assertEqual(mc_alert.validate("webhook", {"url": "http://x.example"}), "bad_url")
        self.assertIsNone(mc_alert.validate("webhook", {"url": "https://x.example/h"}))


class TestTransports(AlertBase):
    CFG = {"nom_serveur": "Survie"}

    def test_email_starttls_login_and_message(self):
        ch = {"name": "mail", "type": "email", "host": "smtp.example", "port": 587, "user": "u",
              "password": "pw", "sender": "mc@example", "to": ["a@example", "b@example"]}
        ok, _ = mc_alert.send(ch, mc_alert.build_event("crash", "Survie", detail="boom"))
        self.assertTrue(ok)
        smtp = FakeSMTP.instances[0]
        self.assertEqual((smtp.host, smtp.port), ("smtp.example", 587))
        self.assertEqual(smtp.calls, ["ehlo", "starttls", "ehlo", ("login", "u", "pw"), "send", "quit"])
        msg, sender, rcpt = smtp.sent
        self.assertEqual((sender, rcpt), ("mc@example", ["a@example", "b@example"]))
        self.assertIn("Survie", msg["Subject"])
        self.assertIn("boom", msg.get_content())

    def test_email_without_credentials_skips_login(self):
        ch = {"name": "m", "type": "email", "host": "h", "sender": "a@b", "to": "c@d"}
        mc_alert.send(ch, mc_alert.build_event("start", "S"))
        self.assertNotIn("login", [c if isinstance(c, str) else c[0] for c in FakeSMTP.instances[0].calls])

    def test_telegram(self):
        ch = {"name": "t", "type": "telegram", "token": "123:ABC", "chat_id": "-42"}
        ok, _ = mc_alert.send(ch, mc_alert.build_event("stop", "S", reason="user"))
        url, body, headers = self.posts.calls[0]
        self.assertTrue(ok)
        self.assertEqual(url, "https://api.telegram.org/bot123:ABC/sendMessage")
        self.assertEqual(json.loads(body)["chat_id"], "-42")

    def test_ntfy_default_and_custom_server_with_token(self):
        mc_alert.send({"name": "n", "type": "ntfy", "topic": "mc alerts"}, mc_alert.build_event("crash_loop", "S"))
        url, body, headers = self.posts.calls[0]
        self.assertEqual(url, "https://ntfy.sh/mc%20alerts")
        self.assertEqual(headers["Priority"], "urgent")
        mc_alert.send({"name": "n", "type": "ntfy", "topic": "t", "server": "https://ntfy.home/", "token": "tk_x"},
                      mc_alert.build_event("start", "S"))
        url, body, headers = self.posts.calls[1]
        self.assertEqual(url, "https://ntfy.home/t")
        self.assertEqual(headers["Authorization"], "Bearer tk_x")

    def test_ntfy_title_with_accents_is_header_safe(self):
        mc_alert.send({"name": "n", "type": "ntfy", "topic": "t"}, mc_alert.build_event("sleep", "Été"))
        title = self.posts.calls[0][2]["Title"]
        title.encode("ascii")

    def test_generic_webhook_json_headers_and_signature(self):
        ch = {"name": "w", "type": "webhook", "url": "https://hook.example/x", "headers": {"X-Key": "1"},
              "secret": "s3cret"}
        mc_alert.send(ch, mc_alert.build_event("backup_failed", "S", detail="disk full"))
        url, body, headers = self.posts.calls[0]
        doc = json.loads(body)
        self.assertEqual((doc["schema"], doc["event"], doc["server"], doc["detail"]), (1, "backup_failed", "S", "disk full"))
        self.assertEqual(headers["X-Key"], "1")
        import hashlib
        import hmac
        expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertEqual(headers["X-MCManager-Signature"], expected)

    def test_discord_channel_embeds(self):
        mc_alert.send({"name": "d2", "type": "discord", "url": "https://discord.com/api/webhooks/1/x"},
                      mc_alert.build_event("update", "S"))
        self.assertIn("embeds", json.loads(self.posts.calls[0][1]))

    def test_failure_is_reported_and_secrets_are_redacted(self):
        self.posts.fail = True
        ch = {"name": "t", "type": "telegram", "token": "123:ABC", "chat_id": "1"}
        ok, detail = mc_alert.send(ch, mc_alert.build_event("start", "S"))
        self.assertFalse(ok)
        self.assertNotIn("123:ABC", detail)
        self.assertIn("***", detail)


class TestNotify(AlertBase):

    def config(self, **extra):
        cfg = {"nom_serveur": "Survie", "alerts": [
            {"name": "all", "type": "webhook", "url": "https://h.example/a", "events": ["*"]},
            {"name": "crashes", "type": "webhook", "url": "https://h.example/b", "events": ["crash", "crash_loop"]},
        ]}
        cfg.update(extra)
        return cfg

    def test_filter_per_channel(self):
        mc_alert.notify(self.config(), "start")
        self.assertEqual([c[0] for c in self.posts.calls], ["https://h.example/a"])
        self.posts.calls.clear()
        mc_alert.notify(self.config(), "crash")
        self.assertEqual(len(self.posts.calls), 2)

    def test_silent_in_maintenance_unless_forced(self):
        self.assertEqual(mc_alert.notify(self.config(mode_maintenance=1), "crash"), [])
        self.assertEqual(len(mc_alert.notify(self.config(mode_maintenance=1), "crash", force=True)), 2)

    def test_one_failing_channel_does_not_block_others_nor_raise(self):
        cfg = self.config()
        calls = []

        def post(url, body, headers):
            calls.append(url)
            if url.endswith("/a"):
                raise OSError("down")
        with mock.patch.object(mc_alert, "http_post", post):
            done = mc_alert.notify(cfg, "crash")
        self.assertEqual(calls, ["https://h.example/a", "https://h.example/b"])
        self.assertEqual([(n, ok) for n, ok, _ in done], [("all", False), ("crashes", True)])

    def test_unknown_event_and_no_channel(self):
        self.assertEqual(mc_alert.notify(self.config(), "bogus"), [])
        self.assertEqual(mc_alert.notify({}, "start"), [])

    def test_stop_reason_is_in_the_message(self):
        mc_alert.notify(self.config(), "stop", reason="update")
        self.assertEqual(json.loads(self.posts.calls[0][1])["reason"], "update")

    def test_listing_masks_secrets_and_includes_legacy_discord(self):
        cfg = {"alerts": [{"name": "t", "type": "telegram", "token": "SECRET", "chat_id": "1", "events": ["*"]},
                          {"name": "w", "type": "webhook", "url": "https://h.example/path/TOKEN", "events": ["*"]}],
               "webhook_url": "https://discord.com/api/webhooks/1/TOKEN2"}
        text = json.dumps(mc_alert.listing(cfg))
        for secret in ("SECRET", "TOKEN", "TOKEN2"):
            self.assertNotIn(secret, text)
        self.assertEqual([c["name"] for c in mc_alert.listing(cfg)], ["t", "w", "discord"])

    def test_listing_drops_secret_fields_instead_of_masking(self):
        cfg = {"alerts": [{"name": "t", "type": "telegram", "token": "SECRET", "chat_id": "1", "events": ["*"]},
                          {"name": "m", "type": "email", "password": "PW", "host": "h", "events": ["*"]}]}
        listed = mc_alert.listing(cfg)
        self.assertNotIn("***", json.dumps(listed))
        for channel in listed:
            self.assertFalse({"secret", "token", "password"} & set(channel))
        self.assertEqual([c["secrets_set"] for c in listed], [["token"], ["password"]])

    def test_test_channels_ignores_filters_and_reaches_legacy_discord(self):
        cfg = {"nom_serveur": "S", "webhook_url": "https://discord.com/api/webhooks/1/x",
               "alerts": [{"name": "c", "type": "webhook", "url": "https://h.example/c", "events": ["crash"]}]}
        found, sent = mc_alert.test_channels(cfg)
        self.assertTrue(found)
        self.assertEqual([n for n, ok, _ in sent], ["c", "discord"])
        self.assertEqual(mc_alert.test_channels(cfg, "zz"), (False, []))


class TestHooks(AlertBase):

    def test_stop_server_sends_stop_or_sleep(self):
        cfg = {"nom_serveur": "S", "dossier_serveur": "/x", "alerts": [
            {"name": "w", "type": "webhook", "url": "https://h.example/a", "events": ["*"]}]}
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
                mock.patch.object(mc_core, "startup_in_progress", return_value=False), \
                mock.patch.object(mc_core, "send_rcon", return_value=True), \
                mock.patch.object(mc_core, "wait_for_exit", return_value=True), \
                mock.patch.object(mc_core, "_remove_pid_file"), \
                mock.patch.object(mc_core, "send_discord_webhook"), \
                mock.patch.object(mc_core.mc_config, "load_webhooks", return_value={}):
            mc_core.stop_server(cfg, reason="sleep")
            mc_core.stop_server(cfg, reason="update")
            mc_core.stop_server(cfg, reason="update", quiet=True)
        events = [(json.loads(c[1])["event"], json.loads(c[1])["reason"]) for c in self.posts.calls]
        self.assertEqual(events, [("sleep", "sleep"), ("stop", "update")])

    def test_backup_failure_raises_backup_failed(self):
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, "srv")
            os.makedirs(os.path.join(folder, "world"))
            cfg = {"nom_serveur": "S", "dossier_serveur": folder, "dossier_backup": os.path.join(d, "bk"),
                   "alerts": [{"name": "w", "type": "webhook", "url": "https://h.example/a", "events": ["backup_failed"]}]}
            with mock.patch("zipfile.ZipFile", side_effect=OSError("disk full")):
                ok, _ = mc_core.backup_server(cfg)
        self.assertFalse(ok)
        doc = json.loads(self.posts.calls[0][1])
        self.assertEqual(doc["event"], "backup_failed")
        self.assertIn("disk full", doc["detail"])


class TestDaemonAndApiEvents(AlertBase):

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"dossier_serveur": self.tmp.name, "nom_serveur": "S", "always_on": 1, "port": 1,
                    "rcon_port": 2, "mcrcon_pass": "x", "mode_maintenance": 0,
                    "alerts": [{"name": "w", "type": "webhook", "url": "https://h.example/a", "events": ["*"]}]}

    def events(self):
        return [json.loads(c[1])["event"] for c in self.posts.calls]

    def test_unplanned_exit_alerts_crash_then_crash_loop(self):
        import mc_daemon
        state = mc_daemon._new_state()
        state["expected_up"] = True
        state["launched_at"] = 1
        with mock.patch.object(mc_core, "log_has_done", return_value=True):
            mc_daemon._watch_crash("a", self.cfg, state, False, now=1000)
        self.assertEqual(self.events(), ["crash"])
        state["expected_up"] = True
        with mock.patch.object(mc_core, "log_has_done", return_value=False), \
                mock.patch.object(mc_core, "send_discord_webhook"):
            mc_daemon._watch_crash("a", self.cfg, state, False, now=1001)
        self.assertEqual(self.events(), ["crash", "crash_loop"])

    def test_wake_alerts_only_when_started(self):
        with mock.patch.object(mc_api, "server_state", return_value="sleeping"), \
                mock.patch.object(mc_api, "start", return_value=mc_api.result(True, "started")), \
                mock.patch("mc_servers.update_cached_ports"):
            mc_api.wake("a", self.cfg)
        self.assertEqual(self.events(), ["wake"])
        self.posts.calls.clear()
        with mock.patch.object(mc_api, "server_state", return_value="sleeping"), \
                mock.patch.object(mc_api, "start", return_value=mc_api.result(False, "start_failed")), \
                mock.patch("mc_servers.update_cached_ports"):
            mc_api.wake("a", self.cfg)
        self.assertEqual(self.events(), [])

    def test_successful_start_alerts_start(self):
        proc = mock.Mock(pid=4242)
        proc.poll.return_value = None
        with mock.patch.object(mc_core, "is_server_running", return_value=False), \
                mock.patch.object(mc_core, "port_occupant", return_value=None), \
                mock.patch.object(mc_core, "sync_server_properties", return_value=[]), \
                mock.patch.object(mc_core, "check_java", return_value=(True, "")), \
                mock.patch.object(mc_core, "find_java", return_value="java"), \
                mock.patch.object(mc_core, "_write_pid_file"), \
                mock.patch.object(mc_core, "send_discord_webhook"), \
                mock.patch.object(mc_core.time, "sleep"), \
                mock.patch("subprocess.Popen", return_value=proc), \
                mock.patch("mc_servers.update_cached_ports"):
            ok, _ = mc_core.start_server(self.cfg)
        self.assertTrue(ok)
        self.assertEqual(self.events(), ["start"])


class ApiBase(AlertBase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {"dossier_serveur": self.tmp.name, "nom_serveur": "S"}
        patcher = mock.patch("mc_servers.update_cached_ports")
        patcher.start()
        self.addCleanup(patcher.stop)


class TestApi(ApiBase):

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_add_list_test_remove_roundtrip_and_perms(self):
        res = mc_api.alert_add("s", self.config, "telegram", {"token": "123:ABC", "chat_id": "9"}, "crash,start")
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["channel"], res["events"]), ("telegram", ["crash", "start"]))
        path = os.path.join(self.tmp.name, "config.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(mc_config.load_config(self.tmp.name)["alerts"][0]["token"], "123:ABC")
        listed = mc_api.alert_list("s", self.config)
        self.assertNotIn("123:ABC", json.dumps(listed))
        tested = mc_api.alert_test("s", self.config, "telegram")
        self.assertTrue(tested["ok"])
        self.assertEqual(len(self.posts.calls), 1)
        self.assertTrue(mc_api.alert_remove("s", self.config, "telegram")["ok"])
        self.assertNotIn("alerts", self.config)
        self.assertEqual(mc_api.alert_remove("s", self.config, "telegram")["code"], "channel_not_found")

    def test_names_are_made_unique_and_validated(self):
        add = lambda **k: mc_api.alert_add("s", self.config, "ntfy", {"topic": "t"}, **k)  # noqa: E731
        self.assertEqual(add()["channel"], "ntfy")
        self.assertEqual(add()["channel"], "ntfy-2")
        self.assertEqual(add(channel_name="ntfy")["code"], "channel_exists")
        self.assertEqual(add(channel_name="bad name")["code"], "bad_channel_name")
        self.assertEqual(add(channel_name="discord")["code"], "bad_channel_name")

    def test_rejections(self):
        self.assertEqual(mc_api.alert_add("s", self.config, "sms", {})["code"], "bad_type")
        self.assertEqual(mc_api.alert_add("s", self.config, "ntfy", {"topic": "t"}, "boom")["code"], "bad_events")
        self.assertEqual(mc_api.alert_add("s", self.config, "email", {"host": "h"})["code"], "missing_addresses")
        self.assertNotIn("alerts", self.config)

    def test_email_recipients_are_split(self):
        mc_api.alert_add("s", self.config, "email",
                         {"host": "h", "sender": "a@b", "to": "x@y, z@y", "user": "u", "password": "p"})
        self.assertEqual(self.config["alerts"][0]["to"], ["x@y", "z@y"])
        self.assertEqual(self.config["alerts"][0]["port"], 587)

    def test_test_failure_is_reported(self):
        mc_api.alert_add("s", self.config, "webhook", {"url": "https://h.example/x"})
        self.posts.fail = True
        res = mc_api.alert_test("s", self.config)
        self.assertEqual((res["ok"], res["code"], res["failed"]), (False, "alert_test_failed", "webhook"))

    def test_test_without_channel(self):
        self.assertEqual(mc_api.alert_test("s", self.config)["code"], "no_channel")


class TestCli(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp()
        cls.folder = tempfile.mkdtemp()
        with open(os.path.join(cls.folder, "config.json"), "w") as f:
            json.dump({"port": 1, "rcon_port": 2, "mcrcon_pass": "x", "always_on": 1, "nom_serveur": "a"}, f)
        with open(os.path.join(cls.data, "servers.json"), "w") as f:
            json.dump({"active": "a", "servers": {"a": {"id": 1, "dossier_serveur": cls.folder}}}, f)
        cls.env = dict(os.environ, MCMANAGER_DATA_DIR=cls.data, NO_COLOR="1")

    def mc(self, *args):
        return subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), *args], capture_output=True,
                              text=True, env=self.env, stdin=subprocess.DEVNULL, timeout=60)

    def test_add_list_remove_json_and_exit_codes(self):
        res = self.mc("alert", "add", "ntfy", "--topic", "t", "--events", "crash", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        doc = json.loads(res.stdout)
        self.assertEqual((doc["schema"], doc["ok"], doc["code"]), (1, True, "alert_added"))
        listed = json.loads(self.mc("alert", "list", "--json").stdout)
        self.assertEqual(listed["channels"][0]["events"], ["crash"])
        self.assertEqual(self.mc("alert", "remove", "ntfy").returncode, 0)
        self.assertEqual(self.mc("alert", "remove", "ntfy").returncode, 1)

    def test_usage_errors_exit_2_and_unknown_server_3(self):
        self.assertEqual(self.mc("alert", "add", "sms").returncode, 2)
        self.assertEqual(self.mc("alert", "add", "telegram", "--token", "x").returncode, 2)
        self.assertEqual(self.mc("alert", "add").returncode, 2)
        self.assertEqual(self.mc("alert", "list", "zz").returncode, 3)

    def test_options_before_or_after_positionals(self):
        a = self.mc("alert", "add", "ntfy", "--topic", "t", "--name", "one", "a")
        b = self.mc("alert", "add", "--topic", "t", "--name", "two", "ntfy", "a")
        self.assertEqual((a.returncode, b.returncode), (0, 0), a.stdout + b.stdout)
        self.mc("alert", "remove", "one")
        self.mc("alert", "remove", "two")


if __name__ == "__main__":
    unittest.main(verbosity=2)
