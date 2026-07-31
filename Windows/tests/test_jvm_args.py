"""
test_jvm_args.py — Heap sync into Forge/NeoForge's user_jvm_args.txt.

Servers launched through run.bat read their heap from that file, so the RAM
configured in MC Manager has to be written into it — without destroying the
comments that document the file, and without gluing flags onto its last line
(the stock file ends without a trailing newline).
"""
import sys
import os
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_core

# The stock NeoForge file: everything commented out, no trailing newline.
STOCK = (
    "# Xmx and Xms set the maximum and minimum RAM usage, respectively.\n"
    "# For example, to set the maximum to 3GB: -Xmx3G\n"
    "\n"
    "# A good default for a modded server is 4GB.\n"
    "# Uncomment the next line to set it.\n"
    "# -Xmx4G"
)


class SyncRunScriptRamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.path = os.path.join(self.dir, "user_jvm_args.txt")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, content):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)

    def _read(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def _active_flags(self):
        return [l.strip() for l in self._read().splitlines()
                if l.strip() and not l.strip().startswith("#")]

    def test_missing_file_is_noop(self):
        mc_core._sync_run_script_ram(self.dir, "8G")  # no file created
        self.assertFalse(os.path.exists(self.path))

    def test_writes_heap_flags(self):
        self._write(STOCK)
        mc_core._sync_run_script_ram(self.dir, "8G")
        self.assertEqual(self._active_flags(), ["-Xms8G", "-Xmx8G"])

    def test_keeps_comments(self):
        self._write(STOCK)
        mc_core._sync_run_script_ram(self.dir, "8G")
        content = self._read()
        self.assertIn("# A good default for a modded server is 4GB.", content)
        self.assertIn("# -Xmx4G", content)

    def test_no_trailing_newline_does_not_glue(self):
        self._write(STOCK)  # ends with "# -Xmx4G" and no newline
        mc_core._sync_run_script_ram(self.dir, "8G")
        self.assertNotIn("# -Xmx4G-Xms", self._read())

    def test_replaces_previous_active_flags(self):
        self._write("-Xms1G\n-Xmx2G\n")
        mc_core._sync_run_script_ram(self.dir, "8G")
        self.assertEqual(self._active_flags(), ["-Xms8G", "-Xmx8G"])

    def test_idempotent(self):
        self._write(STOCK)
        mc_core._sync_run_script_ram(self.dir, "8G")
        once = self._read()
        mc_core._sync_run_script_ram(self.dir, "8G")
        self.assertEqual(once, self._read())

    def test_ram_change_applies(self):
        self._write(STOCK)
        mc_core._sync_run_script_ram(self.dir, "8G")
        mc_core._sync_run_script_ram(self.dir, "12G")
        self.assertEqual(self._active_flags(), ["-Xms12G", "-Xmx12G"])

    def test_keeps_unrelated_active_flags(self):
        self._write("-XX:+UseG1GC\n-Xmx2G\n")
        mc_core._sync_run_script_ram(self.dir, "8G")
        self.assertIn("-XX:+UseG1GC", self._active_flags())

    def test_leaves_no_temp_file(self):
        self._write(STOCK)
        mc_core._sync_run_script_ram(self.dir, "8G")
        self.assertFalse(os.path.exists(self.path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
