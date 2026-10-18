"""Fails when the suite leaves files behind in core/."""
import unittest

import test_00_hermetic as h


class Hygiene(unittest.TestCase):
    def test_core_untouched(self):
        self.assertEqual(sorted(h.snapshot() - h.BEFORE), [])
