import ast
import glob
import os
import unittest
import zipfile

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "build_release_windows", os.path.join(ROOT, "Windows", "build_release.py"))
build_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_release)


def core_modules():
    return {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "core", "*.py"))}


class TestWindowsPackage(unittest.TestCase):
    def test_sources_exist(self):
        for fname in build_release.PACKAGE_FILES:
            self.assertTrue(os.path.exists(build_release.source_path(fname)), fname)

    def test_no_linux_module(self):
        self.assertNotIn("platform_linux.py", build_release.PACKAGE_FILES)
        self.assertIn("platform_windows.py", build_release.PACKAGE_FILES)

    def test_every_plat_win_module_ships(self):
        wanted = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "core", "plat_win_*.py"))}
        self.assertLessEqual(wanted, set(build_release.PACKAGE_FILES))

    def test_all_imported_modules_are_packaged(self):
        shipped = set(build_release.PACKAGE_FILES)
        local = core_modules() - {"platform_linux"}
        for fname in shipped:
            if not fname.endswith(".py"):
                continue
            with open(build_release.source_path(fname), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    names = [node.module.split(".")[0]]
                for name in names:
                    if name in local:
                        self.assertIn(name + ".py", shipped, f"{fname} imports {name}")

    def test_layout_is_flat_under_mcmanager(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            saved = build_release.DIST_DIR
            build_release.DIST_DIR = tmp
            try:
                build_release.build_zip("probe.zip")
            finally:
                build_release.DIST_DIR = saved
            with zipfile.ZipFile(os.path.join(tmp, "probe.zip")) as zf:
                names = zf.namelist()
        self.assertTrue(all(n.startswith("MCManager/") and n.count("/") == 1 for n in names))
        self.assertIn("MCManager/mc_cli.py", names)
        self.assertEqual(len(names), len(build_release.PACKAGE_FILES))


if __name__ == "__main__":
    unittest.main()
