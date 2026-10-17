import ntpath
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import mc_platform
import plat_win_common
import platform_windows as pw
from fake_platform import FakePlatform


def env(**kw):
    return mock.patch.dict(os.environ, kw, clear=True)


class TestContract(unittest.TestCase):
    def test_nothing_missing(self):
        self.assertEqual(mc_platform.missing(pw), [])

    def test_unsupported_is_shared(self):
        self.assertIs(plat_win_common.Unsupported, mc_platform.Unsupported)

    def test_suspend_resume(self):
        with self.assertRaises(mc_platform.Unsupported):
            pw.suspend(1)
        with self.assertRaises(mc_platform.Unsupported):
            pw.resume(1)

    def test_use_fake(self):
        saved = mc_platform._Lazy._impl
        try:
            fake = FakePlatform(port_in_use=True)
            mc_platform.use(fake)
            self.assertTrue(mc_platform.plat.port_in_use(25565))
            self.assertEqual(fake.called("port_in_use"), [(25565,)])
        finally:
            mc_platform.use(saved)


class TestSmallFunctions(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(pw.java_exe_name(), "bin\\java.exe")
        self.assertEqual(pw.adoptium_os(), "windows")
        self.assertIsNone(pw.cgroup_of(1))
        self.assertIsNone(pw.set_executable("x"))

    def test_shell_quote(self):
        self.assertEqual(pw.shell_quote("a b"), '"a b"')
        self.assertEqual(pw.shell_quote("ab"), "ab")

    def test_default_editor(self):
        with env():
            self.assertEqual(pw.default_editor(), ["notepad"])
        with env(EDITOR="vim"):
            self.assertEqual(pw.default_editor(), ["vim"])
        with env(EDITOR="vim", VISUAL="code -w"):
            self.assertEqual(pw.default_editor(), ["code", "-w"])

    def test_java_search_paths(self):
        with env(ProgramFiles=r"D:\PF"):
            paths = pw.java_search_paths()
        self.assertEqual(len(paths), 4)
        self.assertTrue(all(p.startswith("D:\\PF") and p.endswith("java.exe") for p in paths))
        self.assertTrue(any("Eclipse Adoptium" in p for p in paths))
        with env():
            self.assertTrue(pw.java_search_paths()[0].startswith(r"C:\Program Files"))

    def test_setup_console_noop_off_windows(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch("os.system") as system:
            pw.setup_console()
        system.assert_not_called()

    def test_setup_console_windows(self):
        out, err = mock.Mock(), mock.Mock()
        with mock.patch.object(sys, "platform", "win32"), mock.patch("os.system") as system, \
                mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            pw.setup_console()
        system.assert_called_once_with("")
        out.reconfigure.assert_called_once_with(encoding="utf-8")
        err.reconfigure.assert_called_once_with(encoding="utf-8")

    def test_pick_file_dialog_without_tk(self):
        with mock.patch.dict(sys.modules, {"tkinter": None}):
            self.assertIsNone(pw.pick_file_dialog())


class TestLauncher(unittest.TestCase):
    def test_needs_elevation(self):
        with mock.patch.object(pw._files, "is_elevated", return_value=False):
            ok, detail = pw.install_launcher()
        self.assertFalse(ok)

    def test_writes_bat(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "System32"))
            with mock.patch.object(pw._files, "is_elevated", return_value=True), \
                    env(SystemRoot=root), \
                    mock.patch.object(pw.ntpath, "join", os.path.join):
                ok, detail = pw.install_launcher()
            self.assertTrue(ok)
            with open(detail, newline="") as f:
                text = f.read()
        self.assertIn("mc_cli.py", text)
        self.assertTrue(text.endswith("%*\r\n"))

    def test_write_failure(self):
        with mock.patch.object(pw._files, "is_elevated", return_value=True), \
                env(SystemRoot="/nonexistent-root"), \
                mock.patch.object(pw.ntpath, "join", os.path.join):
            ok, detail = pw.install_launcher()
        self.assertFalse(ok)
        self.assertTrue(detail)


class TestService(unittest.TestCase):
    def test_install_maps_code(self):
        with mock.patch.object(pw._service, "find_nssm", return_value="nssm.exe"), \
                mock.patch.object(pw._service, "service_install",
                                  return_value=("ok", "")) as inst:
            self.assertEqual(pw.service_install(), (True, ""))
        args = inst.call_args[0]
        self.assertEqual(args[0], "nssm.exe")
        self.assertEqual(args[1], sys.executable)
        self.assertTrue(args[2].endswith("mc_daemon.py"))
        with mock.patch.object(pw._service, "find_nssm", return_value="nssm.exe"), \
                mock.patch.object(pw._service, "service_install",
                                  return_value=("no_permission", "cmd")):
            self.assertEqual(pw.service_install(), (False, "cmd"))

    def test_install_without_nssm(self):
        with mock.patch.object(pw._service, "find_nssm", return_value=None):
            ok, detail = pw.service_install()
        self.assertFalse(ok)

    def test_drift_passes_expected(self):
        with mock.patch.object(pw._service, "find_nssm", return_value="nssm.exe"), \
                mock.patch.object(pw._service, "service_unit_drift",
                                  return_value=("ok", [])) as drift:
            self.assertEqual(pw.service_unit_drift(), ("ok", []))
        expected = drift.call_args[0][0]
        self.assertEqual(set(expected), {"Application", "AppParameters", "AppDirectory"})
        self.assertEqual(expected["Application"], sys.executable)


class FakeMsvcrt:
    def __init__(self, chars):
        self.chars = list(chars)

    def kbhit(self):
        return bool(self.chars)

    def getwch(self):
        return self.chars.pop(0)


class TestConsole(unittest.TestCase):
    def keys(self, chars, n):
        fake = FakeMsvcrt(chars)
        with mock.patch.dict(sys.modules, {"msvcrt": fake}):
            with pw.console_raw_mode() as console:
                return [console.read_key(0.0) for _ in range(n)]

    def test_plain_and_special(self):
        got = self.keys(["a", "\xe0", "H", "\x00", "K", "\x00", ";", "\r", "\xe0", "\x01"], 7)
        self.assertEqual(got, ["a", "up", "left", "f1", "\r", "special", None])

    def test_timeout_returns_none(self):
        self.assertEqual(self.keys([], 1), [None])

    def test_waits_until_timeout(self):
        fake = FakeMsvcrt([])
        clock = iter([0.0, 0.05, 0.2, 0.4])
        with mock.patch.dict(sys.modules, {"msvcrt": fake}), \
                mock.patch.object(pw.time, "monotonic", lambda: next(clock)), \
                mock.patch.object(pw.time, "sleep"):
            with pw.console_raw_mode() as console:
                self.assertIsNone(console.read_key(0.1))


class TestFakePlatform(unittest.TestCase):
    def test_complete(self):
        self.assertEqual(mc_platform.missing(FakePlatform()), [])

    def test_records_and_overrides(self):
        fake = FakePlatform(port_listener=(5, "java.exe"))
        self.assertEqual(fake.port_listener(25565), (5, "java.exe"))
        self.assertEqual(fake.called("port_listener"), [(25565,)])
        self.assertFalse(fake.process_alive(9))
        fake.alive.add(9)
        self.assertTrue(fake.process_alive(9))

    def test_suspend_unsupported(self):
        with self.assertRaises(mc_platform.Unsupported):
            FakePlatform().suspend(1)

    def test_private_file_and_console(self):
        fake = FakePlatform(keys=["x", "up"])
        fake.write_private_file("p", "t")
        self.assertEqual(fake.files, {"p": "t"})
        with fake.console_raw_mode() as c:
            self.assertEqual([c.read_key(0), c.read_key(0), c.read_key(0)], ["x", "up", None])


if __name__ == "__main__":
    unittest.main()
