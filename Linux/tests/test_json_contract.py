"""
test_json_contract.py — the --json outputs scripts depend on: every document
carries ok and code, the commands added in 2.11 answer in JSON, and dates come
with an epoch twin (*_ts).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, APP)
import mc_api
import mc_modsources


class Base(unittest.TestCase):

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.folder = tempfile.mkdtemp()
        self.cfg = {"port": 1, "rcon_port": 2, "mcrcon_pass": "x", "always_on": 1, "nom_serveur": "a",
                    "dossier_backup": os.path.join(self.data, "bk")}
        self.save()
        with open(os.path.join(self.folder, "server.properties"), "w") as f:
            f.write("online-mode=false\nlevel-name=world\n")
        os.makedirs(os.path.join(self.folder, "world", "region"))
        with open(os.path.join(self.folder, "world", "level.dat"), "w") as f:
            f.write("x")
        with open(os.path.join(self.data, "servers.json"), "w") as f:
            json.dump({"active": "a", "servers": {"a": {"id": 1, "dossier_serveur": self.folder}}}, f)
        self.env = dict(os.environ, MCMANAGER_DATA_DIR=self.data, NO_COLOR="1")
        self.env.pop("MCMANAGER_DEBUG", None)

    def save(self):
        with open(os.path.join(self.folder, "config.json"), "w") as f:
            json.dump(self.cfg, f)

    def js(self, *args):
        res = subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), *args, "--json"],
                             capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL, timeout=60)
        return res.returncode, json.loads(res.stdout)


class TestOkAndCode(Base):

    def test_every_document_has_ok_and_code(self):
        for argv in (["status"], ["status", "a"], ["active"], ["players"], ["java", "list"], ["sleep", "status"]):
            with self.subTest(command=" ".join(argv)):
                rc, doc = self.js(*argv)
                self.assertEqual((rc, doc["ok"], doc["schema"]), (0, True, 1))
                self.assertIsInstance(doc["code"], str)

    def test_failures_carry_ok_false_and_keep_the_error_object(self):
        rc, doc = self.js("status", "zz")
        self.assertEqual((rc, doc["ok"], doc["code"], doc["error"]["code"]), (3, False, "not_found", "not_found"))
        os.remove(os.path.join(self.data, "servers.json"))
        with open(os.path.join(self.data, "servers.json"), "w") as f:
            json.dump({"active": None, "servers": {}}, f)
        rc, doc = self.js("active")
        self.assertEqual((rc, doc["ok"], doc["code"], doc["error"]["code"]), (3, False, "no_active_server",
                                                                               "no_active_server"))

    def test_existing_fields_are_kept(self):
        rc, doc = self.js("active")
        for key in ("name", "id", "active", "path", "state", "error", "sleep"):
            self.assertIn(key, doc)
        self.assertEqual(doc["server"], "a")

    def test_snapshot_has_server_next_to_name(self):
        snap = mc_api.server_snapshot("a", {"id": 1, "dossier_serveur": self.folder}, "a")
        self.assertEqual((snap["name"], snap["server"]), ("a", "a"))
        self.assertIn("server", mc_api.server_snapshot("b", {"id": 2, "dossier_serveur": "/nonexistent"}))


class TestNewJsonCommands(Base):

    def test_freeze_and_thaw(self):
        rc, doc = self.js("freeze", "--max", "2m")
        self.assertEqual((rc, doc["ok"], doc["code"], doc["server"], doc["max_s"]), (0, True, "offline", "a", 120))
        self.assertEqual(doc["expires_ts"] - doc["since_ts"], 120)
        rc, doc = self.js("freeze")
        self.assertEqual((rc, doc["ok"], doc["code"]), (1, False, "already_frozen"))
        rc, doc = self.js("thaw")
        self.assertEqual((rc, doc["ok"], doc["code"], doc["server"]), (0, True, "offline", "a"))
        self.assertEqual(self.js("freeze", "--max", "nonsense")[0], 2)

    def test_freeze_command_runs_then_thaws(self):
        res = subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), "freeze", "--json", "--",
                              sys.executable, "-c", "print('payload'); raise SystemExit(4)"],
                             capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL, timeout=60)
        doc = json.loads(res.stdout)
        self.assertEqual((res.returncode, doc["command_exit_code"], doc["thaw"]["ok"]), (4, 4, True))
        self.assertIn("payload", res.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.folder, mc_api.FROZEN_MARKER)))

    def test_doctor(self):
        rc, doc = self.js("doctor")
        self.assertEqual((doc["ok"], doc["code"]), (rc == 0, "doctor"))
        self.assertTrue(doc["checks"])
        for check in doc["checks"]:
            self.assertEqual(set(check), {"server", "name", "ok", "level", "detail", "fix"})
            self.assertIn(check["level"], ("ok", "info", "warn", "err"))
        self.assertIn("a", {c["server"] for c in doc["checks"]})
        rc, doc = self.js("doctor", "zz")
        self.assertEqual((rc, doc["ok"], doc["code"]), (3, False, "not_found"))

    def test_resume_mode_use(self):
        rc, doc = self.js("mode", "maintenance")
        self.assertEqual((rc, doc["code"], doc["mode"]), (0, "mode_set", "maintenance"))
        rc, doc = self.js("resume")
        self.assertEqual((rc, doc["ok"], doc["code"], doc["server"], doc["was_crashed"]), (0, True, "resumed", "a", False))
        self.assertEqual(doc["mode"], "always-on")
        rc, doc = self.js("use", "a")
        self.assertEqual((rc, doc["code"], doc["server"], doc["id"]), (0, "active_set", "a", 1))
        rc, doc = self.js("use", "zz")
        self.assertEqual((rc, doc["ok"], doc["code"]), (3, False, "not_found"))

    def test_remove_needs_yes(self):
        rc, doc = self.js("remove", "a")
        self.assertEqual((rc, doc["code"]), (2, "confirm_required"))
        rc, doc = self.js("remove", "a", "--yes")
        self.assertEqual((rc, doc["ok"], doc["code"], doc["server"], doc["path"]), (0, True, "deregistered", "a", self.folder))
        self.assertTrue(os.path.isdir(self.folder))

    def test_backup_and_its_timestamp(self):
        rc, doc = self.js("backup")
        self.assertEqual((rc, doc["ok"], doc["code"]), (0, True, "backup_created"))
        self.assertTrue(os.path.isfile(doc["path"]))
        self.assertGreater(doc["created_ts"], 1_700_000_000)
        rc, doc = self.js("backup", "list")
        self.assertIsInstance(doc["backups"][0]["created_ts"], int)

    def test_logs(self):
        rc, doc = self.js("logs")
        self.assertIn(doc["code"], ("logs", "no_log_file"))
        self.assertEqual(doc["ok"], doc["code"] == "logs")
        if doc["ok"]:
            self.assertIsInstance(doc["lines"], list)
            self.assertLessEqual(len(doc["lines"]), 30)
        self.assertEqual(self.js("logs", "zz")[0], 3)


class TestModList(Base):

    def test_jar_version_is_kept_and_tracked_version_is_added(self):
        mods = os.path.join(self.folder, "mods")
        os.makedirs(mods)
        with zipfile.ZipFile(os.path.join(mods, "m.jar"), "w") as zf:
            zf.writestr("fabric.mod.json", json.dumps({"id": "m", "name": "M", "version": "1.2.3"}))
        self.cfg["dossier_serveur"] = self.folder
        mc_modsources.save_manifest(self.cfg, {"entries": {"modrinth:m": {
            "file": "m.jar", "source": "modrinth", "slug": "m", "version": "9.9.9"}}})
        rc, doc = self.js("mod", "list")
        mod = doc["mods"][0]
        self.assertEqual((mod["version"], mod["tracked_version"], mod["source"]), ("1.2.3", "9.9.9", "modrinth"))


class TestTimestamps(Base):

    def test_tasks(self):
        self.js("task", "add", "--cron", "*/5 * * * *", "--action", "command", "--command", "say hi")
        rc, doc = self.js("task", "list")
        task = doc["tasks"][0]
        self.assertIsInstance(task["next_run_ts"], int)
        self.assertIsNone(task["last_run_ts"])
        with open(os.path.join(self.folder, "config.json")) as f:
            self.cfg = json.load(f)
        self.cfg["tasks"][0]["last_run"] = "2026-01-02T03:04:05"
        self.save()
        task = self.js("task", "list")[1]["tasks"][0]
        import datetime
        self.assertEqual(task["last_run_ts"], int(datetime.datetime(2026, 1, 2, 3, 4, 5).timestamp()))

    def test_bans(self):
        with open(os.path.join(self.folder, "banned-players.json"), "w") as f:
            json.dump([{"uuid": "u", "name": "Steve", "created": "2026-01-02 03:04:05 +0000",
                        "source": "x", "expires": "forever", "reason": "r"}], f)
        entry = self.js("ban", "list")[1]["entries"][0]
        self.assertEqual((entry["created_ts"], entry["expires_ts"], entry["created"]),
                         (1767323045, None, "2026-01-02 03:04:05 +0000"))

    def test_history(self):
        logs = os.path.join(self.folder, "logs")
        os.makedirs(logs)
        with open(os.path.join(logs, "latest.log"), "w") as f:
            f.write("[10:00:00] [Server thread/INFO]: Steve[/203.0.113.5:1] logged in with entity id 1 at (0, 0, 0)\n"
                    "[10:10:00] [Server thread/INFO]: Steve left the game\n")
        s = self.js("players", "history", "--days", "3650")[1]["sessions"][0]
        self.assertEqual(s["leave_ts"] - s["join_ts"], 600)
        self.assertEqual(s["duration_s"], 600)
        self.assertIn("join", s)

    def test_snapshot_freeze_times(self):
        self.js("freeze", "--max", "5m")
        snap = self.js("status")[1]["servers"][0]
        self.assertTrue(snap["frozen"])
        self.assertEqual(snap["frozen_expires_ts"] - snap["frozen_since_ts"], 300)


if __name__ == "__main__":
    unittest.main()
