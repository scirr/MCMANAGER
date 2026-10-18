import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plat_win_service as svc

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "windows")


def fx(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return "".join(line for line in f if not line.startswith("##"))


def patch_ps(rc=0, out="", err=""):
    return mock.patch.object(svc.common, "run_powershell", return_value=(rc, out, err))


def patch_run(fn):
    return mock.patch.object(svc.common, "run", side_effect=fn)


class TestState(unittest.TestCase):
    def test_bare_object_from_powershell(self):
        with patch_ps(out=fx("ps_service_running_object_en.json")):
            self.assertEqual(svc.service_state(), "running")
            self.assertTrue(svc.service_running())
            self.assertTrue(svc.service_installed())

    def test_list_from_powershell(self):
        with patch_ps(out=fx("ps_service_stopped_list_fr.json")):
            self.assertEqual(svc.service_state(), "stopped")
            self.assertFalse(svc.service_running())
            self.assertTrue(svc.service_installed())

    def test_numeric_status(self):
        with patch_ps(out=fx("ps_service_running_numeric.json")):
            self.assertEqual(svc.service_state(), "running")

    def test_absent_service_empty_output(self):
        with patch_ps(out=""):
            self.assertEqual(svc.service_state(), "absent")
            self.assertFalse(svc.service_installed())

    def test_powershell_failure_falls_back_to_sc_en(self):
        with patch_ps(rc=1, err="boom"), \
                patch_run(lambda cmd, **k: (0, fx("sc_query_running_en.txt"), "")) as run:
            self.assertEqual(svc.service_state(), "running")
        self.assertEqual(run.call_args[0][0], ["sc", "query", "MCManagerDaemon"])

    def test_sc_fallback_fr_labels(self):
        with patch_ps(rc=127), patch_run(lambda cmd, **k: (0, fx("sc_query_stopped_fr.txt"), "")):
            self.assertEqual(svc.service_state(), "stopped")

    def test_sc_fallback_absent(self):
        with patch_ps(rc=1), patch_run(lambda cmd, **k: (1060, fx("sc_error_absent_fr.txt"), "")):
            self.assertEqual(svc.service_state(), "absent")
            self.assertFalse(svc.service_installed())

    def test_sc_denied_is_unknown_not_absent(self):
        with patch_ps(rc=1), patch_run(lambda cmd, **k: (5, fx("sc_error_denied_en.txt"), "")):
            self.assertIsNone(svc.service_state())
            self.assertFalse(svc.service_installed())

    def test_garbage_json_falls_back(self):
        with patch_ps(out="not json"), patch_run(lambda cmd, **k: (0, fx("sc_query_running_en.txt"), "")):
            self.assertEqual(svc.service_state(), "running")


class TestControl(unittest.TestCase):
    def test_start_ok_and_already_running(self):
        with patch_run(lambda cmd, **k: (0, "", "")):
            self.assertEqual(svc.service_control("start")[0], "ok")
        with patch_run(lambda cmd, **k: (1056, "", "")):
            self.assertEqual(svc.service_control("start")[0], "ok")

    def test_stop_when_not_running_is_ok(self):
        with patch_run(lambda cmd, **k: (1062, "", "")):
            self.assertEqual(svc.service_control("stop")[0], "ok")

    def test_not_installed(self):
        with patch_run(lambda cmd, **k: (1060, fx("sc_error_absent_fr.txt"), "")):
            self.assertEqual(svc.service_control("restart")[0], "not_installed")

    def test_access_denied(self):
        with patch_run(lambda cmd, **k: (5, fx("sc_error_denied_en.txt"), "")):
            code, detail = svc.service_control("stop")
        self.assertEqual(code, "no_permission")
        self.assertIn("Access is denied", detail)
        self.assertEqual(svc.service_admin_command("restart"),
                         "net stop MCManagerDaemon && net start MCManagerDaemon")

    def test_restart_stops_waits_then_starts(self):
        verbs = []

        def fake(cmd, **k):
            verbs.append(cmd[1])
            return 0, "", ""

        states = iter(["pending", "stopped"])
        with patch_run(fake), mock.patch.object(svc, "service_state", lambda: next(states)), \
                mock.patch.object(svc.time, "sleep"):
            self.assertEqual(svc.service_restart(), ("ok", ""))
        self.assertEqual(verbs, ["stop", "start"])

    def test_restart_times_out(self):
        clock = iter([0, 1, 100])
        with patch_run(lambda cmd, **k: (0, "", "")), \
                mock.patch.object(svc, "service_state", lambda: "pending"), \
                mock.patch.object(svc.time, "monotonic", lambda: next(clock)), \
                mock.patch.object(svc.time, "sleep"):
            code, _ = svc.service_restart()
        self.assertEqual(code, "error")

    def test_unknown_action(self):
        with self.assertRaises(ValueError):
            svc.service_control("explode")


def nssm_fake(values, calls=None):
    def fake(cmd, **k):
        if calls is not None:
            calls.append(cmd)
        if cmd[1] == "get":
            value = values.get(cmd[3])
            if value is None:
                return 3, "", "unknown"
            return 0, value, ""
        return 0, "", ""
    return fake


class TestKillTree(unittest.TestCase):
    def test_disabled(self):
        with patch_run(nssm_fake({"AppKillProcessTree": "0\r\n"})):
            self.assertIs(svc.service_kill_tree_disabled("nssm.exe"), True)

    def test_enabled_is_a_problem(self):
        with patch_run(nssm_fake({"AppKillProcessTree": "1\r\n"})):
            self.assertIs(svc.service_kill_tree_disabled("nssm.exe"), False)

    def test_utf16_output_decoded_as_oem(self):
        raw = "\xff\xfe" + "0\x00\r\x00\n\x00".replace("\x00", "\x00")
        with patch_run(nssm_fake({"AppKillProcessTree": raw})):
            self.assertIs(svc.service_kill_tree_disabled("nssm.exe"), True)

    def test_unreadable_or_no_nssm(self):
        with patch_run(nssm_fake({})):
            self.assertIsNone(svc.service_kill_tree_disabled("nssm.exe"))
        with mock.patch.object(svc, "find_nssm", return_value=None):
            self.assertIsNone(svc.service_kill_tree_disabled())

    def test_command(self):
        calls = []
        with patch_run(nssm_fake({"AppKillProcessTree": "0"}, calls)):
            svc.service_kill_tree_disabled("C:\\Program Files\\MC Manager\\nssm.exe")
        self.assertEqual(calls[0], ["C:\\Program Files\\MC Manager\\nssm.exe", "get",
                                    "MCManagerDaemon", "AppKillProcessTree"])


class TestInstall(unittest.TestCase):
    ARGS = ("C:\\Mon Dossier\\nssm.exe", "C:\\Python 3\\pythonw.exe",
            "C:\\Mon Dossier\\mc_daemon.py", "C:\\Mon Dossier", "C:\\Mon Dossier\\logs")

    def test_sets_kill_tree_zero_and_verifies(self):
        calls = []
        with patch_run(nssm_fake({"AppKillProcessTree": "0"}, calls)):
            self.assertEqual(svc.service_install(*self.ARGS), ("ok", ""))
        sets = [c[3:] for c in calls if c[1] == "set"]
        self.assertIn(["AppKillProcessTree", "0"], sets)
        self.assertIn(["AppDirectory", "C:\\Mon Dossier"], sets)
        verbs = [c[1] for c in calls]
        self.assertLess(verbs.index("install"), verbs.index("start"))
        self.assertEqual(verbs[-1], "start")
        install = next(c for c in calls if c[1] == "install")
        self.assertEqual(install[2:], ["MCManagerDaemon", self.ARGS[1], self.ARGS[2]])

    def test_shared_data_dir(self):
        calls = []
        with patch_run(nssm_fake({"AppKillProcessTree": "0"}, calls)):
            svc.service_install(*self.ARGS, shared_data_dir="D:\\Partage MC")
        self.assertIn(["AppEnvironmentExtra", "MCMANAGER_DATA_DIR=D:\\Partage MC"],
                      [c[3:] for c in calls if c[1] == "set"])

    def test_setting_not_applied_is_an_error(self):
        with patch_run(nssm_fake({"AppKillProcessTree": "1"})):
            code, _ = svc.service_install(*self.ARGS)
        self.assertEqual(code, "error")

    def test_not_elevated(self):
        def fake(cmd, **k):
            return (1, "", "access") if cmd[1] == "install" else (0, "", "")

        with patch_run(fake), mock.patch.object(svc.files, "is_elevated", return_value=False):
            code, detail = svc.service_install(*self.ARGS)
        self.assertEqual(code, "no_permission")
        self.assertIn("nssm.exe", detail)


class TestDrift(unittest.TestCase):
    EXPECTED = {"Application": "C:\\Python 3\\pythonw.exe",
                "AppParameters": "\"C:\\Mon Dossier\\mc_daemon.py\"",
                "AppDirectory": "C:\\Mon Dossier"}

    def values(self, **over):
        v = {"Application": "c:\\python 3\\PYTHONW.exe",
             "AppParameters": "C:\\Mon Dossier\\mc_daemon.py",
             "AppDirectory": "C:\\Mon Dossier\\",
             "AppKillProcessTree": "0"}
        v.update(over)
        return v

    def test_missing(self):
        with mock.patch.object(svc, "service_state", return_value="absent"):
            self.assertEqual(svc.service_unit_drift(self.EXPECTED, "nssm.exe"), ("missing", []))

    def test_ok_ignores_case_quotes_and_trailing_slash(self):
        with mock.patch.object(svc, "service_state", return_value="running"), \
                patch_run(nssm_fake(self.values())):
            self.assertEqual(svc.service_unit_drift(self.EXPECTED, "nssm.exe"), ("ok", []))

    def test_outdated(self):
        vals = self.values(AppDirectory="C:\\Ancien", AppKillProcessTree="1")
        with mock.patch.object(svc, "service_state", return_value="running"), \
                patch_run(nssm_fake(vals)):
            status, drift = svc.service_unit_drift(self.EXPECTED, "nssm.exe")
        self.assertEqual(status, "outdated")
        self.assertIn(("AppDirectory", "C:\\Ancien", "C:\\Mon Dossier"), drift)
        self.assertIn(("AppKillProcessTree", "1", "0"), drift)

    def test_no_nssm_means_ok(self):
        with mock.patch.object(svc, "service_state", return_value="running"), \
                mock.patch.object(svc, "find_nssm", return_value=None):
            self.assertEqual(svc.service_unit_drift(self.EXPECTED), ("ok", []))


if __name__ == "__main__":
    unittest.main()


class TestEnsureNssm(unittest.TestCase):
    def archive(self):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for arch in ("win32", "win64"):
                zf.writestr(f"nssm-2.24/{arch}/nssm.exe", arch)
        return buf.getvalue()

    def test_existing_copy_is_used(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "nssm"))
            path = os.path.join(d, "nssm", "nssm.exe")
            open(path, "wb").close()
            with mock.patch.object(svc.ntpath, "join", os.path.join):
                self.assertEqual(svc.ensure_nssm(d, opener=mock.Mock(side_effect=AssertionError)), (path, ""))

    def test_download_extracts_the_right_architecture(self):
        import contextlib
        import io
        import tempfile
        data = self.archive()

        @contextlib.contextmanager
        def opener(url, timeout=None):
            self.assertTrue(url.startswith("https://"))
            yield io.BytesIO(data)

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(svc, "find_nssm", return_value=None), \
                mock.patch.object(svc.ntpath, "join", os.path.join), \
                mock.patch("platform.machine", return_value="AMD64"):
            path, err = svc.ensure_nssm(d, opener=opener)
            self.assertEqual(err, "")
            with open(path) as f:
                self.assertEqual(f.read(), "win64")

    def test_download_failure_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(svc, "find_nssm", return_value=None):
            path, err = svc.ensure_nssm(d, opener=mock.Mock(side_effect=OSError("offline")))
        self.assertIsNone(path)
        self.assertIn("offline", err)
