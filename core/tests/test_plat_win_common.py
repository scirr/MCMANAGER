import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plat_win_common as common


def completed(out=b"", err=b"", rc=0):
    return subprocess.CompletedProcess([], rc, out, err)


class TestRun(unittest.TestCase):
    def test_decodes_requested_codepage(self):
        with mock.patch("subprocess.run", return_value=completed("Aucune règle".encode("cp850"))):
            rc, out, _ = common.run(["netsh"], encoding="cp850")
        self.assertEqual(out, "Aucune règle")

    def test_oem_never_raises_off_windows(self):
        with mock.patch("subprocess.run", return_value=completed(b"ok")):
            self.assertEqual(common.run(["x"])[1], "ok")

    def test_invalid_bytes_are_replaced(self):
        with mock.patch("subprocess.run", return_value=completed(b"a\xffb")):
            self.assertIn("a", common.run(["x"], encoding="utf-8")[1])

    def test_missing_command(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("nope")):
            self.assertEqual(common.run(["x"])[0], 127)

    def test_timeout(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(common.run(["x"])[0], 124)


class TestPowerShell(unittest.TestCase):
    def test_command_line_and_utf8(self):
        with mock.patch("subprocess.run", return_value=completed("﻿é".encode("utf-8"))) as m:
            rc, out, _ = common.run_powershell("Get-Date")
        cmd = m.call_args[0][0]
        self.assertEqual(cmd[:4], ["powershell", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertIn("[Console]::OutputEncoding=[Text.Encoding]::UTF8", cmd[4])
        self.assertTrue(cmd[4].endswith("Get-Date"))
        self.assertEqual(out, "é")


class TestMisc(unittest.TestCase):
    def test_unsupported_code(self):
        self.assertEqual(common.Unsupported.code, "unsupported_on_windows")

    def test_is_windows(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertTrue(common.is_windows())
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(common.is_windows())


if __name__ == "__main__":
    unittest.main()
