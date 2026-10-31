import importlib.util
import os
import plistlib
import stat
import struct
import tempfile
import unittest
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
_spec = importlib.util.spec_from_file_location("build_app_macos", os.path.join(ROOT, "packaging", "macos", "build_app.py"))
build_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_app)


class AppBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = cls._tmp.name
        cls.bin = os.path.join(cls.tmp, "release")
        os.makedirs(os.path.join(cls.bin, "MCManager_MCManagerApp.bundle", "Contents"))
        with open(os.path.join(cls.bin, build_app.EXECUTABLE), "wb") as f:
            f.write(b"\xcf\xfa\xed\xfe")
        os.chmod(os.path.join(cls.bin, build_app.EXECUTABLE), 0o755)
        with open(os.path.join(cls.bin, "MCManager_MCManagerApp.bundle", "Contents", "Info.plist"), "wb") as f:
            f.write(b"x")
        cls.app = os.path.join(cls.tmp, "MCManager.app")
        build_app.assemble(cls.bin, cls.app, "3.0.0")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_layout(self):
        for rel in ("Contents/MacOS/MCManager", "Contents/Info.plist", "Contents/Resources/MCManager.icns",
                    "Contents/Resources/MCManager_MCManagerApp.bundle/Contents/Info.plist"):
            self.assertTrue(os.path.exists(os.path.join(self.app, rel)), rel)
        if os.name != "nt":
            self.assertTrue(os.stat(os.path.join(self.app, "Contents/MacOS/MCManager")).st_mode & stat.S_IXUSR)

    def test_info_plist(self):
        with open(os.path.join(self.app, "Contents", "Info.plist"), "rb") as f:
            info = plistlib.load(f)
        self.assertEqual(info["CFBundleExecutable"], "MCManager")
        self.assertEqual(info["CFBundleIdentifier"], "io.github.scirr.MCManager")
        self.assertEqual(info["CFBundleShortVersionString"], "3.0.0")
        self.assertEqual(info["CFBundleIconFile"], "MCManager")
        self.assertEqual(info["LSMinimumSystemVersion"], "14.0")

    def test_version_matches_the_application(self):
        import sys
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import mc_lang
        self.assertEqual(build_app.read_version(), mc_lang.VERSION)

    def test_icon_is_a_valid_icns(self):
        with open(os.path.join(self.app, "Contents/Resources/MCManager.icns"), "rb") as f:
            data = f.read()
        self.assertEqual(data[:4], b"icns")
        self.assertEqual(struct.unpack(">I", data[4:8])[0], len(data))
        pos, kinds = 8, []
        while pos < len(data):
            kind, size = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
            self.assertEqual(data[pos + 8:pos + 16], b"\x89PNG\r\n\x1a\n")
            kinds.append(kind)
            pos += size
        self.assertEqual(kinds, [b"ic07", b"ic08", b"ic09"])

    def test_zip_keeps_the_app_folder_and_the_executable_bit(self):
        zip_path = build_app.zip_app(self.app, os.path.join(self.tmp, build_app.ZIP_NAME))
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            self.assertTrue(all(n.startswith("MCManager.app/") for n in names))
            info = zf.getinfo("MCManager.app/Contents/MacOS/MCManager")
            self.assertTrue((info.external_attr >> 16) & stat.S_IXUSR)

    def test_missing_build_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            build_app.assemble(os.path.join(self.tmp, "nothing"), os.path.join(self.tmp, "x.app"), "3.0.0")

    def test_zip_name_cannot_be_taken_for_the_core_package(self):
        import sys
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import mc_update
        self.assertNotIn(build_app.ZIP_NAME, set(mc_update.ASSETS.values()) | {mc_update.asset_for("linux")})


if __name__ == "__main__":
    unittest.main()
