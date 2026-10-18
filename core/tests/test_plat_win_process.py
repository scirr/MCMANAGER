import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import winfix
import plat_win_common as common
import plat_win_process as proc


def fake_ps(out="", rc=0):
    return mock.patch.object(proc, "run_powershell", return_value=(rc, out, ""))



class TestMarker(unittest.TestCase):
    def test_boundaries(self):
        has = proc.command_line_has_marker
        self.assertTrue(has('java -Dmcmanager.server=C:\\S\\A -Xmx1G', "C:\\S\\A"))
        self.assertTrue(has('java -Dmcmanager.server=C:\\S\\A', "c:/s/a/"))
        self.assertTrue(has('java "-Dmcmanager.server=C:\\S\\A B" -jar x', "C:\\S\\A B"))
        self.assertFalse(has('java -Dmcmanager.server=C:\\S\\A B -jar x', "C:\\S\\A"))
        self.assertFalse(has('java -Dmcmanager.server=C:\\S\\AB -jar x', "C:\\S\\A"))
        self.assertFalse(has(None, "C:\\S\\A"))
        self.assertFalse(has("java", ""))


class TestFind(unittest.TestCase):
    def find(self, fixture, d):
        with fake_ps(winfix.load(fixture)):
            return proc.find_server_processes(d)

    def test_space_in_path(self):
        self.assertEqual(self.find("cim_java_list.json", "C:\\Servers\\Mon Serveur"), [4128])

    def test_prefix_dir_not_confused(self):
        self.assertEqual(self.find("cim_java_list.json", "C:\\Servers\\Mon"), [5000])

    def test_unrelated_and_null_command_line(self):
        self.assertEqual(self.find("cim_java_list.json", "C:\\Outils"), [])

    def test_single_object(self):
        self.assertEqual(self.find("cim_java_single.json", "c:\\servers\\zoé"), [4128])

    def test_empty_output_and_error(self):
        with fake_ps(""):
            self.assertEqual(proc.find_server_processes("C:\\x"), [])
        with fake_ps("", rc=1):
            self.assertEqual(proc.find_server_processes("C:\\x"), [])
        with fake_ps("not json"):
            self.assertEqual(proc.find_server_processes("C:\\x"), [])
        self.assertEqual(proc.find_server_processes(""), [])

    def test_excludes_current_pid(self):
        out = '[{"ProcessId":%d,"CommandLine":"java -Dmcmanager.server=C:\\\\x"}]' % os.getpid()
        with fake_ps(out):
            self.assertEqual(proc.find_server_processes("C:\\x"), [])


def _row(pid, ppid, name, line):
    return {"ProcessId": pid, "ParentProcessId": ppid, "Name": name, "CommandLine": line}


class TestScriptWrapper(unittest.TestCase):
    DIR = "C:\\Servers\\Forge"

    def find(self, rows, recorded=None):
        with fake_ps(json.dumps(rows)), mock.patch.object(proc, "_read_pid_file", return_value=recorded):
            return proc.find_server_processes(self.DIR)

    def test_direct_marker(self):
        rows = [_row(10, 1, "java.exe", "java -Dmcmanager.server=C:\\Servers\\Forge -jar x.jar")]
        self.assertEqual(self.find(rows), [10])

    def test_child_of_recorded_cmd(self):
        rows = [_row(20, 1, "cmd.exe", "cmd /c run.bat nogui"), _row(21, 20, "java.exe", "java @user_jvm_args.txt")]
        self.assertEqual(self.find(rows, recorded=20), [21])

    def test_child_of_cmd_with_absolute_script(self):
        rows = [_row(20, 1, "cmd.exe", "cmd /c C:\\Servers\\Forge\\run.bat nogui"),
                _row(21, 20, "java.exe", "java @user_jvm_args.txt")]
        self.assertEqual(self.find(rows), [21])

    def test_cmd_of_another_folder(self):
        rows = [_row(20, 1, "cmd.exe", "cmd /c C:\\Servers\\Autre\\run.bat nogui"),
                _row(21, 20, "java.exe", "java @user_jvm_args.txt")]
        self.assertEqual(self.find(rows, recorded=999), [])

    def test_unrelated_cmd_with_recorded_pid_is_refused(self):
        rows = [_row(20, 1, "cmd.exe", "cmd /k dir"), _row(21, 20, "java.exe", "java -jar tool.jar")]
        self.assertEqual(self.find(rows, recorded=20), [])

    def test_dead_parent(self):
        rows = [_row(21, 20, "java.exe", "java @user_jvm_args.txt")]
        self.assertEqual(self.find(rows, recorded=20), [])

    def test_recycled_parent_is_not_cmd(self):
        rows = [_row(20, 1, "explorer.exe", "cmd /c run.bat"), _row(21, 20, "java.exe", "java @user_jvm_args.txt")]
        self.assertEqual(self.find(rows, recorded=20), [])


class TestAlive(unittest.TestCase):
    def test_ctypes_verdict_used(self):
        with mock.patch.object(proc, "_alive_ctypes", return_value=True), \
                mock.patch.object(proc, "run") as r:
            self.assertTrue(proc.process_alive(10))
            r.assert_not_called()
        with mock.patch.object(proc, "_alive_ctypes", return_value=False):
            self.assertFalse(proc.process_alive(10))

    def test_never_uses_os_kill(self):
        with mock.patch.object(proc, "_alive_ctypes", return_value=None), \
                mock.patch.object(proc, "run", return_value=(0, winfix.load("tasklist_en.csv"), "")), \
                mock.patch("os.kill", side_effect=AssertionError("os.kill")):
            self.assertTrue(proc.process_alive(12345))

    def test_tasklist_fallback_en_fr_absent(self):
        def alive(fixture, pid=12345):
            with mock.patch.object(proc, "_alive_ctypes", return_value=None), \
                    mock.patch.object(proc, "run", return_value=(0, winfix.load(fixture), "")) as r:
                res = proc.process_alive(pid)
            self.assertEqual(r.call_args[0][0],
                             ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"])
            return res
        self.assertTrue(alive("tasklist_en.csv"))
        self.assertTrue(alive("tasklist_fr.csv"))
        self.assertFalse(alive("tasklist_none_en.txt"))
        self.assertFalse(alive("tasklist_none_fr.txt"))
        self.assertFalse(alive("tasklist_en.csv", pid=999))

    def test_tasklist_failure_and_bad_pid(self):
        with mock.patch.object(proc, "_alive_ctypes", return_value=None), \
                mock.patch.object(proc, "run", return_value=(1, "", "err")):
            self.assertFalse(proc.process_alive(5))
        self.assertFalse(proc.process_alive(0))
        self.assertFalse(proc.process_alive(None))

    def test_server_dir_checked(self):
        with mock.patch.object(proc, "_alive_ctypes", return_value=True), \
                mock.patch.object(proc, "find_server_processes", return_value=[7]):
            self.assertTrue(proc.process_alive(7, "C:\\x"))
            self.assertFalse(proc.process_alive(8, "C:\\x"))

    def test_ctypes_is_none_off_windows(self):
        with mock.patch.object(proc, "is_windows", return_value=False):
            self.assertIsNone(proc._alive_ctypes(1))


class TestInfo(unittest.TestCase):
    def setUp(self):
        self.p = fake_ps(winfix.load("cim_pid.json"))
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_name(self):
        self.assertEqual(proc.process_name(4128), "java.exe")

    def test_uptime(self):
        with mock.patch.object(proc, "_now", return_value=1700000090.5):
            self.assertAlmostEqual(proc.process_uptime(4128), 90.5)

    def test_memory_kb_no_swap(self):
        self.assertEqual(proc.process_memory(4128), (2097152, None))

    def test_cpu(self):
        self.assertAlmostEqual(proc.process_cpu_seconds(4128), 15.0)

    def test_missing_pid_gives_none(self):
        with fake_ps("[]"):
            self.assertIsNone(proc.process_uptime(1))
            self.assertEqual(proc.process_memory(1), (None, None))
            self.assertIsNone(proc.process_cpu_seconds(1))
        with fake_ps("", rc=1):
            self.assertIsNone(proc.process_cpu_seconds(1))

    def test_name_falls_back_to_tasklist(self):
        with fake_ps("", rc=1), mock.patch.object(
                proc, "run", return_value=(0, winfix.load("tasklist_en.csv"), "")):
            self.assertEqual(proc.process_name(12345), "java.exe")

    def test_start_formats(self):
        self.assertEqual(proc._parse_start("/Date(1700000000000)/"), 1700000000.0)
        self.assertIsNone(proc._parse_start("hier"))
        self.assertIsNone(proc._parse_start(None))


class TestControl(unittest.TestCase):
    def test_kill_command(self):
        with mock.patch.object(proc, "run", return_value=(0, "", "")) as r:
            self.assertTrue(proc.kill(42, tree=True))
            self.assertEqual(r.call_args[0][0], ["taskkill", "/PID", "42", "/T", "/F"])
            proc.kill(42)
            self.assertEqual(r.call_args[0][0], ["taskkill", "/PID", "42", "/F"])
        with mock.patch.object(proc, "run", return_value=(128, "", "not found")):
            self.assertFalse(proc.kill(42))

    def test_terminate_does_nothing(self):
        with mock.patch.object(proc, "run") as r:
            self.assertFalse(proc.terminate(42))
            r.assert_not_called()

    def test_suspend_resume_unsupported(self):
        for fn in (proc.suspend, proc.resume):
            with self.assertRaises(common.Unsupported) as cm:
                fn(1)
            self.assertEqual(cm.exception.code, "unsupported_on_windows")

    def test_trivial(self):
        self.assertIsNone(proc.reap_children())
        self.assertEqual(proc.find_zombie_java(), [])
        self.assertEqual(proc.script_launch_args("run.bat"), ["cmd", "/c", "run.bat", "nogui"])
        self.assertFalse(proc.set_affinity(1, {0}) if not common.is_windows() else False)


class TestSpawn(unittest.TestCase):
    def test_flags_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "dossier avec espace", "out.log")
            os.makedirs(os.path.dirname(log))
            with mock.patch.object(proc, "_popen") as popen:
                proc.spawn_server(["java", "-jar", "a b.jar"], tmp, {"A": "1"}, log)
            args, kw = popen.call_args
            self.assertEqual(args[0], ["java", "-jar", "a b.jar"])
            self.assertEqual(kw["creationflags"], 0x200 | 0x8)
            self.assertEqual(kw["cwd"], tmp)
            self.assertEqual(kw["stderr"], subprocess.STDOUT)
            self.assertTrue(kw["stdout"].closed)
            self.assertEqual(kw["stdout"].name, log)

    def test_no_log(self):
        with mock.patch.object(proc, "_popen") as popen:
            proc.spawn_server(["java"], ".")
        self.assertEqual(popen.call_args[1]["stdout"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
