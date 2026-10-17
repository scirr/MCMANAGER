import os
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_platform
import platform_linux as pl


def _done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


class TestContract(unittest.TestCase):
    def test_nothing_missing(self):
        self.assertEqual(mc_platform.missing(pl), [])

    def test_suspend_resume_use_stop_and_continue(self):
        with mock.patch("os.kill") as kill:
            self.assertTrue(pl.suspend(10))
            self.assertTrue(pl.resume(10))
        self.assertEqual([c.args for c in kill.call_args_list],
                         [(10, signal.SIGSTOP), (10, signal.SIGCONT)])

    def test_tree_signals_the_group_only_when_the_pid_leads_it(self):
        with mock.patch("os.kill") as kill, mock.patch("os.killpg") as killpg, \
             mock.patch("os.getpgid", return_value=10):
            self.assertTrue(pl.terminate(10, tree=True))
            killpg.assert_called_once_with(10, signal.SIGTERM)
            kill.assert_called_once_with(10, signal.SIGTERM)
        with mock.patch("os.kill"), mock.patch("os.killpg") as killpg, \
             mock.patch("os.getpgid", return_value=1):
            pl.kill(10, tree=True)
            killpg.assert_not_called()

    def test_signal_to_a_missing_process_is_false(self):
        with mock.patch("os.kill", side_effect=ProcessLookupError):
            self.assertFalse(pl.kill(10))


class TestProcFiles(unittest.TestCase):
    def _open(self, files):
        real = open

        def fake(path, *a, **k):
            if path in files:
                return mock.mock_open(read_data=files[path])()
            raise FileNotFoundError(path)
        return mock.patch("builtins.open", side_effect=fake), real

    def test_memory(self):
        status = "Name:\tjava\nVmRSS:\t  2048 kB\nVmSwap:\t  16 kB\n"
        patch, _ = self._open({"/proc/7/status": status})
        with patch:
            self.assertEqual(pl.process_memory(7), (2048, 16))
            self.assertEqual(pl.process_memory(8), (None, None))

    def test_cpu_seconds(self):
        stat = "1 (java) S 1 1 1 0 -1 4194560 0 0 0 0 150 50 0 0 20 0 30 0 1000 0 0\n"
        patch, _ = self._open({"/proc/7/stat": stat})
        with patch, mock.patch("os.sysconf", return_value=100):
            self.assertEqual(pl.process_cpu_seconds(7), 2.0)
            self.assertIsNone(pl.process_cpu_seconds(8))

    def test_uptime(self):
        stat = "1 (java) S 1 1 1 0 -1 4194560 0 0 0 0 150 50 0 0 20 0 30 0 1000 0 0\n"
        patch, _ = self._open({"/proc/7/stat": stat, "/proc/uptime": "500.0 100.0\n"})
        with patch, mock.patch("os.sysconf", return_value=100):
            self.assertEqual(pl.process_uptime(7), 490)

    def test_cgroup(self):
        patch, _ = self._open({"/proc/7/cgroup": "1:name=x:/a\n0::/system.slice/mc_manager.service\n"})
        with patch:
            self.assertEqual(pl.cgroup_of(7), "/system.slice/mc_manager.service")
            self.assertIsNone(pl.cgroup_of(8))

    def test_zombie_java_listing(self):
        files = {"/proc/5/stat": "5 (java) Z 3 5 5 0\n", "/proc/6/stat": "6 (bash) Z 3 6 6 0\n"}
        patch, _ = self._open(files)
        with patch, mock.patch("os.listdir", return_value=["5", "6", "self"]):
            self.assertEqual(pl.find_zombie_java(), [(5, 3)])

    def test_server_processes_match_cwd_and_exclude_zombies(self):
        folder = os.path.realpath(tempfile.mkdtemp())
        cwd = {11: folder, 12: folder, 13: "/elsewhere"}
        with mock.patch("os.listdir", return_value=["11", "12", "13", "x"]), \
             mock.patch.object(pl, "_proc_cwd", side_effect=lambda p: cwd[p]), \
             mock.patch.object(pl, "_is_java", return_value=True), \
             mock.patch.object(pl, "_proc_state", side_effect=lambda p: "Z" if p == 12 else "S"):
            self.assertEqual(pl.find_server_processes(folder), [11])
        self.assertEqual(pl.find_server_processes(""), [])

    def test_alive_never_signals_with_a_real_signal(self):
        with mock.patch("os.waitpid", side_effect=ChildProcessError), \
             mock.patch("os.kill", side_effect=ProcessLookupError) as kill:
            self.assertFalse(pl.process_alive(123))
        kill.assert_called_once_with(123, 0)


class TestFilesAndPrivileges(unittest.TestCase):
    def test_secure_and_private(self):
        path = os.path.join(tempfile.mkdtemp(), "f")
        with open(path, "w") as f:
            f.write("x")
        os.chmod(path, 0o644)
        private, fix = pl.file_is_private(path)
        self.assertFalse(private)
        self.assertEqual(fix, f"chmod 600 {path}")
        self.assertTrue(pl.secure_file(path))
        self.assertEqual(pl.file_is_private(path), (True, ""))
        self.assertEqual(pl.file_is_private(path + ".none"), (None, ""))
        self.assertFalse(pl.secure_file(path + ".none"))

    def test_write_private_file_is_atomic_and_0600(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "sub", "c.json")
        pl.write_private_file(path, "one")
        pl.write_private_file(path, "two")
        with open(path) as f:
            self.assertEqual(f.read(), "two")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(os.listdir(os.path.dirname(path)), ["c.json"])

    def test_secure_dir_is_0700(self):
        folder = tempfile.mkdtemp()
        os.chmod(folder, 0o755)
        self.assertTrue(pl.secure_dir(folder))
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)

    def test_paths_and_names(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/c"}):
            self.assertEqual(pl.cache_dir(), "/c")
        with mock.patch.dict(os.environ, {"VISUAL": "", "EDITOR": "vi -p"}):
            self.assertEqual(pl.default_editor(), ["vi", "-p"])
        self.assertEqual((pl.server_script_name(), pl.java_exe_name(), pl.java_archive_kind(), pl.adoptium_os()),
                         ("run.sh", "bin/java", "tar.gz", "linux"))
        self.assertEqual(pl.script_launch_args("run.sh"), ["bash", "run.sh", "nogui"])
        self.assertEqual(pl.shell_quote("a b"), "'a b'")

    def test_open_folder_uses_xdg_open(self):
        with mock.patch("subprocess.Popen") as popen:
            pl.open_folder("/srv/x")
        self.assertEqual(popen.call_args.args[0], ["xdg-open", "/srv/x"])


class TestPorts(unittest.TestCase):
    TABLE = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
             "   0: 00000000:63DD 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000 0 4242 1 0\n"
             "   1: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000 0 4343 1 0\n")

    def _tables(self):
        def fake(path, *a, **k):
            if path == "/proc/net/tcp":
                return mock.mock_open(read_data=self.TABLE)()
            raise FileNotFoundError(path)
        return mock.patch("builtins.open", side_effect=fake)

    def test_listening_interfaces(self):
        with self._tables():
            self.assertTrue(pl.listens_on_all_interfaces(0x63DD))
            self.assertFalse(pl.listens_on_all_interfaces(0x1F90))
            self.assertIsNone(pl.listens_on_all_interfaces(1))
            self.assertEqual(pl._listen_inodes(0x63DD), {"4242"})

    def test_free_port_has_no_listener(self):
        with mock.patch.object(pl, "port_in_use", return_value=False):
            self.assertIsNone(pl.port_listener(25565))
        with mock.patch.object(pl, "port_in_use", return_value=True), \
             mock.patch.object(pl, "_listener_pid", return_value=None):
            self.assertEqual(pl.port_listener(25565), (None, None))


class TestService(unittest.TestCase):
    def _control(self, code, out="", err=""):
        with mock.patch.object(pl, "_run_systemctl", return_value=_done(out, code, err)):
            return pl.service_control("restart")

    def test_codes(self):
        self.assertEqual(self._control(0), ("ok", ""))
        self.assertEqual(self._control(5, err="Unit mc_manager.service not found.")[0], "not_installed")
        self.assertEqual(self._control(1, err="Interactive authentication required.")[0], "no_permission")
        self.assertEqual(self._control(1, err="boom"), ("error", "1|boom"))

    def test_systemctl_arguments(self):
        calls = []

        def run(args, **kw):
            calls.append(args)
            return _done("", 0)
        with mock.patch("os.geteuid", return_value=1000), mock.patch("subprocess.run", side_effect=run):
            pl._run_systemctl("stop")
        self.assertEqual(calls, [["systemctl", "--no-ask-password", "stop", "mc_manager"]])

    def test_installed_and_running_follow_systemctl_show(self):
        show = "LoadState=loaded\nActiveState=active\n"
        with mock.patch("shutil.which", return_value="/bin/systemctl"), \
             mock.patch("subprocess.run", return_value=_done(show)):
            self.assertTrue(pl.service_installed())
            self.assertTrue(pl.service_running())
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(pl.service_installed())
            self.assertFalse(pl.service_running())


class TestFirewall(unittest.TestCase):
    def test_allow_and_remove_use_the_comment_rules_only(self):
        calls = []

        def run(args, root=False):
            calls.append(args)
            if args == ["ufw", "status", "numbered"]:
                return _done("[ 1] 25565/tcp ALLOW IN Anywhere # Minecraft\n"
                             "[ 2] 25565/tcp ALLOW IN Anywhere # MC Manager survie\n")
            return _done()
        with mock.patch.object(pl, "firewall_name", return_value="ufw"), \
             mock.patch.object(pl, "_run", side_effect=run), \
             mock.patch("mc_servers.find_port_conflict", return_value=None):
            self.assertEqual(pl.firewall_allow(25565, "tcp", "survie"), (True, ""))
            self.assertTrue(pl.firewall_remove(25565, "tcp", "survie"))
        self.assertIn(["ufw", "allow", "25565/tcp", "comment", "MC Manager survie"], calls)
        deletes = [c for c in calls if "delete" in c]
        self.assertEqual(deletes, [["ufw", "--force", "delete", "2"]])

    def test_manual_command(self):
        with mock.patch.object(pl, "firewall_name", return_value="firewalld"):
            self.assertIn("firewall-cmd --permanent --add-port=25565/tcp",
                          pl.firewall_manual_command(25565, "tcp", "survie"))


class TestInstall(unittest.TestCase):
    def test_service_install_reports_the_polkit_rule(self):
        folder = tempfile.mkdtemp()
        unit = os.path.join(folder, "mc_manager.service")
        with mock.patch.object(pl, "SERVICE_FILE", unit), \
             mock.patch.object(pl, "_install_polkit_rule", return_value=True), \
             mock.patch("subprocess.run", return_value=_done()) as run:
            self.assertEqual(pl.service_install("cris"), (True, "polkit"))
        self.assertTrue(os.path.exists(unit))
        self.assertEqual([c.args[0][:2] for c in run.call_args_list],
                         [["systemctl", "daemon-reload"], ["systemctl", "enable"], ["systemctl", "restart"]])

    def test_service_install_without_rights(self):
        with mock.patch("builtins.open", side_effect=PermissionError):
            self.assertEqual(pl.service_install("cris"), (False, ""))

    def test_launcher_permission_error_is_reported(self):
        base = tempfile.mkdtemp()
        with mock.patch.object(pl, "BASE_DIR", base), \
             mock.patch("shutil.copy", side_effect=PermissionError):
            ok, detail = pl.install_launcher()
        self.assertFalse(ok)
        self.assertTrue(detail.startswith("permission:"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
