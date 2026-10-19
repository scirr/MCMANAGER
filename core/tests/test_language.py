"""
test_language.py — Runtime language selection.

The active language is persisted in language.txt and applied by mutating the
shared T dict in place (so `from mc_lang import T` stays valid after a switch).
"""
import sys
import os
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_lang


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved_file = mc_lang._LANG_FILE
        self._saved_lang = mc_lang.current_language()
        mc_lang._LANG_FILE = os.path.join(self.tmp.name, "language.txt")

    def tearDown(self):
        mc_lang._LANG_FILE = self._saved_file
        mc_lang._apply_language(self._saved_lang)
        self.tmp.cleanup()

    def test_unset_when_no_file(self):
        self.assertFalse(mc_lang.is_language_set())

    def test_set_persists_and_reads_back(self):
        mc_lang.set_language("en")
        self.assertTrue(mc_lang.is_language_set())
        self.assertEqual(mc_lang.current_language(), "en")
        self.assertEqual(mc_lang._read_saved_language(), "en")

    def test_switch_applies_in_place(self):
        same_dict = mc_lang.T
        mc_lang.set_language("en")
        self.assertEqual(mc_lang.T["yn_yes"], "[Y/n]")
        mc_lang.set_language("fr")
        self.assertEqual(mc_lang.T["yn_yes"], "[O/n]")
        # T must never be reassigned, only mutated
        self.assertIs(same_dict, mc_lang.T)

    def test_invalid_language_defaults_to_fr(self):
        mc_lang._apply_language("de")
        self.assertEqual(mc_lang.current_language(), "fr")

    def test_persisted_invalid_value_is_ignored(self):
        with open(mc_lang._LANG_FILE, "w", encoding="utf-8") as f:
            f.write("de")
        self.assertIsNone(mc_lang._read_saved_language())
        self.assertFalse(mc_lang.is_language_set())

    def test_set_language_normalises(self):
        self.assertEqual(mc_lang.set_language("EN"), "en")
        self.assertEqual(mc_lang.set_language("anything-else"), "fr")


if __name__ == "__main__":
    unittest.main()


class TestNoPromptWithoutKeyboard(unittest.TestCase):
    def test_json_callers_are_never_prompted(self):
        import mc_cli
        with mock.patch.object(mc_cli.mc_lang, "is_language_set", return_value=False), \
             mock.patch.object(sys, "argv", ["mc", "status", "--json"]), \
             mock.patch("builtins.input", side_effect=AssertionError("prompted")):
            mc_cli.prompt_language_if_unset()

    def test_windows_nul_device_is_not_a_keyboard(self):
        import ctypes
        import mc_cli
        fake = mock.Mock()
        fake.kernel32.GetConsoleMode.return_value = 0
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(ctypes, "windll", fake, create=True):
            self.assertFalse(mc_cli.stdin_interactive())
        fake.kernel32.GetConsoleMode.return_value = 1
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(ctypes, "windll", fake, create=True):
            self.assertTrue(mc_cli.stdin_interactive())
