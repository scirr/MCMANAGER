"""
test_prompts.py — Tests for interactive prompts with mocked builtins.input.
Validates validation loops for each user input, in both languages (FR and EN).
"""
import sys
import os
import unittest
from unittest.mock import patch

LINUX_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, LINUX_DIR)


def _switch_lang(lang):
    import mc_lang
    # T is mutated in place, so every module that imported it sees the change.
    mc_lang._apply_language(lang)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _run_with_inputs(func, inputs):
    """Run func() with a sequence of mocked input() values."""
    with patch("builtins.input", side_effect=inputs):
        return func()


# ─── Schedule CLI validation (direct function, no mc_cli wiring) ─────────────

def _validate_schedule(open_h, open_m, close_h, close_m, lang="fr"):
    """
    Reproduces the mc schedule handler validation logic.
    Returns the error message (str) or None if valid.
    """
    import mc_lang
    T = mc_lang._FR if lang == "fr" else mc_lang._EN
    if not (0 <= open_h <= 23):
        return T["invalid_hour"].format(val=open_h)
    if not (0 <= open_m <= 59):
        return T["invalid_minute"].format(val=open_m)
    if not (0 <= close_h <= 23):
        return T["invalid_hour"].format(val=close_h)
    if not (0 <= close_m <= 59):
        return T["invalid_minute"].format(val=close_m)
    return None


class TestScheduleValidation(unittest.TestCase):
    """Validates hour/minute validation logic of the mc schedule handler."""

    # ── Cas valides ──────────────────────────────────────────────────────────

    def test_valid_fr(self):
        self.assertIsNone(_validate_schedule(8, 0, 22, 30, "fr"))

    def test_valid_en(self):
        self.assertIsNone(_validate_schedule(0, 0, 23, 59, "en"))

    def test_boundary_hour_0_fr(self):
        self.assertIsNone(_validate_schedule(0, 0, 23, 59, "fr"))

    def test_boundary_hour_23_en(self):
        self.assertIsNone(_validate_schedule(23, 59, 0, 0, "en"))

    def test_boundary_minute_0_fr(self):
        self.assertIsNone(_validate_schedule(8, 0, 22, 0, "fr"))

    def test_boundary_minute_59_en(self):
        self.assertIsNone(_validate_schedule(8, 59, 22, 59, "en"))

    # ── Heure invalide ───────────────────────────────────────────────────────

    def test_invalid_open_hour_24_fr(self):
        msg = _validate_schedule(24, 0, 22, 0, "fr")
        self.assertIsNotNone(msg)
        self.assertIn("24", msg)

    def test_invalid_open_hour_24_en(self):
        msg = _validate_schedule(24, 0, 22, 0, "en")
        self.assertIsNotNone(msg)
        self.assertIn("24", msg)

    def test_invalid_open_hour_25_fr(self):
        msg = _validate_schedule(25, 0, 22, 0, "fr")
        self.assertIsNotNone(msg)
        self.assertIn("25", msg)

    def test_invalid_close_hour_24_fr(self):
        msg = _validate_schedule(8, 0, 24, 0, "fr")
        self.assertIsNotNone(msg)

    def test_invalid_close_hour_25_en(self):
        msg = _validate_schedule(8, 0, 25, 0, "en")
        self.assertIsNotNone(msg)

    def test_negative_open_hour_fr(self):
        msg = _validate_schedule(-1, 0, 22, 0, "fr")
        self.assertIsNotNone(msg)

    def test_negative_close_hour_en(self):
        msg = _validate_schedule(8, 0, -1, 0, "en")
        self.assertIsNotNone(msg)

    # ── Minute invalide ──────────────────────────────────────────────────────

    def test_invalid_open_minute_60_fr(self):
        msg = _validate_schedule(8, 60, 22, 0, "fr")
        self.assertIsNotNone(msg)
        self.assertIn("60", msg)

    def test_invalid_open_minute_60_en(self):
        msg = _validate_schedule(8, 60, 22, 0, "en")
        self.assertIsNotNone(msg)
        self.assertIn("60", msg)

    def test_invalid_open_minute_70_fr(self):
        msg = _validate_schedule(8, 70, 22, 0, "fr")
        self.assertIsNotNone(msg)
        self.assertIn("70", msg)

    def test_invalid_close_minute_60_fr(self):
        msg = _validate_schedule(8, 0, 22, 60, "fr")
        self.assertIsNotNone(msg)

    def test_invalid_close_minute_70_en(self):
        msg = _validate_schedule(8, 0, 22, 70, "en")
        self.assertIsNotNone(msg)

    def test_negative_open_minute(self):
        msg = _validate_schedule(8, -1, 22, 0, "fr")
        self.assertIsNotNone(msg)

    def test_negative_close_minute(self):
        msg = _validate_schedule(8, 0, 22, -1, "en")
        self.assertIsNotNone(msg)


# ─── mc_deploy helper functions ──────────────────────────────────────────────

class TestDeployAskNonempty(unittest.TestCase):
    """ask_nonempty loops until a non-empty string is entered."""

    def _run(self, inputs, default=""):
        import mc_deploy
        with patch("builtins.input", side_effect=inputs):
            return mc_deploy.ask_nonempty("Nom ?", default)

    def test_accepts_valid_immediately(self):
        result = self._run(["MonServeur"])
        self.assertEqual(result, "MonServeur")

    def test_accepts_default_on_enter(self):
        # Pressing Enter (empty input) with a non-empty default → accepts default
        result = self._run([""], default="Minecraft")
        self.assertEqual(result, "Minecraft")

    def test_rejects_empty_when_no_default(self):
        # Empty default + empty input → loop until real value
        result = self._run(["", "   ", "MonServeur"], default="")
        self.assertEqual(result, "MonServeur")

    def test_strips_whitespace(self):
        result = self._run(["  Toto  "])
        self.assertEqual(result, "Toto")


class TestDeployAskIntWithPort(unittest.TestCase):
    """ask_int with valid_port loops until port is in range."""

    def _run(self, inputs):
        import mc_deploy
        from mc_validate import valid_port
        with patch("builtins.input", side_effect=inputs):
            return mc_deploy.ask_int("Port ?", 25565,
                                     validate=valid_port, error_key="invalid_port")

    def test_accepts_valid_port(self):
        result = self._run(["25565"])
        self.assertEqual(result, 25565)

    def test_rejects_0_then_accepts(self):
        result = self._run(["0", "25565"])
        self.assertEqual(result, 25565)

    def test_rejects_65536_then_accepts(self):
        result = self._run(["65536", "80"])
        self.assertEqual(result, 80)

    def test_rejects_negative_then_accepts(self):
        result = self._run(["-1", "25565"])
        self.assertEqual(result, 25565)

    def test_rejects_text_then_accepts(self):
        result = self._run(["abc", "25565"])
        self.assertEqual(result, 25565)

    def test_accepts_boundary_1(self):
        result = self._run(["1"])
        self.assertEqual(result, 1)

    def test_accepts_boundary_65535(self):
        result = self._run(["65535"])
        self.assertEqual(result, 65535)


# ─── mc_config validators ────────────────────────────────────────────────────

class TestConfigSmartAskPort(unittest.TestCase):
    """_smart_ask_port in mc_config loops until port is valid."""

    def _run(self, inputs, lang="fr"):
        _switch_lang(lang)
        import mc_config
        config = {}
        with patch("builtins.input", side_effect=inputs):
            return mc_config._smart_ask_port("Port ?", "port", config, 25565)

    def test_valid_port_fr(self):
        result = self._run(["25565"], lang="fr")
        self.assertEqual(result, 25565)

    def test_valid_port_en(self):
        result = self._run(["25565"], lang="en")
        self.assertEqual(result, 25565)

    def test_invalid_0_then_valid_fr(self):
        result = self._run(["0", "25565"], lang="fr")
        self.assertEqual(result, 25565)

    def test_invalid_0_then_valid_en(self):
        result = self._run(["0", "25565"], lang="en")
        self.assertEqual(result, 25565)

    def test_invalid_above_max_fr(self):
        result = self._run(["99999", "25565"], lang="fr")
        self.assertEqual(result, 25565)

    def test_port_as_int(self):
        result = self._run(["8080"])
        self.assertIsInstance(result, int)


class TestConfigSmartAskBool(unittest.TestCase):
    """_smart_ask_bool loops until 0 or 1 is entered."""

    def _run(self, inputs, lang="fr"):
        _switch_lang(lang)
        import mc_config
        config = {}
        with patch("builtins.input", side_effect=inputs):
            return mc_config._smart_ask_bool("always_on ?", "always_on", config, 1)

    def test_accepts_0_fr(self):
        self.assertEqual(self._run(["0"], lang="fr"), 0)

    def test_accepts_1_en(self):
        self.assertEqual(self._run(["1"], lang="en"), 1)

    def test_rejects_2_then_accepts_fr(self):
        self.assertEqual(self._run(["2", "1"], lang="fr"), 1)

    def test_rejects_2_then_accepts_en(self):
        self.assertEqual(self._run(["2", "0"], lang="en"), 0)

    def test_rejects_text_fr(self):
        self.assertEqual(self._run(["oui", "1"], lang="fr"), 1)

    def test_rejects_text_en(self):
        self.assertEqual(self._run(["yes", "1"], lang="en"), 1)

    def test_rejects_negative(self):
        self.assertEqual(self._run(["-1", "0"]), 0)


class TestConfigSmartAskRam(unittest.TestCase):
    """_smart_ask_ram loops until a valid RAM format is entered."""

    def _run(self, inputs, lang="fr"):
        _switch_lang(lang)
        import mc_config
        config = {}
        with patch("builtins.input", side_effect=inputs):
            return mc_config._smart_ask_ram("RAM ?", "ram_allocation", config, "4G")

    def test_accepts_4G_fr(self):
        self.assertEqual(self._run(["4G"], lang="fr"), "4G")

    def test_accepts_8192M_en(self):
        self.assertEqual(self._run(["8192M"], lang="en"), "8192M")

    def test_rejects_no_unit_then_accepts_fr(self):
        self.assertEqual(self._run(["4096", "4G"], lang="fr"), "4G")

    def test_rejects_no_unit_then_accepts_en(self):
        self.assertEqual(self._run(["4096", "4G"], lang="en"), "4G")

    def test_rejects_GB_suffix_fr(self):
        self.assertEqual(self._run(["4GB", "4G"], lang="fr"), "4G")

    def test_rejects_0G(self):
        self.assertEqual(self._run(["0G", "4G"]), "4G")

    def test_accepts_lowercase_fr(self):
        self.assertEqual(self._run(["4g"], lang="fr"), "4g")

    def test_accepts_lowercase_en(self):
        self.assertEqual(self._run(["512m"], lang="en"), "512m")


class TestConfigSmartAskCpu(unittest.TestCase):
    """_smart_ask_cpu loops until a valid CPU affinity format is entered."""

    def _run(self, inputs, lang="fr"):
        _switch_lang(lang)
        import mc_config
        config = {}
        with patch("builtins.input", side_effect=inputs):
            return mc_config._smart_ask_cpu("CPU ?", "cpu_affinity", config, "0-7")

    def test_accepts_range_fr(self):
        self.assertEqual(self._run(["0-7"], lang="fr"), "0-7")

    def test_accepts_range_en(self):
        self.assertEqual(self._run(["8-15"], lang="en"), "8-15")

    def test_accepts_list_fr(self):
        self.assertEqual(self._run(["0,1,2,3"], lang="fr"), "0,1,2,3")

    def test_accepts_mixed_en(self):
        self.assertEqual(self._run(["0-3,8-11"], lang="en"), "0-3,8-11")

    def test_rejects_letters_then_accepts_fr(self):
        self.assertEqual(self._run(["abc", "0-7"], lang="fr"), "0-7")

    def test_rejects_letters_then_accepts_en(self):
        self.assertEqual(self._run(["bad", "0-7"], lang="en"), "0-7")

    def test_rejects_spaces_inside(self):
        self.assertEqual(self._run(["0 - 7", "0-7"]), "0-7")

    def test_accepts_single_core_fr(self):
        self.assertEqual(self._run(["0"], lang="fr"), "0")


class TestConfigSmartAskNonempty(unittest.TestCase):
    """_smart_ask_nonempty loops until a non-empty name is entered."""

    def _run(self, inputs, lang="fr", default="Minecraft"):
        _switch_lang(lang)
        import mc_config
        config = {}
        with patch("builtins.input", side_effect=inputs):
            return mc_config._smart_ask_nonempty("Nom ?", "nom_serveur", config, default)

    def test_accepts_valid_fr(self):
        self.assertEqual(self._run(["Serveur1"], lang="fr"), "Serveur1")

    def test_accepts_valid_en(self):
        self.assertEqual(self._run(["MyServer"], lang="en"), "MyServer")

    def test_accepts_default_on_enter_fr(self):
        # Pressing Enter with default "Minecraft" → accepts default
        self.assertEqual(self._run([""], lang="fr", default="Minecraft"), "Minecraft")

    def test_accepts_default_on_enter_en(self):
        self.assertEqual(self._run([""], lang="en", default="Minecraft"), "Minecraft")

    def test_rejects_empty_when_no_default_fr(self):
        # No default (empty string) → must type a real name
        self.assertEqual(self._run(["", "Serveur1"], lang="fr", default=""), "Serveur1")

    def test_rejects_empty_when_no_default_en(self):
        self.assertEqual(self._run(["", "MyServer"], lang="en", default=""), "MyServer")

    def test_rejects_whitespace_only_no_default(self):
        self.assertEqual(self._run(["   ", "Serveur1"], default=""), "Serveur1")


# ─── mc_config schedule helpers ──────────────────────────────────────────────

class TestConfigAskHour(unittest.TestCase):
    """_ask_hour loops until 0-23 is entered."""

    def _run(self, inputs, lang="fr"):
        _switch_lang(lang)
        import mc_config
        config = {}
        with patch("builtins.input", side_effect=inputs):
            return mc_config._ask_hour("prompt_open_hour", "open_hour", config, 8)

    def test_accepts_0_fr(self):
        self.assertEqual(self._run(["0"], lang="fr"), 0)

    def test_accepts_23_en(self):
        self.assertEqual(self._run(["23"], lang="en"), 23)

    def test_rejects_24_then_accepts_fr(self):
        self.assertEqual(self._run(["24", "8"], lang="fr"), 8)

    def test_rejects_24_then_accepts_en(self):
        self.assertEqual(self._run(["24", "8"], lang="en"), 8)

    def test_rejects_negative(self):
        self.assertEqual(self._run(["-1", "12"]), 12)

    def test_rejects_25(self):
        self.assertEqual(self._run(["25", "10"]), 10)


class TestConfigAskMinute(unittest.TestCase):
    """_ask_minute loops until 0-59 is entered."""

    def _run(self, inputs, lang="fr"):
        _switch_lang(lang)
        import mc_config
        config = {}
        with patch("builtins.input", side_effect=inputs):
            return mc_config._ask_minute("prompt_open_min", "open_min", config, 0)

    def test_accepts_0_fr(self):
        self.assertEqual(self._run(["0"], lang="fr"), 0)

    def test_accepts_59_en(self):
        self.assertEqual(self._run(["59"], lang="en"), 59)

    def test_rejects_60_then_accepts_fr(self):
        self.assertEqual(self._run(["60", "30"], lang="fr"), 30)

    def test_rejects_60_then_accepts_en(self):
        self.assertEqual(self._run(["60", "30"], lang="en"), 30)

    def test_rejects_70(self):
        self.assertEqual(self._run(["70", "0"]), 0)

    def test_rejects_negative(self):
        self.assertEqual(self._run(["-5", "30"]), 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
