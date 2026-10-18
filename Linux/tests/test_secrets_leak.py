"""
test_secrets_leak.py — no command may print a configured secret, in text or
in JSON. A server is built with recognisable fake secrets; every command that
has --json runs against it and its whole output is searched.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, APP)
import mc_alert
import mc_api
import mc_backup
import mc_cli

SECRETS = {
    "rcon": "LEAK-rcon-pass-91",
    "hook": "LEAK-discord-hook-92",
    "cf": "LEAK-curseforge-key-93-abcdefgh",
    "smtp": "LEAK-smtp-pass-94",
    "tg": "LEAK-telegram-token-95",
    "ntfy": "LEAK-ntfy-token-96",
    "hdr": "LEAK-header-value-97",
    "hmac": "LEAK-hmac-secret-98",
    "akey": "LEAK-s3-access-99",
    "skey": "LEAK-s3-secret-100",
    "keyfile": "LEAK-keyfile-101",
    "pwfile": "LEAK-pwfile-102",
    "enc": "LEAK-enckey-103",
    "wh_path": "LEAK-webhook-path-104",
}

# command line (without --json) -> run as is; None = exempt, with the reason.
COVERED = {
    "status": [["status"], ["status", "a"]],
    "active": [["active"]],
    "players": [["players"], ["players", "history"]],
    "switch": [["switch", "a"]],
    "sleep": [["sleep", "status"]],
    "status-page": [["status-page", "disable"]],
    "router": [["router", "status"]],
    "datapack": [["datapack", "list"]],
    "mod": [["mod", "list"]],
    "java": [["java", "list"]],
    "backup": [["backup", "list"], ["backup", "remote", "list"]],
    "alert": [["alert", "list"]],
    "whitelist": [["whitelist", "list"]],
    "op": [["op", "list"]],
    "ban": [["ban", "list"]],
    "ban-ip": [["ban-ip", "list"]],
    "kick": [["kick", "Steve"]],
    "world": [["world", "list"]],
    "task": [["task", "list"]],
    "freeze": [["freeze", "--max", "1m"], ["thaw"]],
    "thaw": [],
    "doctor": [["doctor"]],
    "logs": [["logs"]],
    "resume": [["resume"]],
    "use": [["use", "a"]],
    "remove": [["remove", "zz", "--yes"]],
    "mode": [["mode", "always-on"]],
    "config": [],
    "deploy": None,
    "modpack": None,
    "upgrade": None,
    "update": None,
    "metrics": None,
}


def json_commands():
    parser = mc_cli.build_parser()
    sub = next(a for a in parser._actions if hasattr(a, "choices") and a.choices and a.dest == "action")
    names = set()
    for name, p in sub.choices.items():
        if any("--json" in a.option_strings for a in p._actions):
            names.add(name)
    return names


class TestLeaks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp()
        cls.folder = tempfile.mkdtemp()
        cfg = {
            "port": 1, "rcon_port": 2, "mcrcon_pass": SECRETS["rcon"], "always_on": 1, "nom_serveur": "a",
            "webhook_url": "https://discord.example/api/webhooks/1/" + SECRETS["hook"],
            "curseforge_api_key": SECRETS["cf"],
            "backup_encrypt_key_file": "/nowhere/" + SECRETS["enc"],
            "dossier_backup": os.path.join(cls.data, "bk"),
            "alerts": [
                {"name": "mail", "type": "email", "events": ["*"], "host": "smtp.example", "port": 587,
                 "user": "u", "password": SECRETS["smtp"], "sender": "a@b.c", "to": ["d@e.f"]},
                {"name": "tg", "type": "telegram", "events": ["*"], "token": SECRETS["tg"], "chat_id": "1"},
                {"name": "nt", "type": "ntfy", "events": ["*"], "topic": "t", "token": SECRETS["ntfy"]},
                {"name": "wh", "type": "webhook", "events": ["*"],
                 "url": "https://hook.example/" + SECRETS["wh_path"],
                 "headers": {"Authorization": "Bearer " + SECRETS["hdr"]}, "secret": SECRETS["hmac"]},
            ],
            "backup_remotes": [
                {"name": "s3", "type": "s3", "bucket": "b", "prefix": "p", "access_key": SECRETS["akey"],
                 "secret_key": SECRETS["skey"], "region": "r"},
                {"name": "sf", "type": "sftp", "host": "h", "port": 22, "user": "u", "path": "/x",
                 "key": "/home/u/" + SECRETS["keyfile"]},
                {"name": "rs", "type": "restic", "repo": "/r", "password_file": "/home/u/" + SECRETS["pwfile"]},
            ],
        }
        with open(os.path.join(cls.folder, "config.json"), "w") as f:
            json.dump(cfg, f)
        with open(os.path.join(cls.folder, "server.properties"), "w") as f:
            f.write("online-mode=false\nlevel-name=world\n")
        with open(os.path.join(cls.data, "servers.json"), "w") as f:
            json.dump({"active": "a", "servers": {"a": {"id": 1, "dossier_serveur": cls.folder}}}, f)
        cls.env = dict(os.environ, MCMANAGER_DATA_DIR=cls.data, NO_COLOR="1")
        cls.env.pop("MCMANAGER_DEBUG", None)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), *args],
                              capture_output=True, text=True, env=self.env,
                              stdin=subprocess.DEVNULL, timeout=60)

    def assert_clean(self, text, what):
        for label, value in SECRETS.items():
            self.assertNotIn(value, text, f"{label} leaked by: {what}")

    def test_every_json_command_is_covered_or_exempt(self):
        self.assertEqual(json_commands() - set(COVERED), set(),
                         "a command with --json has no leak check: add it to COVERED")

    def test_no_json_command_prints_a_secret(self):
        for name, variants in COVERED.items():
            for argv in variants or []:
                for extra in ([], ["--json"]):
                    if extra and name not in json_commands():
                        continue
                    with self.subTest(command=" ".join(argv + extra)):
                        res = self.run_cli(*argv, *extra)
                        self.assert_clean(res.stdout + res.stderr, " ".join(argv + extra))

    def test_config_get_masks_everything(self):
        res = self.run_cli("config", "get")
        self.assertEqual(res.returncode, 0)
        self.assert_clean(res.stdout + res.stderr, "config get")
        doc = json.loads(res.stdout)
        self.assertEqual(doc["mcrcon_pass"], "***")
        self.assertEqual(sorted(doc["secrets_set"]), sorted(
            ["mcrcon_pass", "webhook_url", "curseforge_api_key", "backup_encrypt_key_file", "alerts",
             "backup_remotes"]))
        self.assertEqual(doc["nom_serveur"], "a")

    def test_config_get_of_a_secret_key_needs_reveal(self):
        res = self.run_cli("config", "get", "mcrcon_pass")
        self.assertEqual(res.returncode, 1)
        self.assert_clean(res.stdout + res.stderr, "config get mcrcon_pass")
        res = self.run_cli("config", "get", "mcrcon_pass", "--reveal")
        self.assertEqual((res.returncode, res.stdout.strip()), (0, SECRETS["rcon"]))
        self.assertEqual(self.run_cli("config", "get", "nom_serveur").stdout.strip(), "a")

    def test_config_set_never_echoes_a_secret(self):
        res = self.run_cli("config", "set", "webhook_url", "https://discord.example/x/" + SECRETS["hook"])
        self.assert_clean(res.stdout + res.stderr, "config set webhook_url")

    def test_alert_list_gives_header_names_not_values(self):
        res = json.loads(self.run_cli("alert", "list", "--json").stdout)
        hook = next(c for c in res["channels"] if c["name"] == "wh")
        self.assertNotIn("headers", hook)
        self.assertEqual(hook["header_names"], ["Authorization"])
        self.assertEqual(sorted(hook["secrets_set"]), ["headers", "secret"])

    def test_backup_remote_list_has_no_credentials_or_paths(self):
        res = json.loads(self.run_cli("backup", "remote", "list", "--json").stdout)
        by_name = {r["name"]: r for r in res["remotes"]}
        self.assertNotIn("access_key", by_name["s3"])
        self.assertEqual(by_name["s3"]["secrets_set"], ["access_key", "secret_key"])
        self.assertNotIn("key", by_name["sf"])
        self.assertEqual(by_name["sf"]["secrets_set"], ["key"])
        self.assertNotIn("password_file", by_name["rs"])
        self.assertEqual(by_name["rs"]["secrets_set"], ["password_file"])


class TestErrorMessages(unittest.TestCase):

    def config(self):
        return {"dossier_serveur": tempfile.mkdtemp(), "nom_serveur": "a", "alerts": [
            {"name": "wh", "type": "webhook", "events": ["*"], "url": "https://hook.example/" + SECRETS["wh_path"],
             "headers": {"Authorization": SECRETS["hdr"]}, "secret": SECRETS["hmac"]}],
            "backup_remotes": [
                {"name": "s3", "type": "s3", "bucket": "b", "access_key": SECRETS["akey"],
                 "secret_key": SECRETS["skey"]},
                {"name": "sf", "type": "sftp", "host": "h", "path": "/x", "key": "/k/" + SECRETS["keyfile"]}]}

    def test_alert_test_failure_details_are_redacted(self):
        def boom(url, body, headers):
            raise OSError(f"{url} {headers['Authorization']} {headers['X-MCManager-Signature']}")
        with mock.patch.object(mc_alert, "http_post", boom):
            res = mc_api.alert_test("a", self.config())
        self.assertFalse(res["ok"])
        text = json.dumps(res)
        self.assertNotIn(SECRETS["wh_path"], text)
        self.assertNotIn(SECRETS["hdr"], text)

    def test_backup_remote_test_failure_details_are_redacted(self):
        def boom(remote):
            raise mc_backup.BackupError("failed", f"{remote.get('access_key')} {remote.get('secret_key')} "
                                                  f"{remote.get('key')}")
        with mock.patch.object(mc_backup, "check_remote", boom):
            res = mc_api.backup_remote_test("a", self.config())
        self.assertFalse(res["ok"])
        self.assertNotIn("LEAK", json.dumps(res))

    def test_push_all_failure_details_are_redacted(self):
        def boom(remote, *a, **k):
            raise mc_backup.BackupError("s3_failed", f"{remote.get('secret_key')} {remote.get('key')}")
        with mock.patch.object(mc_backup, "push", boom):
            out = mc_backup.push_all(self.config(), "x.zip")
        self.assertNotIn("LEAK", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
