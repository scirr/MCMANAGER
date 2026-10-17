"""
test_deploy.py — Pure deployment helpers.

neoforge_version_prefix maps a Minecraft version to the NeoForge API prefix
filter. The trailing dot is essential: without it, "21.1" also matches
"21.11.*" (Minecraft 1.21.11) because the API filter is a prefix match.
"""
import sys
import os
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_deploy
import mc_config


class NeoForgeVersionPrefixTests(unittest.TestCase):
    def test_patch_version(self):
        self.assertEqual(mc_deploy.neoforge_version_prefix("1.21.1"), "21.1.")

    def test_no_patch_version_defaults_minor_zero(self):
        self.assertEqual(mc_deploy.neoforge_version_prefix("1.21"), "21.0.")

    def test_other_major(self):
        self.assertEqual(mc_deploy.neoforge_version_prefix("1.20.4"), "20.4.")

    def test_double_digit_patch(self):
        self.assertEqual(mc_deploy.neoforge_version_prefix("1.21.11"), "21.11.")

    def test_always_ends_with_dot(self):
        for v in ("1.21", "1.21.1", "1.20.4", "1.21.11"):
            self.assertTrue(mc_deploy.neoforge_version_prefix(v).endswith("."))

    def test_prefix_does_not_collide_with_higher_minor(self):
        # The whole point of the fix: 1.21.1 must NOT produce a prefix that
        # 1.21.11's version string would also start with.
        p1 = mc_deploy.neoforge_version_prefix("1.21.1")   # "21.1."
        self.assertFalse("21.11.44".startswith(p1))
        self.assertTrue("21.1.243".startswith(p1))


class DetectDefaultJarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, name):
        with open(os.path.join(self.d, name), "w") as f:
            f.write("")

    def test_runsh_wins_over_jars(self):
        # Forge/NeoForge: run.sh is the launcher, no single runnable jar.
        self._touch("run.sh")
        self.assertEqual(mc_config.detect_default_jar(self.d), "run.sh")

    def test_single_jar(self):
        self._touch("paper-1.21.1.jar")
        self.assertEqual(mc_config.detect_default_jar(self.d), "paper-1.21.1.jar")

    def test_no_jar_no_script_falls_back(self):
        self.assertEqual(mc_config.detect_default_jar(self.d), "fabric-server-launch.jar")


if __name__ == "__main__":
    unittest.main()
