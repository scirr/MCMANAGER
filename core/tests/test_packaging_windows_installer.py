import importlib.util
import os
import re
import tempfile
import unittest
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")


def load(name, *path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load("build_installer", "packaging", "windows", "build_installer.py")
windows_zip = load("build_release_windows_installer", "Windows", "build_release.py")


def fake_embeddable(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("python.exe", b"exe")
        zf.writestr("python312.zip", b"stdlib")
        zf.writestr("python312._pth", "python312.zip\n.\n\n#import site\n")


class StageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        saved = windows_zip.DIST_DIR
        windows_zip.DIST_DIR = self.tmp
        try:
            windows_zip.build_zip("MCManager.zip")
        finally:
            windows_zip.DIST_DIR = saved
        self.zip = os.path.join(self.tmp, "MCManager.zip")
        self.app = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(self.app, "Strings"))
        for name in ("MCManager.exe", os.path.join("Strings", "x.resw")):
            with open(os.path.join(self.app, name), "wb") as f:
                f.write(b"x")
        self.python = os.path.join(self.tmp, "embed.zip")
        fake_embeddable(self.python)
        self.stage = installer.stage(self.zip, self.app, os.path.join(self.tmp, "stage"), self.python)

    def test_layout(self):
        self.assertTrue(os.path.isfile(os.path.join(self.stage, "python", "python.exe")))
        self.assertTrue(os.path.isfile(os.path.join(self.stage, "core", "mc_cli.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.stage, "core", "platform_windows.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.stage, "app", "MCManager.exe")))
        self.assertTrue(os.path.isfile(os.path.join(self.stage, "app", "Strings", "x.resw")))

    def test_installer_replaces_the_batch_scripts(self):
        names = os.listdir(os.path.join(self.stage, "core"))
        self.assertNotIn("install.bat", names)
        self.assertNotIn("uninstall.bat", names)
        self.assertNotIn("language.txt", names)

    def test_path_file_lets_the_embedded_python_import_the_core(self):
        with open(os.path.join(self.stage, "python", "python312._pth"), newline="") as f:
            text = f.read()
        self.assertEqual(text.split("\r\n")[:3], ["python312.zip", ".", "..\\core"])
        self.assertNotIn("#import site", text)

    def test_app_must_be_published(self):
        os.remove(os.path.join(self.app, "MCManager.exe"))
        with self.assertRaises(FileNotFoundError):
            installer.stage(self.zip, self.app, os.path.join(self.tmp, "stage2"), self.python)


class ScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(installer.SCRIPT, encoding="utf-8") as f:
            cls.iss = f.read()

    def test_pinned_python(self):
        self.assertRegex(installer.PYTHON_SHA256, r"^[0-9a-f]{64}$")
        self.assertIn(installer.PYTHON_VERSION, installer.PYTHON_URL)
        self.assertTrue(installer.PYTHON_URL.startswith("https://www.python.org/ftp/python/"))

    def test_command_line(self):
        cmd = installer.iscc_command("ISCC.exe", "3.0.0", "S", "O")
        self.assertIn("/DAppVersion=3.0.0", cmd)
        self.assertEqual(cmd[-1], installer.SCRIPT)

    def test_service_and_environment_match_the_core(self):
        sys_path = os.path.join(ROOT, "core")
        with open(os.path.join(sys_path, "plat_win_service.py"), encoding="utf-8") as f:
            service = re.search(r'^SERVICE_NAME = "([^"]+)"', f.read(), re.M).group(1)
        self.assertIn(f'#define ServiceName "{service}"', self.iss)
        self.assertIn("MCMANAGER_DATA_DIR", self.iss)

    def test_uninstall_never_touches_servers(self):
        deletes = re.search(r"\[UninstallDelete\](.*?)(?=\n\[|\Z)", self.iss, re.S).group(1)
        self.assertNotIn("commonappdata", deletes)
        self.assertNotIn("Servers", deletes)
        self.assertNotIn("servers.json", deletes)

    def test_launcher_and_service_use_the_embedded_python(self):
        self.assertIn(r'{app}\python\python.exe', self.iss)
        self.assertIn("--install-only", self.iss)
        self.assertIn("--install-daemon", self.iss)

    def test_no_certificate_means_unsigned(self):
        self.assertFalse(installer.sign_installer("x.exe", env={}))


if __name__ == "__main__":
    unittest.main()
