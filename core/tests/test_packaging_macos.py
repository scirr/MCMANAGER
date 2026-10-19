import importlib.util
import os
import tempfile
import unittest
import zipfile

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_spec = importlib.util.spec_from_file_location("build_release_macos", os.path.join(ROOT, "macOS", "build_release.py"))
build_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_release)


class TestMacPackage(unittest.TestCase):
    def test_sources_exist(self):
        for fname in build_release.PACKAGE_FILES:
            self.assertTrue(os.path.exists(build_release.source_path(fname)), fname)

    def test_platform_modules(self):
        files = build_release.PACKAGE_FILES
        self.assertIn("platform_macos.py", files)
        self.assertIn("plat_posix.py", files)
        self.assertNotIn("platform_linux.py", files)
        self.assertNotIn("platform_windows.py", files)

    def test_zip_layout_and_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_release.build_zip("MCManager-macOS.zip", tmp)
            with zipfile.ZipFile(os.path.join(tmp, "MCManager-macOS.zip")) as zf:
                names = set(zf.namelist())
                self.assertIn("MCManager/mc_config.py", names)
                self.assertIn("MCManager/install.sh", names)
                self.assertEqual(zf.getinfo("MCManager/install.sh").external_attr >> 16, 0o755)
                self.assertEqual(zf.getinfo("MCManager/uninstall.sh").external_attr >> 16, 0o755)

    def test_install_script_refuses_sudo_and_source_folder(self):
        with open(os.path.join(ROOT, "macOS", "install.sh"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("This is the source folder", text)
        self.assertIn('"$(id -u)" -eq 0', text)
