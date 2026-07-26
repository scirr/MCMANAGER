"""
test_lang_parity.py — Verifies that all keys exist in both languages
and that placeholders {xxx} are identical.
"""
import re
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_lang


def _placeholders(s):
    return sorted(re.findall(r'\{(\w+)\}', str(s)))


class TestLangParity(unittest.TestCase):

    def test_all_fr_keys_in_en(self):
        missing = set(mc_lang._FR) - set(mc_lang._EN)
        self.assertFalse(missing, f"Clés présentes en FR mais absentes en EN : {missing}")

    def test_all_en_keys_in_fr(self):
        missing = set(mc_lang._EN) - set(mc_lang._FR)
        self.assertFalse(missing, f"Clés présentes en EN mais absentes en FR : {missing}")

    def test_placeholder_parity(self):
        mismatches = {}
        for key in mc_lang._FR:
            fr_ph = _placeholders(mc_lang._FR[key])
            en_ph = _placeholders(mc_lang._EN.get(key, ""))
            if fr_ph != en_ph:
                mismatches[key] = {"fr": fr_ph, "en": en_ph}
        self.assertFalse(mismatches,
            "Placeholders différents entre FR et EN :\n" +
            "\n".join(f"  {k}: FR={v['fr']} EN={v['en']}" for k, v in mismatches.items()))

    def test_no_empty_values(self):
        empty = [k for k, v in mc_lang._FR.items() if str(v).strip() == ""]
        self.assertFalse(empty, f"Valeurs vides en FR : {empty}")
        empty = [k for k, v in mc_lang._EN.items() if str(v).strip() == ""]
        self.assertFalse(empty, f"Valeurs vides en EN : {empty}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
