"""
test_backup.py — Backup list, retention, restoration, destinations
(sftp / s3 / restic simulated), encryption and the freeze around a running
server.
"""
import datetime
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_api
import mc_backup
import mc_config
import mc_core

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def make_archive(folder, day, hhmm="12-00-00", kind="manual", world="world", level=True, size=10):
    d = os.path.join(folder, day)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"backup_{kind}_{day}_{hhmm}.zip")
    with zipfile.ZipFile(path, "w") as zf:
        if level:
            zf.writestr(f"{world}/level.dat", "x" * size)
            zf.writestr(f"{world}/region/r.0.0.mca", "R")
    return path


def days_ago(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).strftime("%Y-%m-%d")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.server = os.path.join(self.root, "srv")
        self.backups = os.path.join(self.root, "bk")
        os.makedirs(self.server)
        os.makedirs(self.backups)


class TestListing(Tmp):

    def test_newest_first_with_ids_and_types(self):
        make_archive(self.backups, days_ago(2), kind="auto")
        new = make_archive(self.backups, days_ago(0), "09-30-00", kind="manual")
        items = mc_backup.list_backups(self.backups)
        self.assertEqual(items[0]["path"], new)
        self.assertEqual(items[0]["id"], os.path.basename(new)[:-4])
        self.assertEqual((items[0]["type"], items[1]["type"]), ("manual", "auto"))
        self.assertFalse(items[0]["encrypted"])

    def test_find_by_id_file_latest_and_path(self):
        a = make_archive(self.backups, days_ago(3))
        b = make_archive(self.backups, days_ago(1))
        ident = os.path.basename(a)[:-4]
        self.assertEqual(mc_backup.find_backup(self.backups, ident)["path"], a)
        self.assertEqual(mc_backup.find_backup(self.backups, os.path.basename(a))["path"], a)
        self.assertEqual(mc_backup.find_backup(self.backups, "latest")["path"], b)
        self.assertEqual(mc_backup.find_backup(self.backups, a)["path"], a)
        self.assertIsNone(mc_backup.find_backup(self.backups, "nope"))

    def test_encrypted_archives_are_listed(self):
        path = make_archive(self.backups, days_ago(0))
        shutil.copy(path, path + ".enc")
        names = {b["file"]: b["encrypted"] for b in mc_backup.list_backups(self.backups)}
        self.assertTrue(names[os.path.basename(path) + ".enc"])


class TestRetention(Tmp):

    def test_keep_n_newest(self):
        paths = [make_archive(self.backups, days_ago(n)) for n in (5, 4, 3, 2, 1)]
        res = mc_backup.apply_retention(self.backups, keep=2, days=0)
        self.assertEqual(res["files"], 3)
        self.assertEqual([os.path.exists(p) for p in paths], [False, False, False, True, True])

    def test_days_window(self):
        old = make_archive(self.backups, days_ago(40))
        mid = make_archive(self.backups, days_ago(10))
        new = make_archive(self.backups, days_ago(0))
        mc_backup.apply_retention(self.backups, keep=0, days=30)
        self.assertEqual([os.path.exists(p) for p in (old, mid, new)], [False, True, True])
        self.assertFalse(os.path.exists(os.path.dirname(old)))

    def test_newest_is_never_deleted_even_when_too_old(self):
        only = make_archive(self.backups, days_ago(400))
        mc_backup.apply_retention(self.backups, keep=1, days=7)
        self.assertTrue(os.path.exists(only))
        a = make_archive(self.backups, days_ago(500))
        mc_backup.apply_retention(self.backups, keep=0, days=7)
        self.assertTrue(os.path.exists(only))
        self.assertFalse(os.path.exists(a))

    def test_disabled_rules_delete_nothing(self):
        paths = [make_archive(self.backups, days_ago(n)) for n in (900, 500)]
        mc_backup.apply_retention(self.backups, keep=0, days=0)
        self.assertTrue(all(os.path.exists(p) for p in paths))

    def test_both_rules_combine(self):
        paths = [make_archive(self.backups, days_ago(n)) for n in (50, 3, 2, 1)]
        mc_backup.apply_retention(self.backups, keep=3, days=10)
        self.assertEqual([os.path.exists(p) for p in paths], [False, True, True, True])

    def test_foreign_files_untouched(self):
        keep = os.path.join(self.backups, "notes.txt")
        open(keep, "w").close()
        make_archive(self.backups, days_ago(100))
        make_archive(self.backups, days_ago(0))
        mc_backup.apply_retention(self.backups, keep=1, days=1)
        self.assertTrue(os.path.exists(keep))


class Server(Tmp):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.server, "world", "region"))
        for name, text in (("world/level.dat", "CURRENT"), ("world/region/r.0.0.mca", "old")):
            with open(os.path.join(self.server, name), "w") as f:
                f.write(text)
        self.config = {"dossier_serveur": self.server, "dossier_backup": self.backups, "nom_serveur": "Srv",
                       "mode_maintenance": 1, "stop_reason": "user", "always_on": 1}
        for target in ("mc_servers.update_cached_ports",):
            p = mock.patch(target)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(mc_core, "is_server_running", return_value=False)
        p.start()
        self.addCleanup(p.stop)


class TestRestore(Server):

    def level(self):
        with open(os.path.join(self.server, "world", "level.dat")) as f:
            return f.read()

    def test_restore_replaces_world_and_keeps_a_safety_backup(self):
        arch = make_archive(self.backups, days_ago(1), size=3)
        res = mc_api.backup_restore("s", self.config, os.path.basename(arch)[:-4])
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.level(), "xxx")
        self.assertEqual(os.listdir(self.server), ["world"])
        with zipfile.ZipFile(res["safety"]) as zf:
            self.assertEqual(zf.read("world/level.dat"), b"CURRENT")
        self.assertIn("pre-restore", os.path.basename(res["safety"]))

    def test_refused_while_running(self):
        arch = make_archive(self.backups, days_ago(1))
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
                mock.patch.object(mc_api, "_is_listening", return_value=True), \
                mock.patch.object(mc_core, "server_ready", return_value=True):
            res = mc_api.backup_restore("s", self.config, arch)
        self.assertEqual(res["code"], "server_running")
        self.assertEqual(self.level(), "CURRENT")

    def test_refused_when_the_daemon_would_relaunch_it(self):
        arch = make_archive(self.backups, days_ago(1))
        self.config["mode_maintenance"] = 0
        res = mc_api.backup_restore("s", self.config, arch)
        self.assertEqual(res["code"], "stop_first")
        self.assertEqual(self.level(), "CURRENT")

    def test_unknown_backup(self):
        self.assertEqual(mc_api.backup_restore("s", self.config, "zz")["code"], "backup_not_found")

    def test_archive_without_world_is_refused_before_any_change(self):
        arch = make_archive(self.backups, days_ago(1), level=False)
        res = mc_api.backup_restore("s", self.config, arch)
        self.assertEqual(res["code"], "no_world_in_archive")
        self.assertEqual(self.level(), "CURRENT")
        self.assertEqual(len(mc_backup.list_backups(self.backups)), 1)

    def test_corrupt_archive(self):
        d = os.path.join(self.backups, days_ago(1))
        os.makedirs(d)
        with open(os.path.join(d, "backup_manual_2026-01-01_00-00-00.zip"), "w") as f:
            f.write("not a zip")
        self.assertEqual(mc_api.backup_restore("s", self.config, "latest")["code"], "bad_archive")

    def test_zip_slip_is_refused(self):
        path = os.path.join(self.backups, "backup_manual_2026-01-01_00-00-00.zip")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("world/level.dat", "x")
            zf.writestr("world/../../evil.txt", "x")
        res = mc_api.backup_restore("s", self.config, path)
        self.assertEqual(res["code"], "unsafe_archive")
        self.assertEqual(self.level(), "CURRENT")
        self.assertFalse(os.path.exists(os.path.join(self.root, "evil.txt")))

    def test_swap_failure_rolls_back_to_the_original_world(self):
        arch = make_archive(self.backups, days_ago(1), size=3)
        real_rename = os.rename

        def flaky(src, dst):
            if os.path.basename(src) == "world" and os.sep + "extract" + os.sep in src:
                raise OSError("disk error")
            return real_rename(src, dst)
        with mock.patch("os.rename", flaky):
            res = mc_api.backup_restore("s", self.config, arch)
        self.assertEqual(res["code"], "swap_failed")
        self.assertEqual(self.level(), "CURRENT")
        self.assertEqual(os.listdir(self.server), ["world"])

    def test_other_dimensions_of_the_old_world_are_replaced_too(self):
        os.makedirs(os.path.join(self.server, "world_nether"))
        arch = make_archive(self.backups, days_ago(1))
        self.assertTrue(mc_api.backup_restore("s", self.config, arch)["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.server, "world_nether")))

    def test_encrypted_archive_needs_its_key(self):
        arch = make_archive(self.backups, days_ago(1))
        shutil.move(arch, arch + ".enc")
        res = mc_api.backup_restore("s", self.config, arch + ".enc")
        self.assertEqual(res["code"], "encrypt_key_missing")

    @unittest.skipUnless(shutil.which("openssl"), "openssl missing")
    def test_encrypt_decrypt_roundtrip_through_restore(self):
        arch = make_archive(self.backups, days_ago(1), size=4)
        key = os.path.join(self.root, "key")
        with open(key, "w") as f:
            f.write("correct horse battery staple\n")
        enc = os.path.join(self.root, "backup_manual_2026-01-02_00-00-00.zip.enc")
        mc_backup.encrypt(arch, enc, key)
        self.assertNotEqual(Path(enc).read_bytes()[:4], b"PK\x03\x04")
        self.config["backup_encrypt_key_file"] = key
        res = mc_api.backup_restore("s", self.config, enc)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.level(), "xxxx")


class TestBackupServer(Server):

    def test_retention_applied_and_remote_push_called(self):
        make_archive(self.backups, days_ago(5))
        make_archive(self.backups, days_ago(4))
        self.config.update(backup_keep=2, backup_remotes=[{"name": "r", "type": "s3"}])
        with mock.patch.object(mc_backup, "push_all", return_value=[("r", True, "x")]) as push:
            ok, msg = mc_core.backup_server(self.config)
        self.assertTrue(ok, msg)
        self.assertEqual(len(mc_backup.list_backups(self.backups)), 2)
        push.assert_called_once()

    def test_remote_failure_keeps_local_backup_and_alerts(self):
        self.config.update(backup_remotes=[{"name": "r", "type": "s3"}])
        with mock.patch.object(mc_backup, "push_all", return_value=[("r", False, "s3_failed: boom")]), \
                mock.patch.object(mc_core, "_alert") as alert:
            ok, msg = mc_core.backup_server(self.config)
        self.assertTrue(ok)
        self.assertIn("boom", msg)
        self.assertEqual(alert.call_args[0][1], "backup_failed")
        self.assertEqual(len(mc_backup.list_backups(self.backups)), 1)

    def test_safety_backup_skips_retention_and_remotes(self):
        make_archive(self.backups, days_ago(5))
        self.config.update(backup_keep=1, backup_remotes=[{"name": "r", "type": "s3"}])
        with mock.patch.object(mc_backup, "push_all") as push:
            ok, _ = mc_core.backup_server(self.config, "pre-restore", housekeeping=False)
        self.assertTrue(ok)
        push.assert_not_called()
        self.assertEqual(len(mc_backup.list_backups(self.backups)), 2)

    def test_running_server_is_frozen_then_thawed_before_zipping(self):
        rcon = []
        order = []
        real_zip = zipfile.ZipFile

        def zipper(*a, **k):
            order.append("zip")
            return real_zip(*a, **k)
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
                mock.patch.object(mc_core, "send_rcon", side_effect=lambda c, cmd: rcon.append(cmd) or order.append(cmd) or True), \
                mock.patch.object(mc_core.time, "sleep"), \
                mock.patch("zipfile.ZipFile", zipper):
            ok, msg = mc_core.backup_server(self.config)
        self.assertTrue(ok, msg)
        self.assertEqual(rcon, ["save-off", "save-all flush", "save-on"])
        self.assertLess(order.index("save-on"), order.index("zip"))
        self.assertFalse(mc_api.is_frozen(self.config))

    def test_freeze_failure_aborts_and_leaves_saving_on(self):
        calls = []
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
                mock.patch.object(mc_core, "send_rcon", side_effect=lambda c, cmd: calls.append(cmd) or cmd == "save-on"):
            ok, _ = mc_core.backup_server(self.config)
        self.assertFalse(ok)
        self.assertEqual(calls[-1], "save-on")
        self.assertFalse(mc_api.is_frozen(self.config))

    def test_existing_freeze_is_left_to_its_owner(self):
        mc_api.freeze(self.config)
        calls = []
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
                mock.patch.object(mc_core, "send_rcon", side_effect=lambda c, cmd: calls.append(cmd) or True):
            ok, _ = mc_core.backup_server(self.config)
        self.assertTrue(ok)
        self.assertEqual(calls, [])
        self.assertTrue(mc_api.is_frozen(self.config))

    def test_failed_zip_thaws_and_reports(self):
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
                mock.patch.object(mc_core, "send_rcon", return_value=True), \
                mock.patch.object(mc_core.time, "sleep"), \
                mock.patch("zipfile.ZipFile", side_effect=OSError("full")):
            ok, _ = mc_core.backup_server(self.config)
        self.assertFalse(ok)
        self.assertFalse(mc_api.is_frozen(self.config))


class TestRemoteConfig(Server):

    def add(self, *a, **k):
        with mock.patch("mc_servers.update_cached_ports"):
            return mc_api.backup_remote_add("s", self.config, *a, **k)

    def test_url_parsing(self):
        self.assertEqual(mc_backup.parse_remote_url("sftp://bob@h.example:2222/data/mc"),
                         ("sftp", {"host": "h.example", "port": 2222, "user": "bob", "path": "/data/mc"}))
        self.assertEqual(mc_backup.parse_remote_url("s3://bkt/a/b"), ("s3", {"bucket": "bkt", "prefix": "a/b"}))
        self.assertEqual(mc_backup.parse_remote_url("restic:sftp:u@h:/repo"), ("restic", {"repo": "sftp:u@h:/repo"}))
        for bad in ("ftp://x/y", "sftp://h", "s3://", "restic:", "nothing"):
            with self.assertRaises(mc_backup.BackupError):
                mc_backup.parse_remote_url(bad)

    def test_s3_remote_stored_with_secrets_private_and_masked_in_listing(self):
        res = self.add("cloud", "s3://bkt/mc", access_key="AK", secret_key="SK", endpoint="https://minio.lan:9000",
                       region="fr-par")
        self.assertTrue(res["ok"], res)
        mode = stat.S_IMODE(os.stat(os.path.join(self.server, "config.json")).st_mode)
        self.assertEqual(mode, 0o600)
        stored = mc_config.load_config(self.server)["backup_remotes"][0]
        self.assertEqual((stored["secret_key"], stored["endpoint"], stored["region"]), ("SK", "https://minio.lan:9000", "fr-par"))
        listed = mc_api.backup_remote_list("s", self.config)
        self.assertNotIn("SK", json.dumps(listed))
        self.assertEqual(listed["remotes"][0]["target"], "s3://bkt/mc (https://minio.lan:9000)")

    def test_s3_needs_keys_and_a_safe_endpoint(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AWS_ACCESS_KEY_ID", None)
            os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
            self.assertEqual(self.add("c", "s3://b/p")["code"], "s3_credentials_missing")
        self.assertEqual(self.add("c", "s3://b/p", access_key="a", secret_key="b", endpoint="http://example.com")["code"], "bad_url")

    def test_restic_password_goes_to_a_600_file(self):
        res = self.add("rs", "restic:/mnt/backups", password="hunter2")
        self.assertTrue(res["ok"], res)
        pw = mc_config.load_config(self.server)["backup_remotes"][0]["password_file"]
        self.assertEqual(Path(pw).read_text(), "hunter2")
        self.assertEqual(stat.S_IMODE(os.stat(pw).st_mode), 0o600)
        self.assertEqual(self.add("rs2", "restic:/x")["code"], "restic_password_missing")

    def test_existing_password_file_is_tightened(self):
        pw = os.path.join(self.root, "pw")
        Path(pw).write_text("x")
        os.chmod(pw, 0o644)
        self.assertTrue(self.add("rs", "restic:/x", password_file=pw)["ok"])
        self.assertEqual(stat.S_IMODE(os.stat(pw).st_mode), 0o600)

    def test_sftp_key_must_exist_and_names_are_unique(self):
        self.assertEqual(self.add("a", "sftp://u@h/p", key="/nonexistent")["code"], "key_not_found")
        self.assertTrue(self.add("a", "sftp://u@h/p")["ok"])
        self.assertEqual(self.add("a", "sftp://u@h/p")["code"], "remote_exists")
        self.assertEqual(self.add("bad name", "sftp://u@h/p")["code"], "bad_remote_name")
        self.assertEqual(self.add("b", "gopher://h")["code"], "bad_remote_url")

    def test_remove(self):
        self.add("a", "sftp://u@h/p")
        with mock.patch("mc_servers.update_cached_ports"):
            self.assertTrue(mc_api.backup_remote_remove("s", self.config, "a")["ok"])
            self.assertEqual(mc_api.backup_remote_remove("s", self.config, "a")["code"], "remote_not_found")
        self.assertNotIn("backup_remotes", self.config)


def completed(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class TestTransports(Server):

    def archive(self):
        return make_archive(self.backups, days_ago(0))

    def test_sftp_push_uses_batch_mode_key_and_port(self):
        remote = {"name": "r", "type": "sftp", "host": "h.example", "port": 2222, "user": "bob",
                  "path": "/data/mc", "key": "/k/id"}
        with mock.patch.object(mc_backup, "which", return_value="/usr/bin/sftp"), \
                mock.patch.object(mc_backup, "_run", return_value=completed()) as run:
            name = mc_backup.push(remote, self.archive(), "srv")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:3], ["sftp", "-b", "-"])
        self.assertIn("BatchMode=yes", cmd)
        self.assertEqual(cmd[cmd.index("-P") + 1], "2222")
        self.assertEqual(cmd[cmd.index("-i") + 1], "/k/id")
        self.assertEqual(cmd[-1], "bob@h.example")
        batch = run.call_args[1]["input"]
        self.assertTrue(batch.startswith("put "))
        self.assertIn(f'"/data/mc/{name}"', batch)

    def test_sftp_failure_surfaces_stderr(self):
        remote = {"name": "r", "type": "sftp", "host": "h", "path": "/p"}
        with mock.patch.object(mc_backup, "which", return_value="/usr/bin/sftp"), \
                mock.patch.object(mc_backup, "_run", return_value=completed(1, "", "Permission denied")):
            with self.assertRaises(mc_backup.BackupError) as ctx:
                mc_backup.push(remote, self.archive(), "srv")
        self.assertIn("Permission denied", str(ctx.exception))

    def test_sftp_missing_tool(self):
        with mock.patch.object(mc_backup, "which", return_value=None):
            with self.assertRaises(mc_backup.BackupError) as ctx:
                mc_backup.push({"name": "r", "type": "sftp", "host": "h", "path": "/p"}, self.archive(), "s")
        self.assertEqual(ctx.exception.code, "tool_missing")

    def test_s3_push_key_layout(self):
        remote = {"name": "c", "type": "s3", "bucket": "bkt", "prefix": "mc", "access_key": "a",
                  "secret_key": "b", "region": "eu-west-1"}
        with mock.patch.object(mc_backup.mc_s3.S3Client, "put_file") as put:
            name = mc_backup.push(remote, self.archive(), "Survie")
        key, path = put.call_args[0]
        self.assertEqual(key, f"mc/Survie/{name}")
        self.assertTrue(path.endswith(".zip"))

    def test_s3_error_is_wrapped(self):
        remote = {"name": "c", "type": "s3", "bucket": "b", "access_key": "a", "secret_key": "b"}
        err = mc_backup.mc_s3.S3Error("http_403", "denied")
        with mock.patch.object(mc_backup.mc_s3.S3Client, "put_file", side_effect=err):
            with self.assertRaises(mc_backup.BackupError) as ctx:
                mc_backup.push(remote, self.archive(), "s")
        self.assertEqual(ctx.exception.code, "s3_failed")

    def test_restic_backs_up_the_backup_folder_with_password_file_and_inits_when_needed(self):
        remote = {"name": "r", "type": "restic", "repo": "sftp:u@h:/repo", "password_file": "/pw"}
        seen = []

        def run(cmd, **kw):
            seen.append((cmd, kw["env"]))
            return completed(1, "", "no repo") if cmd[1:3] == ["cat", "config"] else completed()
        with mock.patch.object(mc_backup, "which", return_value="/usr/bin/restic"), \
                mock.patch.object(mc_backup, "_run", side_effect=run):
            mc_backup.push(remote, self.archive(), "srv", backup_dir=self.backups)
        verbs = [c[1] for c, _ in seen]
        self.assertEqual(verbs, ["cat", "init", "backup"])
        cmd, env = seen[2]
        self.assertEqual(cmd[-1], self.backups)
        self.assertEqual(env["RESTIC_REPOSITORY"], "sftp:u@h:/repo")
        self.assertEqual(env["RESTIC_PASSWORD_FILE"], "/pw")
        self.assertNotIn("-p", cmd)

    def test_encrypted_upload_sends_the_enc_file_and_removes_the_temp(self):
        key = os.path.join(self.root, "key")
        Path(key).write_text("k")
        remote = {"name": "c", "type": "s3", "bucket": "b", "access_key": "a", "secret_key": "b"}
        sent = {}

        def fake_encrypt(src, dst, key_file):
            Path(dst).write_text("ENC")
            sent["dst"] = dst

        def fake_put(self, key, path):
            sent["key"], sent["path"], sent["exists"] = key, path, os.path.exists(path)
        with mock.patch.object(mc_backup, "which", return_value="/usr/bin/openssl"), \
                mock.patch.object(mc_backup, "encrypt", fake_encrypt), \
                mock.patch.object(mc_backup.mc_s3.S3Client, "put_file", fake_put):
            name = mc_backup.push(remote, self.archive(), "s", key_file=key)
        self.assertTrue(name.endswith(".zip.enc"))
        self.assertTrue(sent["key"].endswith(".zip.enc") and sent["exists"])
        self.assertFalse(os.path.exists(sent["dst"]))

    def test_encryption_without_openssl_warns_and_sends_clear(self):
        key = os.path.join(self.root, "key")
        Path(key).write_text("k")
        remote = {"name": "c", "type": "s3", "bucket": "b", "access_key": "a", "secret_key": "b"}
        warned = []
        with mock.patch.object(mc_backup, "which", return_value=None), \
                mock.patch.object(mc_backup.mc_s3.S3Client, "put_file"):
            name = mc_backup.push(remote, self.archive(), "s", key_file=key, warn=warned.append)
        self.assertTrue(name.endswith(".zip"))
        self.assertEqual(warned, ["encrypt_unavailable"])

    def test_missing_key_file_refuses_to_send_in_clear(self):
        remote = {"name": "c", "type": "s3", "bucket": "b", "access_key": "a", "secret_key": "b"}
        with mock.patch.object(mc_backup, "which", return_value="/usr/bin/openssl"), \
                mock.patch.object(mc_backup.mc_s3.S3Client, "put_file") as put:
            with self.assertRaises(mc_backup.BackupError) as ctx:
                mc_backup.push(remote, self.archive(), "s", key_file="/nonexistent/key")
        self.assertEqual(ctx.exception.code, "encrypt_key_missing")
        put.assert_not_called()

    def test_push_all_isolates_failures(self):
        self.config.update(backup_remotes=[{"name": "a", "type": "s3", "bucket": "b", "access_key": "x", "secret_key": "y"},
                                           {"name": "b", "type": "s3", "bucket": "b", "access_key": "x", "secret_key": "y"}])
        calls = []

        def put(self_, key, path):
            calls.append(key)
            if len(calls) == 1:
                raise mc_backup.mc_s3.S3Error("network", "down")
        with mock.patch.object(mc_backup.mc_s3.S3Client, "put_file", put):
            out = mc_backup.push_all(self.config, self.archive())
        self.assertEqual([(n, ok) for n, ok, _ in out], [("a", False), ("b", True)])

    def test_remote_test_reports_each_destination(self):
        self.config["backup_remotes"] = [
            {"name": "ok", "type": "s3", "bucket": "b", "access_key": "x", "secret_key": "y"},
            {"name": "ko", "type": "sftp", "host": "h", "path": "/p"}]
        with mock.patch.object(mc_backup.mc_s3.S3Client, "list", return_value=[]), \
                mock.patch.object(mc_backup, "which", return_value="/usr/bin/sftp"), \
                mock.patch.object(mc_backup, "_run", return_value=completed(255, "", "Connection refused")):
            res = mc_api.backup_remote_test("s", self.config)
        self.assertFalse(res["ok"])
        self.assertEqual(res["failed"], "ko")
        self.assertEqual([c["ok"] for c in res["checks"]], [True, False])
        self.assertEqual(mc_api.backup_remote_test("s", self.config, "zz")["code"], "remote_not_found")
        self.assertEqual(mc_api.backup_remote_test("s", {})["code"], "no_remote")


class TestCli(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = os.path.join(tmp.name, "data")
        self.folder = os.path.join(tmp.name, "srv")
        self.backups = os.path.join(tmp.name, "bk")
        os.makedirs(self.data)
        os.makedirs(os.path.join(self.folder, "world"))
        self.level_file = os.path.join(self.folder, "world", "level.dat")
        with open(self.level_file, "w") as f:
            f.write("CUR")
        with open(os.path.join(self.folder, "config.json"), "w") as f:
            json.dump({"port": 1, "rcon_port": 2, "mcrcon_pass": "x", "always_on": 1, "nom_serveur": "a",
                       "mode_maintenance": 1, "stop_reason": "user", "dossier_backup": self.backups}, f)
        with open(os.path.join(self.data, "servers.json"), "w") as f:
            json.dump({"active": "a", "servers": {"a": {"id": 1, "dossier_serveur": self.folder}}}, f)
        self.env = dict(os.environ, MCMANAGER_DATA_DIR=self.data, NO_COLOR="1")
        self.archive = make_archive(self.backups, days_ago(1), size=3)

    def level(self):
        with open(self.level_file) as f:
            return f.read()

    def mc(self, *args):
        return subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), *args], capture_output=True,
                              text=True, env=self.env, stdin=subprocess.DEVNULL, timeout=60)

    def test_list_json(self):
        res = self.mc("backup", "list", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        doc = json.loads(res.stdout)
        self.assertEqual((doc["schema"], doc["ok"], doc["count"]), (1, True, 1))
        self.assertEqual(doc["backups"][0]["id"], os.path.basename(self.archive)[:-4])

    def test_list_text(self):
        res = self.mc("backup", "list")
        self.assertEqual(res.returncode, 0)
        self.assertIn(os.path.basename(self.archive)[:-4], res.stdout)

    def test_restore_without_yes_is_refused_when_not_interactive(self):
        res = self.mc("backup", "restore", "latest")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(self.level(), "CUR")

    def test_restore_usage_and_unknown_server_and_unknown_backup(self):
        self.assertEqual(self.mc("backup", "restore").returncode, 2)
        self.assertEqual(self.mc("backup", "list", "zz").returncode, 3)
        self.assertEqual(self.mc("backup", "restore", "nope", "--yes").returncode, 1)
        self.assertEqual(self.mc("backup", "remote", "frobnicate").returncode, 2)

    def test_remote_add_list_test_remove(self):
        res = self.mc("backup", "remote", "add", "cloud", "s3://bkt/p", "--access-key", "AK", "--secret-key", "SK", "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        listed = json.loads(self.mc("backup", "remote", "list", "--json").stdout)
        self.assertEqual(listed["remotes"][0]["target"], "s3://bkt/p")
        self.assertNotIn("SK", self.mc("backup", "remote", "list", "--json").stdout)
        self.assertEqual(self.mc("backup", "remote", "add", "cloud", "s3://b/p", "--access-key", "A", "--secret-key", "S").returncode, 1)
        self.assertEqual(self.mc("backup", "remote", "add", "x", "bogus://b").returncode, 2)
        self.assertEqual(self.mc("backup", "remote", "remove", "cloud").returncode, 0)
        self.assertEqual(self.mc("backup", "remote", "remove", "cloud").returncode, 1)

    def test_restore_with_yes_then_world_replaced(self):
        res = self.mc("backup", "restore", os.path.basename(self.archive)[:-4], "--yes", "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(json.loads(res.stdout)["code"], "backup_restored")
        self.assertEqual(self.level(), "xxx")


if __name__ == "__main__":
    unittest.main(verbosity=2)
