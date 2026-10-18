import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import mc_core
import mc_platform
from fake_platform import FakePlatform

UNIX = (
    "-DlibraryDirectory=libraries\n"
    "-p\n"
    "libraries/cpw/a.jar:libraries/cpw/b.jar\n"
    "--add-modules\n"
    "ALL-MODULE-PATH\n"
    "-DlegacyClassPath=libraries/x/c.jar:libraries/y/d.jar\n"
    "-DignoreList=a,b:c\n"
    "cpw.mods.bootstraplauncher.BootstrapLauncher\n"
)
INLINE = "-p libraries/a.jar:libraries/b.jar\n-DignoreList=a:b\nMain\n"
SUB = os.path.join("libraries", "net", "neoforged", "neoforge", "21.1.248")


class DirectLaunch(unittest.TestCase):
    def setUp(self):
        saved = mc_platform._Lazy._impl
        self.addCleanup(setattr, mc_platform._Lazy, "_impl", saved)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def use(self, **results):
        fake = FakePlatform(**results)
        mc_platform.use(fake)
        return fake

    def forge(self, name="unix_args.txt", text=UNIX):
        folder = os.path.join(self.dir, SUB)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)

    def config(self, jar="run.sh"):
        return {"jar_name": jar, "ram_allocation": "4G", "java_flags": "-XX:+UseG1GC"}

    def test_linux_runs_java_on_unix_args(self):
        self.use()
        self.forge()
        args, direct = mc_core.build_launch_args(self.config(), "java", self.dir)
        self.assertTrue(direct)
        self.assertEqual(args, ["java", "-Dmcmanager.server=" + self.dir, "@user_jvm_args.txt",
                                "@" + SUB.replace(os.sep, "/") + "/unix_args.txt", "nogui"])

    def test_windows_generates_win_args_from_unix_args(self):
        self.use(launch_args_name="win_args.txt", server_script_name="run.bat")
        self.forge()
        args, direct = mc_core.build_launch_args(self.config("run.bat"), "java", self.dir)
        self.assertTrue(direct)
        self.assertTrue(args[-2].endswith("/win_args.txt"))
        with open(os.path.join(self.dir, SUB, "win_args.txt"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("libraries/cpw/a.jar;libraries/cpw/b.jar", text)
        self.assertIn("-DlegacyClassPath=libraries/x/c.jar;libraries/y/d.jar", text)
        self.assertIn("-DignoreList=a,b:c", text)
        self.assertNotIn("\r", text)

    def test_inline_module_path(self):
        self.assertIn("-p libraries/a.jar;libraries/b.jar", mc_core._to_windows_args(INLINE))
        self.assertIn("-DignoreList=a:b", mc_core._to_windows_args(INLINE))

    def test_existing_win_args_are_kept(self):
        self.use(launch_args_name="win_args.txt", server_script_name="run.bat")
        self.forge()
        self.forge("win_args.txt", "custom\n")
        mc_core.build_launch_args(self.config("run.bat"), "java", self.dir)
        with open(os.path.join(self.dir, SUB, "win_args.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "custom\n")

    def test_missing_args_files_fall_back_to_the_script(self):
        fake = self.use()
        args, direct = mc_core.build_launch_args(self.config(), "java", self.dir)
        self.assertFalse(direct)
        self.assertEqual(args, ["sh", "run.sh", "nogui"])
        self.assertEqual(fake.called("script_launch_args"), [("run.sh",)])

    def test_plain_jar_carries_the_marker(self):
        self.use()
        args, direct = mc_core.build_launch_args(self.config("server.jar"), "java", self.dir)
        self.assertTrue(direct)
        self.assertIn("-Dmcmanager.server=" + self.dir, args)
        self.assertLess(args.index("-Dmcmanager.server=" + self.dir), args.index("-jar"))
        self.assertEqual(args[-1], "nogui")

    def test_script_test_follows_the_platform(self):
        self.use(server_script_name="run.bat")
        self.assertTrue(mc_core.is_run_script("run.bat"))
        self.assertFalse(mc_core.is_run_script("run.sh"))
        self.assertFalse(mc_core.is_run_script("server.jar"))


if __name__ == "__main__":
    unittest.main()
