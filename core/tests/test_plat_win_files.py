import ntpath
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plat_win_files as files


def env(**kw):
    return mock.patch.dict(os.environ, kw, clear=True)


class TestCurrentUser(unittest.TestCase):
    def test_domain_and_user(self):
        with env(USERDOMAIN="PC-DE-JOSÉ", USERNAME="José Müller"):
            self.assertEqual(files.current_user(), "PC-DE-JOSÉ\\José Müller")

    def test_no_domain(self):
        with env(USERNAME="cris"):
            self.assertEqual(files.current_user(), "cris")


class TestSecure(unittest.TestCase):
    def test_file_command_is_a_list_with_spaces_and_accents(self):
        path = "C:\\Users\\José Müller\\AppData\\Roaming\\MCManager\\servers.json"
        with env(USERDOMAIN="PC", USERNAME="José Müller"), \
                mock.patch.object(files.common, "run", return_value=(0, "", "")) as run:
            self.assertTrue(files.secure_file(path))
        self.assertEqual(run.call_args[0][0], [
            "icacls", path, "/inheritance:r", "/grant:r", "PC\\José Müller:F"])

    def test_dir_inherits_to_children(self):
        with env(USERDOMAIN="PC", USERNAME="cris"), \
                mock.patch.object(files.common, "run", return_value=(0, "", "")) as run:
            self.assertTrue(files.secure_dir("C:\\Mon Dossier"))
        self.assertEqual(run.call_args[0][0][-1], "PC\\cris:(OI)(CI)F")

    def test_extra_principal(self):
        with env(USERNAME="cris"), \
                mock.patch.object(files.common, "run", return_value=(0, "", "")) as run:
            files.secure_file("x", also=("SYSTEM",))
        self.assertEqual(run.call_args[0][0][-2:], ["/grant:r", "SYSTEM:F"])

    def test_failure_is_false(self):
        with env(USERNAME="cris"), mock.patch.object(files.common, "run", return_value=(5, "", "Access is denied.")):
            self.assertFalse(files.secure_file("x"))
            self.assertFalse(files.secure_dir("x"))

    def test_privacy_not_checkable(self):
        self.assertEqual(files.file_is_private("x"), (None, ""))


class TestDirs(unittest.TestCase):
    def test_data_dir(self):
        with env(APPDATA="C:\\Users\\Jo Smith\\AppData\\Roaming"):
            self.assertEqual(files.data_dir(), "C:\\Users\\Jo Smith\\AppData\\Roaming\\MCManager")

    def test_data_dir_override(self):
        with env(APPDATA="C:\\A", MCMANAGER_DATA_DIR=" D:\\Partage "):
            self.assertEqual(files.data_dir(), "D:\\Partage")

    def test_cache_dir(self):
        with env(LOCALAPPDATA="C:\\Users\\Jo\\AppData\\Local"):
            self.assertEqual(files.cache_dir(), "C:\\Users\\Jo\\AppData\\Local\\MCManager\\cache")

    def test_fallback_without_variables(self):
        with env(HOME="/h", USERPROFILE="C:\\Users\\Jo"):
            self.assertTrue(ntpath.basename(files.data_dir()) == "MCManager")
            self.assertTrue(files.cache_dir().endswith("MCManager\\cache"))


class TestOpenFolder(unittest.TestCase):
    def test_startfile_with_spaces(self):
        with mock.patch.object(os, "startfile", create=True) as start:
            self.assertTrue(files.open_folder("C:\\Mon Serveur"))
        start.assert_called_once_with("C:\\Mon Serveur")

    def test_startfile_error(self):
        with mock.patch.object(os, "startfile", create=True, side_effect=OSError):
            self.assertFalse(files.open_folder("C:\\x"))

    def test_explorer_fallback(self):
        with mock.patch.object(files.os, "startfile", None, create=True), \
                mock.patch.object(files.common, "run", return_value=(1, "", "")) as run:
            self.assertTrue(files.open_folder("C:\\Mon Serveur"))
        self.assertEqual(run.call_args[0][0], ["explorer", "C:\\Mon Serveur"])


class TestAtomicReplace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "dossier avec espaces", "a.tmp")
        os.makedirs(os.path.dirname(self.src))
        self.dst = os.path.join(os.path.dirname(self.src), "b.json")
        with open(self.src, "w") as f:
            f.write("new")

    def test_plain(self):
        files.atomic_replace(self.src, self.dst)
        with open(self.dst) as f:
            self.assertEqual(f.read(), "new")

    def test_retries_while_locked(self):
        real = os.replace
        calls = []

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, "locked")
            real(a, b)

        with mock.patch.object(files.os, "replace", flaky), mock.patch.object(files.time, "sleep") as sleep:
            files.atomic_replace(self.src, self.dst)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(os.path.exists(self.dst))

    def test_winerror_32_is_retried(self):
        err = OSError(32, "used")
        err.winerror = 32
        with mock.patch.object(files.os, "replace", side_effect=err), \
                mock.patch.object(files.time, "sleep"):
            with self.assertRaises(OSError):
                files.atomic_replace(self.src, self.dst, attempts=3)

    def test_gives_up_with_the_last_error(self):
        with mock.patch.object(files.os, "replace", side_effect=PermissionError(13, "locked")) as rep, \
                mock.patch.object(files.time, "sleep"):
            with self.assertRaises(PermissionError):
                files.atomic_replace(self.src, self.dst, attempts=4)
        self.assertEqual(rep.call_count, 4)

    def test_other_errors_fail_at_once(self):
        with mock.patch.object(files.os, "replace", side_effect=FileNotFoundError()) as rep:
            with self.assertRaises(FileNotFoundError):
                files.atomic_replace(self.src, self.dst)
        self.assertEqual(rep.call_count, 1)


class TestWritePrivate(unittest.TestCase):
    def test_lf_no_bom_and_secured(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with mock.patch.object(files, "secure_file", return_value=True) as sec:
                files.write_private_file(path, "a\nb\n")
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"a\nb\n")
            sec.assert_called_once()
            self.assertEqual(os.listdir(d), ["config.json"])


class TestMisc(unittest.TestCase):
    def test_archive_kind(self):
        self.assertEqual(files.java_archive_kind(), "zip")

    def test_not_elevated_off_windows(self):
        with mock.patch.object(files.common, "is_windows", return_value=False):
            self.assertFalse(files.is_elevated())


if __name__ == "__main__":
    unittest.main()
