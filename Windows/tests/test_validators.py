"""
test_validators.py — Unit tests for pure validation functions (mc_validate).
These functions have no dependencies and are tested directly.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mc_validate import valid_port, valid_ram, valid_cpu, valid_bool


class TestValidPort(unittest.TestCase):
    def test_valid_standard(self):
        for p in [1, 25, 80, 443, 25565, 25575, 65535]:
            with self.subTest(port=p):
                self.assertTrue(valid_port(p))

    def test_valid_string(self):
        self.assertTrue(valid_port("25565"))
        self.assertTrue(valid_port("1"))
        self.assertTrue(valid_port("65535"))

    def test_invalid_zero(self):
        self.assertFalse(valid_port(0))

    def test_invalid_negative(self):
        self.assertFalse(valid_port(-1))
        self.assertFalse(valid_port(-100))

    def test_invalid_above_max(self):
        self.assertFalse(valid_port(65536))
        self.assertFalse(valid_port(99999))

    def test_invalid_non_numeric(self):
        self.assertFalse(valid_port("abc"))
        self.assertFalse(valid_port(""))
        self.assertFalse(valid_port(None))
        self.assertFalse(valid_port("25565abc"))


class TestValidRam(unittest.TestCase):
    def test_valid_gigabytes(self):
        for v in ["1G", "4G", "8G", "16G", "32G", "1g", "8g"]:
            with self.subTest(val=v):
                self.assertTrue(valid_ram(v))

    def test_valid_megabytes(self):
        for v in ["512M", "1024M", "4096M", "8192M", "512m", "4096m"]:
            with self.subTest(val=v):
                self.assertTrue(valid_ram(v))

    def test_invalid_no_unit(self):
        self.assertFalse(valid_ram("4"))
        self.assertFalse(valid_ram("1024"))

    def test_invalid_wrong_unit(self):
        self.assertFalse(valid_ram("4GB"))
        self.assertFalse(valid_ram("4MB"))
        self.assertFalse(valid_ram("4K"))

    def test_invalid_zero(self):
        self.assertFalse(valid_ram("0G"))
        self.assertFalse(valid_ram("0M"))

    def test_invalid_empty(self):
        self.assertFalse(valid_ram(""))

    def test_invalid_text(self):
        self.assertFalse(valid_ram("abc"))
        self.assertFalse(valid_ram("fourG"))

    def test_invalid_decimal(self):
        self.assertFalse(valid_ram("4.5G"))
        self.assertFalse(valid_ram("2.5M"))


class TestValidCpu(unittest.TestCase):
    def test_single_core(self):
        self.assertTrue(valid_cpu("0"))
        self.assertTrue(valid_cpu("7"))
        self.assertTrue(valid_cpu("15"))

    def test_range(self):
        self.assertTrue(valid_cpu("0-7"))
        self.assertTrue(valid_cpu("8-15"))
        self.assertTrue(valid_cpu("0-3"))

    def test_list(self):
        self.assertTrue(valid_cpu("0,1,2,3"))
        self.assertTrue(valid_cpu("0,2,4"))

    def test_mixed(self):
        self.assertTrue(valid_cpu("0-3,8-11"))
        self.assertTrue(valid_cpu("0,4-7,12"))

    def test_invalid_letters(self):
        self.assertFalse(valid_cpu("a-b"))
        self.assertFalse(valid_cpu("abc"))

    def test_invalid_empty(self):
        self.assertFalse(valid_cpu(""))

    def test_invalid_negative(self):
        self.assertFalse(valid_cpu("-1"))
        self.assertFalse(valid_cpu("0--7"))

    def test_invalid_trailing_comma(self):
        self.assertFalse(valid_cpu("0,1,"))

    def test_invalid_spaces(self):
        # Spaces around the string are stripped, but inside are not
        self.assertFalse(valid_cpu("0 - 7"))
        self.assertFalse(valid_cpu("0, 1"))


class TestValidBool(unittest.TestCase):
    def test_valid_zero(self):
        self.assertTrue(valid_bool(0))
        self.assertTrue(valid_bool("0"))

    def test_valid_one(self):
        self.assertTrue(valid_bool(1))
        self.assertTrue(valid_bool("1"))

    def test_invalid_two(self):
        self.assertFalse(valid_bool(2))
        self.assertFalse(valid_bool("2"))

    def test_invalid_negative(self):
        self.assertFalse(valid_bool(-1))

    def test_invalid_text(self):
        self.assertFalse(valid_bool("oui"))
        self.assertFalse(valid_bool("yes"))
        self.assertFalse(valid_bool("true"))
        self.assertFalse(valid_bool(""))
        self.assertFalse(valid_bool(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
