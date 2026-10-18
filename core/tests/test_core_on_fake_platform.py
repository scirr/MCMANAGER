import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import mc_api
import mc_config
import mc_core
import mc_doctor
import mc_firewall
import mc_ipc
import mc_platform
import mc_servers
from fake_platform import FakePlatform


class FakePlatformCase(unittest.TestCase):
    """The core must reach the system only through `plat`: every real way into
    it is made to fail while a FakePlatform answers."""

    def use(self, **results):
        saved = mc_platform._Lazy._impl
        self.addCleanup(setattr, mc_platform._Lazy, "_impl", saved)
        self.fake = FakePlatform(**results)
        mc_platform.use(self.fake)
        for target in ("os.kill", "os.killpg", "subprocess.run", "subprocess.Popen"):
            patcher = mock.patch(target, side_effect=AssertionError(f"{target} reached the system"))
            patcher.start()
            self.addCleanup(patcher.stop)
        return self.fake

    def config(self, **extra):
        folder = tempfile.mkdtemp()
        return dict({"dossier_serveur": folder, "port": 25565, "rcon_port": 25575}, **extra)


class TestProcesses(FakePlatformCase):
    def test_status_follows_the_platform(self):
        config = self.config()
        fake = self.use(find_server_processes=[4321])
        self.assertTrue(mc_core.is_server_running(config))
        self.assertEqual(fake.called("find_server_processes"), [(config["dossier_serveur"],)])
        fake.results["find_server_processes"] = []
        self.assertFalse(mc_core.is_server_running(config))

    def test_recorded_pid_is_checked_against_the_server_folder(self):
        config = self.config()
        fake = self.use()
        fake.alive.add(77)
        mc_core._write_pid_file(config, 77)
        self.assertTrue(mc_core.is_server_running(config))
        self.assertIn((77, config["dossier_serveur"]), fake.called("process_alive"))

    def test_signals_go_through_terminate_and_kill(self):
        config = self.config()
        fake = self.use(find_server_processes=[500], terminate=True, kill=True)
        fake.alive.add(400)
        mc_core._write_pid_file(config, 400)
        self.assertTrue(mc_core._signal_server(config, "terminate"))
        self.assertEqual(sorted(a for a in fake.called("terminate")), [(400,), (500,)])
        self.assertTrue(mc_core._signal_server(config, "kill"))
        self.assertEqual(len(fake.called("kill")), 2)

    def test_listener_memory_and_uptime_come_from_the_platform(self):
        fake = self.use(port_in_use=True, port_listener=(9, "java"), process_memory=(2048, 7),
                        process_uptime=12.0)
        self.assertEqual(mc_core.port_occupant(25565), (9, "java"))
        self.assertEqual(mc_core.proc_memory(9), (2048, 7))
        self.assertEqual(mc_core.proc_uptime(9), 12.0)
        self.assertEqual(fake.called("port_in_use"), [(25565,)])

    def test_freeze_is_refused_where_suspend_is_unsupported(self):
        config = self.config(sleep_join_mode="hold", sleep_enabled=1, mcrcon_pass="x")
        self.use(find_server_processes=[1])
        self.assertFalse(mc_core.freeze_supported())
        res = mc_api.sleep_configure("a", config, freeze=True)
        self.assertEqual((res["ok"], res["code"]), (False, "unsupported_on_windows"))
        with mock.patch.object(mc_core, "send_rcon", return_value=True):
            self.assertEqual(mc_core.suspend_server(config), (False, "unsupported"))
            self.assertEqual(mc_api.suspend("a", config)["code"], "unsupported_on_windows")
        self.assertFalse(os.path.exists(os.path.join(config["dossier_serveur"], mc_core.SUSPENDED_MARKER)))


class TestCliUnsupported(unittest.TestCase):
    def _run(self, argv):
        import contextlib
        import io
        import mc_cli
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["mc"] + argv), \
             mock.patch.object(mc_cli, "main", side_effect=mc_platform.Unsupported("suspend")), \
             mock.patch.object(mc_cli, "_setup_output"), \
             contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            mc_cli.run()
        return stop.exception.code, out.getvalue()

    def test_json_error_is_stable(self):
        code, out = self._run(["sleep", "enable", "--freeze", "on", "--json"])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual((data["ok"], data["code"]), (False, "unsupported_on_windows"))

    def test_text_message_exists_in_both_languages(self):
        import mc_lang
        self.assertTrue(mc_lang._FR["res_unsupported_on_windows"])
        self.assertTrue(mc_lang._EN["res_unsupported_on_windows"])


class TestFirewall(FakePlatformCase):
    def test_allow_and_remove_are_delegated_with_the_server_label(self):
        fake = self.use(firewall_name="ufw", firewall_port_open=False)
        self.assertEqual(mc_firewall.ensure_game_port_rule(25566, old_port=25565, name="survie"), (True, None))
        self.assertEqual(fake.called("firewall_remove"), [(25565, "tcp", "survie")])
        self.assertEqual(fake.called("firewall_allow"), [(25566, "tcp", "survie")])

    def test_failure_returns_the_platform_manual_command(self):
        self.use(firewall_name="netsh", firewall_port_open=False, firewall_allow=(False, "denied"),
                 firewall_manual_command="netsh advfirewall ...")
        self.assertEqual(mc_firewall.ensure_game_port_rule(25565, name="s"), (False, "netsh advfirewall ..."))

    def test_open_port_is_left_alone_and_no_firewall_gives_the_command(self):
        fake = self.use(firewall_name="ufw", firewall_port_open=True)
        self.assertEqual(mc_firewall.ensure_game_port_rule(25565, name="s"), (True, None))
        self.assertEqual(fake.called("firewall_allow"), [])
        fake.results["firewall_name"] = None
        self.assertEqual(mc_firewall.ensure_game_port_rule(25565, name="s"), (False, "fw-allow"))


class TestFiles(FakePlatformCase):
    def test_private_files_and_secure_file(self):
        fake = self.use()
        path = os.path.join(tempfile.mkdtemp(), "servers.json")
        mc_servers._atomic_write_json(path, {"a": 1})
        self.assertEqual(json.loads(fake.files[path]), {"a": 1})
        self.assertFalse(os.path.exists(path))

    def test_doctor_asks_the_platform_to_tighten_permissions(self):
        fake = self.use(file_is_private=(False, "fix it"), secure_file=True)
        path = os.path.join(tempfile.mkdtemp(), "config.json")
        with open(path, "w") as f:
            f.write("{}")
        status, *_ = mc_doctor.check_private_file(path)
        self.assertEqual(status, "ok")
        self.assertEqual(fake.called("secure_file"), [(path,)])
        fake.results.update(secure_file=False)
        status, _label, _detail, fix = mc_doctor.check_private_file(path)
        self.assertEqual((status, fix), ("warn", "fix it"))
        fake.results["file_is_private"] = (None, "")
        self.assertIsNone(mc_doctor.check_private_file(path))

    def test_daemon_heartbeat_uses_process_alive(self):
        fake = self.use()
        base = tempfile.mkdtemp()
        run = os.path.join(base, "run")
        with mock.patch.object(mc_ipc, "RUN_DIR", run), \
             mock.patch.object(mc_ipc, "HEARTBEAT_FILE", os.path.join(run, "hb")):
            mc_ipc.beat()
            self.assertEqual(list(fake.files), [os.path.join(run, "hb")])
            with open(os.path.join(run, "hb"), "w") as f:
                f.write(fake.files[os.path.join(run, "hb")])
            self.assertFalse(mc_ipc.daemon_listening())
            fake.alive.add(os.getpid())
            self.assertTrue(mc_ipc.daemon_listening())


class TestService(FakePlatformCase):
    def test_doctor_service_check(self):
        self.use(service_installed=True, service_running=True)
        self.assertEqual(mc_doctor._check_daemon_service()[0], True)
        self.fake.results["service_running"] = False
        self.assertEqual(mc_doctor._check_daemon_service()[0], False)
        self.fake.results["service_installed"] = False
        self.assertEqual(mc_doctor._check_daemon_service()[1], mc_core.T["doctor_svc_not_inst"])

    def test_unit_drift_and_restart_are_delegated(self):
        fake = self.use(service_unit_drift=("outdated", [("KillMode", None, "process")]),
                        service_control=("no_permission", ""))
        self.assertEqual(mc_config.check_service_unit()[0], "outdated")
        import mc_update
        self.assertFalse(mc_update._restart_daemon())
        self.assertEqual(fake.called("service_control"), [("restart",)])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestLinuxBehaviourKept(unittest.TestCase):
    def test_daemon_error_shows_return_code_and_output(self):
        import contextlib
        import io
        import mc_cli
        saved = mc_platform._Lazy._impl
        self.addCleanup(setattr, mc_platform._Lazy, "_impl", saved)
        import platform_linux
        mc_platform.use(platform_linux)
        done = subprocess.CompletedProcess([], 3, stdout="out ", stderr="Job failed\n")
        out = io.StringIO()
        with mock.patch.object(platform_linux, "_run_systemctl", return_value=done), \
             contextlib.redirect_stdout(out):
            mc_cli.dispatch_daemon("restart")
        text = out.getvalue()
        self.assertIn("3", text)
        self.assertIn("out Job failed", text)
        self.assertNotIn("error", text.lower().replace("erreur", ""))

    def test_ipc_files_are_0644_with_a_pid_temporary(self):
        import platform_linux
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "r.json")
        seen = []
        real = os.replace
        with mock.patch("os.replace", side_effect=lambda a, b: (seen.append(a), real(a, b))):
            platform_linux.write_private_file(path, "{}", 0o644)
            platform_linux.write_private_file(os.path.join(folder, "p.json"), "{}")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
        self.assertEqual(os.stat(os.path.join(folder, "p.json")).st_mode & 0o777, 0o600)
        self.assertEqual(seen[0], f"{path}.{os.getpid()}.tmp")

    def test_run_dir_owner_given_only_to_a_folder_just_created(self):
        base = tempfile.mkdtemp()
        run = os.path.join(base, "run")
        with mock.patch.object(mc_ipc, "BASE_DIR", base), mock.patch.object(mc_ipc, "RUN_DIR", run), \
             mock.patch.object(mc_ipc.plat, "secure_dir") as secure:
            mc_ipc._private_dir(os.path.join(run, "requests"))
            mc_ipc._private_dir(os.path.join(run, "requests"))
        self.assertEqual([c.kwargs for c in secure.call_args_list],
                         [{"owner_of": base}, {"owner_of": base}, {}, {}])

    def test_secure_dir_chowns_only_when_asked_and_root(self):
        import platform_linux
        folder = tempfile.mkdtemp()
        with mock.patch("os.geteuid", return_value=0), mock.patch("os.chown") as chown:
            platform_linux.secure_dir(folder)
            chown.assert_not_called()
            platform_linux.secure_dir(folder, owner_of=folder)
            self.assertEqual(chown.call_count, 1)
        with mock.patch("os.chown") as chown:
            platform_linux.secure_dir(folder, owner_of=folder)
            chown.assert_not_called()

    def test_restic_password_file_error_is_not_swallowed(self):
        fake = FakePlatform(secure_file=False)
        saved = mc_platform._Lazy._impl
        self.addCleanup(setattr, mc_platform._Lazy, "_impl", saved)
        mc_platform.use(fake)
        pw = os.path.join(tempfile.mkdtemp(), "pw")
        with open(pw, "w") as f:
            f.write("x")
        config = {"dossier_serveur": tempfile.mkdtemp()}
        with self.assertRaises(PermissionError):
            mc_api.backup_remote_add("a", config, "r", "restic:/srv/repo", password_file=pw)

    def test_doctor_says_systemctl_is_unavailable(self):
        fake = FakePlatform(service_installed=None)
        saved = mc_platform._Lazy._impl
        self.addCleanup(setattr, mc_platform._Lazy, "_impl", saved)
        mc_platform.use(fake)
        self.assertEqual(mc_doctor._check_daemon_service(), (False, mc_core.T["doctor_svc_no_sc"]))
        import platform_linux
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(platform_linux.service_installed())
