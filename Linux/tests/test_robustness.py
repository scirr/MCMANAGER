"""
test_robustness.py — Regression tests for the 2.4.9 robustness fixes:
BOM-tolerant JSON, unreadable files isolated, server.properties sync,
RCON reads on a closed socket, TIME_WAIT ports, process identity by
working directory, systemd unit drift, CLI exit codes (no traceback).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..")
sys.path.insert(0, APP)

import mc_servers
import mc_config
import mc_core


class TestReadJson(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_bom_is_accepted(self):
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w", encoding="utf-8-sig") as f:
            json.dump({"port": 25565}, f)
        self.assertEqual(mc_servers.read_json(path), {"port": 25565})

    def test_missing_file_returns_default_copy(self):
        default = {"a": []}
        value = mc_servers.read_json(os.path.join(self.tmp, "nope.json"), default)
        self.assertEqual(value, default)
        self.assertIsNot(value, default)

    def test_invalid_json_raises_data_file_error(self):
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w") as f:
            f.write("{bad")
        with self.assertRaises(mc_servers.DataFileError) as ctx:
            mc_servers.read_json(path)
        self.assertEqual(ctx.exception.path, path)

    def test_load_config_with_bom(self):
        with open(os.path.join(self.tmp, "config.json"), "w", encoding="utf-8-sig") as f:
            json.dump({"mode_maintenance": 1}, f)
        self.assertEqual(mc_config.load_config(self.tmp)["mode_maintenance"], 1)

    def test_corrupt_registry_is_not_read_as_empty(self):
        # Reading an unreadable registry as "no servers" stopped supervision of
        # every server and let the next write erase the real file.
        path = os.path.join(self.tmp, "servers.json")
        with open(path, "w") as f:
            f.write("{oops")
        with mock.patch.object(mc_servers, "REGISTRY_FILE", path):
            with self.assertRaises(mc_servers.DataFileError):
                mc_servers.load_registry()
        with open(path) as f:
            self.assertEqual(f.read(), "{oops")

    def test_unreadable_webhooks_fall_back_to_templates(self):
        with open(os.path.join(self.tmp, "webhooks.json"), "w") as f:
            f.write("{bad")
        templates = mc_config.load_webhooks(self.tmp)
        self.assertIn("stop", templates)
        with open(os.path.join(self.tmp, "webhooks.json")) as f:
            self.assertEqual(f.read(), "{bad")  # left alone for the user to fix


class TestServerPropertiesSync(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.props = os.path.join(self.tmp, "server.properties")
        with open(self.props, "w") as f:
            f.write("#Minecraft server properties\nserver-port=25566\nmotd=Héllo\nenable-rcon=false\n")
        self.config = {"dossier_serveur": self.tmp, "port": 25565,
                       "mcrcon_pass": "secret", "rcon_port": 25575}

    def _read(self):
        with open(self.props, encoding="utf-8") as f:
            return f.read()

    def test_dry_run_reports_without_writing(self):
        before = self._read()
        changes = mc_core.sync_server_properties(self.config, apply=False)
        keys = {k for k, _, _ in changes}
        self.assertEqual(keys, {"server-port", "enable-rcon", "rcon.port", "rcon.password"})
        self.assertEqual(self._read(), before)

    def test_apply_fixes_managed_keys_and_keeps_the_rest(self):
        mc_core.sync_server_properties(self.config)
        text = self._read()
        self.assertIn("server-port=25565\n", text)
        self.assertIn("enable-rcon=true\n", text)
        self.assertIn("rcon.port=25575\n", text)
        self.assertIn("rcon.password=secret\n", text)
        self.assertIn("motd=Héllo\n", text)
        self.assertTrue(text.startswith("#Minecraft server properties\n"))
        self.assertEqual(mc_core.sync_server_properties(self.config), [])

    def test_no_properties_file_is_a_no_op(self):
        os.remove(self.props)
        self.assertEqual(mc_core.sync_server_properties(self.config), [])
        self.assertFalse(os.path.exists(self.props))


class TestRcon(unittest.TestCase):

    def test_closed_socket_does_not_spin(self):
        a, b = socket.socketpair()
        # Announce a 20-byte packet, send only 5 bytes, then close.
        b.sendall((20).to_bytes(4, "little") + b"12345")
        b.close()
        a.settimeout(2)
        self.assertEqual(mc_core.rcon_recv_packet(a), (None, None, None))
        a.close()


class TestPorts(unittest.TestCase):

    def test_time_wait_is_not_in_use(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen()
        c = socket.create_connection(("127.0.0.1", port))
        conn, _ = srv.accept()
        conn.close()  # server side closes first -> TIME_WAIT on the server port
        c.close()
        srv.close()
        self.assertFalse(mc_core._port_in_use(port))

    def test_listening_port_is_in_use_and_owner_found(self):
        srv = socket.socket()
        srv.bind(("0.0.0.0", 0))
        srv.listen()
        port = srv.getsockname()[1]
        try:
            self.assertTrue(mc_core._port_in_use(port))
            self.assertEqual(mc_core._port_listener_pid(port), os.getpid())
            pid, _prog = mc_core.port_occupant(port)
            self.assertEqual(pid, os.getpid())
        finally:
            srv.close()


class TestProcessIdentity(unittest.TestCase):

    def test_pid_in_other_folder_is_not_the_server(self):
        other = tempfile.mkdtemp()
        self.assertTrue(mc_core.is_pid_running(os.getpid(), os.getcwd()))
        self.assertFalse(mc_core.is_pid_running(os.getpid(), other))

    def test_dead_pid(self):
        proc = subprocess.Popen(["true"])
        proc.wait()
        self.assertFalse(mc_core.is_pid_running(proc.pid))

    def test_zombie_is_not_running(self):
        proc = subprocess.Popen(["true"])
        # Wait for it to exit without reaping it.
        for _ in range(100):
            if mc_core._proc_state(proc.pid) == "Z":
                break
            import time
            time.sleep(0.02)
        self.assertEqual(mc_core._proc_state(proc.pid), "Z")
        with mock.patch("os.waitpid", side_effect=ChildProcessError):
            self.assertFalse(mc_core.is_pid_running(proc.pid))
        proc.wait()

    def test_no_java_in_empty_folder(self):
        self.assertEqual(mc_core.server_java_pids(tempfile.mkdtemp()), [])

    def test_is_server_running_ignores_foreign_port_holder(self):
        tmp = tempfile.mkdtemp()
        srv = socket.socket()
        srv.bind(("0.0.0.0", 0))
        srv.listen()
        port = srv.getsockname()[1]
        try:
            config = {"dossier_serveur": tmp, "port": port}
            self.assertFalse(mc_core.is_server_running(config))
            self.assertFalse(os.path.exists(os.path.join(tmp, "server.pid")))
        finally:
            srv.close()

    def test_java_major_version(self):
        self.assertEqual(mc_core.java_major_version('openjdk version "21.0.4" 2024-07-16'), 21)
        self.assertEqual(mc_core.java_major_version('java version "1.8.0_402"'), 8)
        self.assertEqual(mc_core.java_major_version('openjdk version "25" 2025-09-16'), 25)
        self.assertIsNone(mc_core.java_major_version("garbage"))


class TestServiceUnit(unittest.TestCase):

    def _check(self, content):
        path = os.path.join(tempfile.mkdtemp(), "mc_manager.service")
        if content is not None:
            with open(path, "w") as f:
                f.write(content)
        with mock.patch.object(mc_config, "SERVICE_FILE", path):
            return mc_config.check_service_unit()

    def test_missing(self):
        self.assertEqual(self._check(None)[0], "missing")

    def test_current_unit_is_ok(self):
        self.assertEqual(self._check(mc_config._service_unit_content("cris")), ("ok", []))

    def test_other_python_and_env_are_ignored(self):
        unit = mc_config._service_unit_content("cris").replace(
            "ExecStart=" + (sys.executable or "/usr/bin/python3"), "ExecStart=/opt/py/bin/python3")
        unit = unit.replace("[Service]\n", "[Service]\nEnvironment=\"MCMANAGER_DATA_DIR=/srv\"\n")
        self.assertEqual(self._check(unit)[0], "ok")

    def test_missing_killmode_is_outdated(self):
        unit = mc_config._service_unit_content("cris").replace("KillMode=process\n", "")
        state, diffs = self._check(unit)
        self.assertEqual(state, "outdated")
        self.assertIn("KillMode", [k for k, _, _ in diffs])


class TestCliExitCodes(unittest.TestCase):
    """Run the real CLI in a subprocess against a throwaway data dir."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.env = dict(os.environ, MCMANAGER_DATA_DIR=self.data)
        self.env.pop("MCMANAGER_DEBUG", None)

    def _mc(self, *args):
        return subprocess.run([sys.executable, os.path.join(APP, "mc_cli.py"), *args],
                              capture_output=True, text=True, env=self.env,
                              stdin=subprocess.DEVNULL, timeout=60)

    def _registry(self, servers, active=None, encoding="utf-8"):
        with open(os.path.join(self.data, "servers.json"), "w", encoding=encoding) as f:
            json.dump({"active": active, "servers": servers}, f)

    def test_version_is_zero(self):
        self.assertEqual(self._mc("version").returncode, 0)

    def test_usage_error_is_two(self):
        self.assertEqual(self._mc("no-such-command").returncode, 2)

    def test_no_server_is_three(self):
        self._registry({})
        self.assertEqual(self._mc("start").returncode, 3)

    def test_unknown_target_is_three(self):
        folder = tempfile.mkdtemp()
        self._registry({"a": {"id": 1, "dossier_serveur": folder}}, "a")
        self.assertEqual(self._mc("backup", "zz").returncode, 3)

    def test_corrupt_registry_is_one_without_traceback(self):
        with open(os.path.join(self.data, "servers.json"), "w") as f:
            f.write("{nope")
        result = self._mc("status")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertIn("servers.json", result.stdout)

    def test_bom_registry_and_config_work(self):
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "config.json"), "w", encoding="utf-8-sig") as f:
            json.dump({"port": 25565, "mode_maintenance": 1}, f)
        self._registry({"a": {"id": 1, "dossier_serveur": folder}}, "a", encoding="utf-8-sig")
        result = self._mc("status")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("\x1b[", result.stdout)  # no colour codes when piped

    def test_stop_on_offline_server_is_zero_and_sets_maintenance(self):
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "config.json"), "w") as f:
            json.dump({"port": 1, "mode_maintenance": 0}, f)
        self._registry({"a": {"id": 1, "dossier_serveur": folder}}, "a")
        self.assertEqual(self._mc("stop").returncode, 0)
        with open(os.path.join(folder, "config.json")) as f:
            self.assertEqual(json.load(f)["mode_maintenance"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
