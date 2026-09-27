"""
test_hardening.py — 2.8.0: private files, run/ permissions, hardened unit,
polkit rule, sleep listener limits, RCON exposure checks.
"""
import json
import os
import socket
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_config
import mc_core
import mc_doctor
import mc_ipc
import mc_servers
import mc_sleep


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class TestPrivateFiles(unittest.TestCase):

    def test_json_written_0600(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "config.json")
        with open(path, "w") as f:
            f.write("{}")
        os.chmod(path, 0o644)
        mc_servers._atomic_write_json(path, {"mcrcon_pass": "x"})
        self.assertEqual(_mode(path), 0o600)
        with open(path) as f:
            self.assertEqual(json.load(f), {"mcrcon_pass": "x"})

    def test_save_config_is_private(self):
        folder = tempfile.mkdtemp()
        with mock.patch.object(mc_servers, "update_cached_ports"):
            mc_config.save_config({"dossier_serveur": folder, "port": 1})
        self.assertEqual(_mode(mc_config.config_path(folder)), 0o600)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "needs root")
    def test_root_write_keeps_the_owner(self):
        folder = tempfile.mkdtemp()
        os.chown(folder, 4321, 4321)
        path = os.path.join(folder, "servers.json")
        mc_servers._atomic_write_json(path, {})
        self.assertEqual((os.stat(path).st_uid, os.stat(path).st_gid), (4321, 4321))
        os.chown(path, 1234, 1234)
        mc_servers._atomic_write_json(path, {"a": 1})
        self.assertEqual(os.stat(path).st_uid, 1234)

    def test_doctor_tightens_permissions(self):
        path = os.path.join(tempfile.mkdtemp(), "config.json")
        with open(path, "w") as f:
            f.write("{}")
        os.chmod(path, 0o644)
        status, *_ = mc_doctor.check_private_file(path)
        self.assertEqual(status, "ok")
        self.assertEqual(_mode(path), 0o600)
        self.assertIsNone(mc_doctor.check_private_file(path))


class TestRunDir(unittest.TestCase):

    def test_run_dir_is_0700(self):
        base = tempfile.mkdtemp()
        run = os.path.join(base, "run")
        with mock.patch.object(mc_ipc, "BASE_DIR", base), \
             mock.patch.object(mc_ipc, "RUN_DIR", run), \
             mock.patch.object(mc_ipc, "HEARTBEAT_FILE", os.path.join(run, "hb")):
            mc_ipc.beat()
        self.assertEqual(_mode(run), 0o700)


class TestUnitAndPolkit(unittest.TestCase):

    def test_unit_is_hardened(self):
        unit = mc_config._unit_directives(mc_config._service_unit_content("cris"))
        for key, value in (("NoNewPrivileges", "yes"), ("PrivateTmp", "yes"), ("ProtectKernelTunables", "yes"),
                           ("ProtectKernelModules", "yes"), ("ProtectKernelLogs", "yes"),
                           ("LockPersonality", "yes"), ("KillMode", "process")):
            self.assertEqual(unit.get(key), value, key)
        self.assertIn("AF_INET", unit["RestrictAddressFamilies"])
        self.assertNotIn("MemoryDenyWriteExecute", unit)   # the JVM JIT needs it off

    def test_previous_unit_is_reported_outdated(self):
        old = "[Service]\nUser=cris\nWorkingDirectory=%s\nExecStart=/usr/bin/python3 %s\nRestart=on-failure\nRestartSec=10\nKillMode=process\nType=simple\n" % (
            mc_config.BASE_DIR, os.path.join(mc_config.BASE_DIR, "mc_daemon.py"))
        path = os.path.join(tempfile.mkdtemp(), "u.service")
        with open(path, "w") as f:
            f.write(old)
        with mock.patch.object(mc_config, "SERVICE_FILE", path):
            state, diffs = mc_config.check_service_unit()
        self.assertEqual(state, "outdated")
        self.assertIn("NoNewPrivileges", [k for k, _, _ in diffs])

    def test_polkit_rule_scope(self):
        rule = mc_config._polkit_rule_content("cris")
        self.assertIn('subject.user == "cris"', rule)
        self.assertIn('"mc_manager.service"', rule)
        self.assertIn("org.freedesktop.systemd1.manage-units", rule)
        self.assertNotIn("enable", rule)

    def test_no_polkit_rule_for_root_or_without_polkit(self):
        self.assertFalse(mc_config.install_polkit_rule("root"))
        with mock.patch.object(mc_config, "POLKIT_RULE_FILE", "/nonexistent/dir/rule"):
            self.assertFalse(mc_config.install_polkit_rule("cris"))


class TestSleepLimits(unittest.TestCase):

    def test_per_ip_limit(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        listener = mc_sleep.SleepListener("t", port, lambda: ("z", 1, "v", None), lambda n: "x")
        listener.start()
        self.assertTrue(listener.bound.wait(5))
        try:
            held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(mc_sleep.MAX_PER_IP)]
            time.sleep(0.3)
            extra = socket.create_connection(("127.0.0.1", port), timeout=5)
            extra.settimeout(3)
            try:
                data = extra.recv(1)
            except (ConnectionResetError, OSError):
                data = b""
            self.assertEqual(data, b"")          # refused at once
            for c in held:
                c.close()
            extra.close()
        finally:
            listener.stop()
        self.assertEqual(listener._per_ip, {})

    def test_close_wait_is_short(self):
        self.assertLessEqual(mc_sleep.CLIENT_CLOSE_WAIT, 3)


class TestRconExposure(unittest.TestCase):

    def test_listen_address(self):
        s = socket.socket()
        s.bind(("0.0.0.0", 0))
        s.listen()
        port = s.getsockname()[1]
        local = socket.socket()
        local.bind(("127.0.0.1", 0))
        local.listen()
        try:
            self.assertTrue(mc_core.listens_on_all_interfaces(port))
            self.assertFalse(mc_core.listens_on_all_interfaces(local.getsockname()[1]))
        finally:
            s.close()
            local.close()
        self.assertIsNone(mc_core.listens_on_all_interfaces(port))


if __name__ == "__main__":
    unittest.main(verbosity=2)
