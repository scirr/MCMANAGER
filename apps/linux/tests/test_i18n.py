import re
import unittest

from mcmanager_app import i18n


class TestI18n(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(set(i18n.TEXTS["en"]), set(i18n.TEXTS["fr"]))

    def test_placeholders_match(self):
        for key, text in i18n.TEXTS["en"].items():
            self.assertEqual(sorted(re.findall(r"{(\w+)}", text)),
                             sorted(re.findall(r"{(\w+)}", i18n.TEXTS["fr"][key])), key)

    def test_no_empty_text(self):
        for table in i18n.TEXTS.values():
            self.assertTrue(all(table.values()))

    def test_system_language(self):
        self.assertEqual(i18n.system_language({"LANG": "fr_FR.UTF-8"}), "fr")
        self.assertEqual(i18n.system_language({"LANGUAGE": "de:fr"}), "en")
        self.assertEqual(i18n.system_language({"LANGUAGE": "fr:en"}), "fr")
        self.assertEqual(i18n.system_language({}), "en")

    def test_fallbacks(self):
        i18n.set_language("fr")
        self.addCleanup(i18n.set_language, "en")
        self.assertEqual(i18n.t("start"), "Démarrer")
        self.assertEqual(i18n.t("missing_key"), "missing_key")
        self.assertIn("x", i18n.error_text("x"))
        i18n.set_language("xx")
        self.assertEqual(i18n.language(), "en")

    def test_every_error_text_used_by_the_models_exists(self):
        for code in ("unauthorized", "forbidden", "not_found", "server_running", "console_offline", "bad_pair_code",
                     "invalid_name", "kick_offline", "player_not_online", "rcon_failed"):
            self.assertNotIn("(", i18n.error_text(code))


if __name__ == "__main__":
    unittest.main()
