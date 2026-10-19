import os
import plistlib
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_platform
import platform_macos as pm

PS_ONE = "  501     1 Ss    02-03:04:05 204800   1:23.45 /Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home/bin/java -Xmx4G -jar server.jar nogui\n"
PS_ALL = (
    "    1     0 Ss    12-04:11:09  11264   0:42.18 /sbin/launchd\n"
    "  412     1 S      03:21:45  95232   1:02:03.04 /Applications/My Apps/Safari.app/Contents/MacOS/Safari\n"
    " 6310   977 S<s       01:12 2204672  12:30.99 /Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home/bin/java -Xms4G -jar fabric.jar nogui\n"
    " 6400   977 Z           00:09       0   0:00.00 (java)\n"
    " 6500   977 S           00:05   10240   0:00.01 bash run.sh nogui\n"
    "garbage line\n"
)
LSOF_CWD = "p6310\nfcwd\nn/Users/cris/Library/Application Support/MCManager/Servers/alpha\np6500\nfcwd\nn/Users/cris/other\n"
LSOF_LISTEN = "p6310\ncjava\nf95\nn*:25565\nf96\nn*:25565\n"
LSOF_LOCAL = "p701\ncjava\nf12\nn127.0.0.1:25575\np702\ncjava\nf13\nn[::1]:25575\n"
LAUNCHCTL_PRINT = (
    "gui/501/io.github.scirr.mcmanager = {\n"
    "\tactive count = 1\n"
    "\tpath = /Users/cris/Library/LaunchAgents/io.github.scirr.mcmanager.plist\n"
    "\ttype = LaunchAgent\n"
    "\tstate = running\n"
    "\n"
    "\tprogram = /usr/bin/python3\n"
    "\targuments = {\n"
    "\t\t/usr/bin/python3\n"
    "\t\t/Users/cris/MCManager/mc_daemon.py\n"
    "\t}\n"
    "\tproperties = keepalive | runatload | abandonprocessgroup\n"
    "\tpid = 8123\n"
    "\timmediate reason = ipc (mach)\n"
    "}\n"
)


def _done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


class TestContract(unittest.TestCase):
    def test_nothing_missing(self):
        self.assertEqual(mc_platform.missing(pm), [])

    def test_names_and_paths(self):
        self.assertEqual(pm.os_name(), "macOS")
        self.assertEqual(pm.adoptium_os(), "mac")
        self.assertEqual(pm.java_archive_kind(), "tar.gz")
        self.assertEqual(pm.java_exe_name(), "Contents/Home/bin/java")
        self.assertIn("/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java", pm.java_search_paths())
        self.assertTrue(pm.data_dir().endswith("Library/Application Support/MCManager/Servers"))
        self.assertTrue(pm.cache_dir().endswith("Library/Caches/MCManager"))
        self.assertIsNone(pm.cgroup_of(1))

    @unittest.skipIf(sys.platform == "win32", "POSIX signals")
    def test_suspend_and_resume_use_stop_and_continue(self):
        with mock.patch("os.kill") as kill:
            self.assertTrue(pm.suspend(10))
            self.assertTrue(pm.resume(10))
        self.assertEqual([c.args for c in kill.call_args_list], [(10, signal.SIGSTOP), (10, signal.SIGCONT)])

    def test_editor_and_folder(self):
        with mock.patch.dict(os.environ, {"VISUAL": "", "EDITOR": ""}):
            self.assertEqual(pm.default_editor(), ["open", "-t"])
        with mock.patch.dict(os.environ, {"VISUAL": "", "EDITOR": "vi -p"}):
            self.assertEqual(pm.default_editor(), ["vi", "-p"])
        with mock.patch("subprocess.Popen") as popen:
            pm.open_folder("/x")
        self.assertEqual(popen.call_args.args[0], ["open", "/x"])


class TestPs(unittest.TestCase):
    def test_parse_rows(self):
        rows = pm.parse_ps(PS_ALL)
        self.assertEqual([r["pid"] for r in rows], [1, 412, 6310, 6400, 6500])
        one = pm.parse_ps(PS_ONE)[0]
        self.assertEqual(one["uptime"], 2 * 86400 + 3 * 3600 + 4 * 60 + 5)
        self.assertEqual(one["rss"], 204800)
        self.assertAlmostEqual(one["cpu"], 83.45)
        self.assertTrue(one["command"].endswith("-jar server.jar nogui"))
        self.assertAlmostEqual(rows[1]["cpu"], 3723.04)
        self.assertEqual(rows[1]["uptime"], 3 * 3600 + 21 * 60 + 45)
        self.assertEqual(rows[1]["command"], "/Applications/My Apps/Safari.app/Contents/MacOS/Safari")

    def test_single_process_queries(self):
        with mock.patch.object(pm, "_run", return_value=_done(PS_ONE)):
            self.assertEqual(pm.process_uptime(501), 183845)
            self.assertEqual(pm.process_memory(501), (204800, None))
            self.assertAlmostEqual(pm.process_cpu_seconds(501), 83.45)

    def test_unknown_process(self):
        with mock.patch.object(pm, "_run", return_value=_done("", 1)):
            self.assertIsNone(pm.process_uptime(9))
            self.assertEqual(pm.process_memory(9), (None, None))
            self.assertIsNone(pm.process_cpu_seconds(9))
            self.assertIsNone(pm.process_name(9))

    def test_process_name_is_the_basename(self):
        with mock.patch.object(pm, "_run", return_value=_done("/Library/Java/x.jdk/Contents/Home/bin/java\n")):
            self.assertEqual(pm.process_name(5), "java")

    def test_zombie_java(self):
        with mock.patch.object(pm, "_run", return_value=_done(PS_ALL)):
            self.assertEqual(pm.find_zombie_java(), [(6400, 977)])

    def test_find_server_processes_matches_working_directory(self):
        target = "/Users/cris/Library/Application Support/MCManager/Servers/alpha"

        def run(args, timeout=15):
            return _done(PS_ALL) if args[0] == "ps" else _done(LSOF_CWD)
        with mock.patch.object(pm, "_run", side_effect=run), mock.patch("os.path.realpath", side_effect=lambda p: p):
            self.assertEqual(pm.find_server_processes(target), [6310])
            self.assertEqual(pm.find_server_processes(""), [])

    @unittest.skipIf(sys.platform == "win32", "POSIX waitpid")
    def test_process_alive_checks_directory(self):
        with mock.patch("os.kill"), mock.patch("os.waitpid", side_effect=ChildProcessError), \
             mock.patch.object(pm, "_run", return_value=_done(PS_ONE)), \
             mock.patch.object(pm, "_proc_cwd", return_value="/srv/a"):
            self.assertTrue(pm.process_alive(501))
            self.assertTrue(pm.process_alive(501, "/srv/a"))
            self.assertFalse(pm.process_alive(501, "/srv/b"))

    @unittest.skipIf(sys.platform == "win32", "POSIX waitpid")
    def test_process_alive_false_for_zombie_and_missing(self):
        with mock.patch("os.kill"), mock.patch("os.waitpid", side_effect=ChildProcessError), \
             mock.patch.object(pm, "_run", return_value=_done(" 6400   977 Z 00:09 0 0:00.00 (java)\n")):
            self.assertFalse(pm.process_alive(6400))
        with mock.patch("os.kill", side_effect=ProcessLookupError), mock.patch("os.waitpid", side_effect=ChildProcessError):
            self.assertFalse(pm.process_alive(1))


class TestLsof(unittest.TestCase):
    def test_cwd(self):
        cwds = pm.parse_lsof_cwd(LSOF_CWD)
        self.assertEqual(cwds[6310], "/Users/cris/Library/Application Support/MCManager/Servers/alpha")
        self.assertEqual(cwds[6500], "/Users/cris/other")

    def test_listen(self):
        self.assertEqual(pm.parse_lsof_listen(LSOF_LISTEN), [(6310, "java", ["*:25565", "*:25565"])])

    def test_in_use_when_only_lsof_sees_the_listener(self):
        with mock.patch.object(pm, "_bind_probe", return_value=False), \
             mock.patch.object(pm, "_run", return_value=_done(LSOF_LOCAL)):
            self.assertTrue(pm.port_in_use(25575))
        with mock.patch.object(pm, "_bind_probe", return_value=False), mock.patch.object(pm, "_run", return_value=_done("", 1)):
            self.assertFalse(pm.port_in_use(25575))

    def test_port_listener(self):
        with mock.patch.object(pm, "port_in_use", return_value=True), \
             mock.patch.object(pm, "_run", return_value=_done(LSOF_LISTEN)) as run:
            self.assertEqual(pm.port_listener(25565), (6310, "java"))
        self.assertEqual(run.call_args.args[0], ["lsof", "-nP", "-iTCP:25565", "-sTCP:LISTEN", "-Fpcn"])
        with mock.patch.object(pm, "port_in_use", return_value=True), mock.patch.object(pm, "_run", return_value=_done("", 1)):
            self.assertEqual(pm.port_listener(25565), (None, None))
        with mock.patch.object(pm, "port_in_use", return_value=False):
            self.assertIsNone(pm.port_listener(25565))
        self.assertIsNone(pm.port_listener(0))

    def test_all_interfaces(self):
        with mock.patch.object(pm, "_run", return_value=_done(LSOF_LISTEN)):
            self.assertTrue(pm.listens_on_all_interfaces(25565))
        with mock.patch.object(pm, "_run", return_value=_done(LSOF_LOCAL)):
            self.assertFalse(pm.listens_on_all_interfaces(25575))
        with mock.patch.object(pm, "_run", return_value=_done("", 1)):
            self.assertIsNone(pm.listens_on_all_interfaces(25575))


class TestService(unittest.TestCase):
    def test_plist_content(self):
        data = plistlib.loads(pm._service_plist_bytes())
        self.assertEqual(data["Label"], "io.github.scirr.mcmanager")
        self.assertTrue(data["KeepAlive"])
        self.assertTrue(data["RunAtLoad"])
        self.assertTrue(data["AbandonProcessGroup"])
        self.assertEqual(data["ProgramArguments"][-1], os.path.join(pm.BASE_DIR, "mc_daemon.py"))
        self.assertEqual(data["WorkingDirectory"], pm.BASE_DIR)
        self.assertTrue(pm.SERVICE_FILE.replace(os.sep, "/").endswith("Library/LaunchAgents/io.github.scirr.mcmanager.plist"))

    def test_shared_data_dir_is_baked_in(self):
        with mock.patch.dict(os.environ, {"MCMANAGER_DATA_DIR": "/shared"}):
            self.assertEqual(pm._service_plist()["EnvironmentVariables"]["MCMANAGER_DATA_DIR"], "/shared")

    def test_parse_launchctl_print(self):
        self.assertEqual(pm.parse_launchctl_print(LAUNCHCTL_PRINT), {"state": "running", "pid": "8123"})
        self.assertEqual(pm.parse_launchctl_print("\tstate = not running\n"), {})

    def test_running(self):
        with mock.patch("os.getuid", create=True, return_value=501):
            with mock.patch.object(pm, "_launchctl", return_value=_done(LAUNCHCTL_PRINT)):
                self.assertTrue(pm.service_running())
            with mock.patch.object(pm, "_launchctl", return_value=_done("", 113, "Could not find service")):
                self.assertFalse(pm.service_running())

    def test_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.plist")
            with mock.patch.object(pm, "SERVICE_FILE", path):
                self.assertEqual(pm.service_unit_drift(), ("missing", []))
                with open(path, "wb") as f:
                    f.write(pm._service_plist_bytes())
                self.assertEqual(pm.service_unit_drift(), ("ok", []))
                data = pm._service_plist()
                data["AbandonProcessGroup"] = False
                with open(path, "wb") as f:
                    f.write(plistlib.dumps(data))
                state, diffs = pm.service_unit_drift()
                self.assertEqual(state, "outdated")
                self.assertEqual(diffs[0][0], "AbandonProcessGroup")

    def test_control_not_installed(self):
        with mock.patch.object(pm, "SERVICE_FILE", "/nonexistent/x.plist"):
            self.assertEqual(pm.service_control("start"), ("not_installed", ""))

    def _control(self, action, loaded, result=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.plist")
            open(path, "w").close()
            calls = []

            def launchctl(*args):
                calls.append(args)
                if args[0] == "print":
                    return _done(LAUNCHCTL_PRINT) if loaded else _done("", 113, "Could not find service")
                return result or _done()
            with mock.patch.object(pm, "SERVICE_FILE", path), mock.patch.object(pm, "_launchctl", side_effect=launchctl), \
                 mock.patch("os.getuid", create=True, return_value=501):
                return pm.service_control(action), [c for c in calls if c[0] != "print"]

    def test_control_commands(self):
        res, calls = self._control("stop", True)
        self.assertEqual((res, calls), (("ok", ""), [("bootout", "gui/501/io.github.scirr.mcmanager")]))
        self.assertEqual(self._control("stop", False), (("ok", ""), []))
        res, calls = self._control("restart", True)
        self.assertEqual(calls, [("kickstart", "-k", "gui/501/io.github.scirr.mcmanager")])
        res, calls = self._control("start", False)
        self.assertEqual(calls[0][:2], ("bootstrap", "gui/501"))

    def test_control_errors(self):
        res, _ = self._control("start", False, _done("", 5, "Bootstrap failed: 5: Input/output error"))
        self.assertEqual(res[0], "error")
        res, _ = self._control("start", False, _done("", 1, "Operation not permitted"))
        self.assertEqual(res[0], "no_permission")

    def test_install_refuses_root(self):
        with mock.patch("os.getuid", create=True, return_value=0):
            self.assertFalse(pm.service_install()[0])

    def test_install_writes_and_bootstraps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "A", "s.plist")
            calls = []

            def launchctl(*args):
                calls.append(args)
                return _done("", 113) if args[0] == "print" else _done()
            with mock.patch.object(pm, "SERVICE_FILE", path), mock.patch.object(pm, "LAUNCH_AGENTS_DIR", os.path.dirname(path)), \
                 mock.patch.object(pm, "BASE_DIR", tmp), mock.patch.object(pm, "_launchctl", side_effect=launchctl), \
                 mock.patch("os.getuid", create=True, return_value=501):
                self.assertEqual(pm.service_install(), (True, ""))
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(calls[-1][0], "bootstrap")


class TestFirewallAndLauncher(unittest.TestCase):
    def test_firewall_is_manual(self):
        self.assertEqual(pm.firewall_allow(25565, "tcp", "a"), (False, "manual"))
        self.assertFalse(pm.firewall_remove(25565, "tcp", "a"))
        self.assertIsNone(pm.firewall_port_open(25565))
        self.assertIn("socketfilterfw", pm.firewall_manual_command(25565, "tcp", "a"))
        with mock.patch("os.path.exists", return_value=True):
            self.assertEqual(pm.firewall_name(), "socketfilterfw")
        with mock.patch("os.path.exists", return_value=False):
            self.assertIsNone(pm.firewall_name())

    def test_launcher_falls_back_to_home_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            home_bin = os.path.join(tmp, "bin", "mc")
            real_copy = __import__("shutil").copy

            def copy(src, dst):
                if dst.startswith("/usr/local"):
                    raise PermissionError
                return real_copy(src, dst)
            with mock.patch.object(pm, "BASE_DIR", tmp), mock.patch.object(pm, "LAUNCHER_PATHS", ("/usr/local/bin/mc", home_bin)), \
                 mock.patch("shutil.copy", side_effect=copy):
                self.assertEqual(pm.install_launcher(), (True, home_bin))

    def test_launcher_reports_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pm, "BASE_DIR", tmp), mock.patch("shutil.copy", side_effect=PermissionError), \
                 mock.patch("os.makedirs"):
                ok, detail = pm.install_launcher()
            self.assertFalse(ok)
            self.assertTrue(detail.startswith("permission:"))


@unittest.skipUnless(sys.platform == "darwin", "needs a real Mac")
class TestOnMac(unittest.TestCase):
    def test_platform_is_selected(self):
        self.assertEqual(mc_platform.plat.os_name(), "macOS")

    def test_own_process_is_visible(self):
        self.assertTrue(pm.process_alive(os.getpid()))
        self.assertGreaterEqual(pm.process_uptime(os.getpid()), 0)
        self.assertGreater(pm.process_memory(os.getpid())[0], 0)
        self.assertIsNotNone(pm.process_cpu_seconds(os.getpid()))
        self.assertEqual(pm._proc_cwd(os.getpid()), os.path.realpath(os.getcwd()))

    def test_listener_is_found(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            self.assertEqual(pm.port_listener(port)[0], os.getpid())
            self.assertFalse(pm.listens_on_all_interfaces(port))

    def test_launchctl_available(self):
        self.assertTrue(pm.service_installed() in (True, False))


if __name__ == "__main__":
    unittest.main()
