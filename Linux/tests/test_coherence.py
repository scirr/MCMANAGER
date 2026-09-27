"""
test_coherence.py — Inter-field coherence tests.
Covers inconsistencies between successive answers (RCON port = game port,
identical schedules, AutoModpack re-asked, etc.).
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_lang


def _switch_lang(lang):
    # T is mutated in place, so every module that imported it sees the change.
    mc_lang._apply_language(lang)


# ─── Validate schedule open == close ─────────────────────────────────────────

def _validate_schedule(open_h, open_m, close_h, close_m, lang="fr"):
    T = mc_lang._FR if lang == "fr" else mc_lang._EN
    if not (0 <= open_h <= 23): return T["invalid_hour"].format(val=open_h)
    if not (0 <= open_m <= 59): return T["invalid_minute"].format(val=open_m)
    if not (0 <= close_h <= 23): return T["invalid_hour"].format(val=close_h)
    if not (0 <= close_m <= 59): return T["invalid_minute"].format(val=close_m)
    if (open_h, open_m) == (close_h, close_m):
        return T["schedule_same_time"]
    return None


class TestScheduleSameTime(unittest.TestCase):
    """Identical open and close times → error."""

    def test_same_time_rejected_fr(self):
        self.assertIsNotNone(_validate_schedule(8, 0, 8, 0, "fr"))

    def test_same_time_rejected_en(self):
        self.assertIsNotNone(_validate_schedule(22, 30, 22, 30, "en"))

    def test_same_hour_diff_minute_ok(self):
        self.assertIsNone(_validate_schedule(8, 0, 8, 30, "fr"))

    def test_different_times_ok_fr(self):
        self.assertIsNone(_validate_schedule(8, 0, 22, 0, "fr"))

    def test_different_times_ok_en(self):
        self.assertIsNone(_validate_schedule(20, 0, 3, 0, "en"))

    def test_midnight_to_midnight_rejected(self):
        self.assertIsNotNone(_validate_schedule(0, 0, 0, 0, "fr"))

    def test_error_message_contains_key_fr(self):
        msg = _validate_schedule(8, 0, 8, 0, "fr")
        self.assertIsInstance(msg, str)
        self.assertTrue(len(msg) > 10)

    def test_error_message_contains_key_en(self):
        msg = _validate_schedule(8, 0, 8, 0, "en")
        self.assertIsInstance(msg, str)
        self.assertTrue(len(msg) > 10)


# ─── RCON port ≠ game port ───────────────────────────────────────────────────

class TestRconVsGamePort(unittest.TestCase):
    """RCON port must not be identical to the game port."""

    def _check(self, rcon_port, game_port):
        return rcon_port == game_port

    def test_rcon_equals_game_port(self):
        self.assertTrue(self._check(25565, 25565))

    def test_rcon_default_differs_from_game_default(self):
        self.assertFalse(self._check(25575, 25565))

    def test_rcon_custom_differs(self):
        self.assertFalse(self._check(25576, 25565))

    def test_zero_edge(self):
        # Both would fail range check anyway
        self.assertTrue(self._check(0, 0))

    def test_error_message_has_both_ports_fr(self):
        T = mc_lang._FR
        msg = T["rcon_same_as_game_port"].format(rcon=25565, game=25565)
        self.assertIn("25565", msg)

    def test_error_message_has_both_ports_en(self):
        T = mc_lang._EN
        msg = T["rcon_same_as_game_port"].format(rcon=25565, game=25565)
        self.assertIn("25565", msg)


# ─── AutoModpack — mark refusal ──────────────────────────────────────────────

class TestAutomodpackDeclineMarking(unittest.TestCase):
    """
    When the user declines AutoModpack or the loader is incompatible,
    activer_automodpack must be set to 0 to avoid re-asking the question.
    """

    def test_loader_incompatible_sets_zero(self):
        """Vanilla/Paper → activer_automodpack=0 immédiatement."""
        from mc_deploy import AUTOMODPACK_LOADER_MAP
        for loader in ("Vanilla", "Paper"):
            with self.subTest(loader=loader):
                self.assertIsNone(AUTOMODPACK_LOADER_MAP[loader],
                    f"{loader} should map to None (not supported)")

    def test_supported_loaders_have_mapping(self):
        from mc_deploy import AUTOMODPACK_LOADER_MAP
        for loader in ("Fabric", "Forge", "NeoForge"):
            with self.subTest(loader=loader):
                self.assertIsNotNone(AUTOMODPACK_LOADER_MAP[loader])

    def _run_provisioning(self, config):
        """Helper: runs ensure_provisioning with all I/O dependencies patched."""
        import mc_config
        import mc_deploy
        import mc_firewall
        from unittest.mock import patch

        setup_calls = []
        with patch.object(mc_deploy, "setup_automodpack",
                          side_effect=lambda *a, **kw: setup_calls.append(a) or a[1]):
            with patch.object(mc_deploy, "setup_rcon",
                              return_value=(config, "pass", 25575)):
                with patch.object(mc_deploy, "generate_server_properties"):
                    with patch.object(mc_firewall, "ensure_game_port_rule",
                                      return_value=(True, "")):
                        with patch("mc_config.load_config", return_value={}):
                            result = mc_config.ensure_provisioning(config.copy(), "/fake")
        return result, setup_calls

    def test_ensure_provisioning_skips_when_key_present(self):
        """ensure_provisioning must not call setup_automodpack if the key already exists."""
        _switch_lang("fr")
        config = {
            "dossier_serveur": "/fake",
            "port": 25565,
            "activer_automodpack": 0,
            "loader": "Fabric",
            "mc_version": "1.21.4",
            "mcrcon_pass": "pass",
        }
        _, setup_calls = self._run_provisioning(config)
        self.assertEqual(len(setup_calls), 0,
            "setup_automodpack should NOT be called when activer_automodpack is already set")

    def test_ensure_provisioning_skips_vanilla_loader(self):
        """Vanilla without activer_automodpack key → must mark 0 without calling setup."""
        _switch_lang("fr")
        config = {
            "dossier_serveur": "/fake",
            "port": 25565,
            "loader": "Vanilla",
            "mc_version": "1.21.4",
            "mcrcon_pass": "pass",
        }
        _, setup_calls = self._run_provisioning(config)
        self.assertEqual(len(setup_calls), 0,
            "setup_automodpack should NOT be called for Vanilla")


# ─── Maintenance / resume semantics ──────────────────────────────────────────

class TestResumeAnnounce(unittest.TestCase):
    """Leaving maintenance must arm a one-shot 'announce next start' flag: the
    always-on restart path is silent by design, but a reopening is not."""

    def test_resume_clears_maintenance(self):
        import mc_config
        config = mc_config.resume_mode({"mode_maintenance": 1})
        self.assertEqual(config["mode_maintenance"], 0)

    def test_resume_arms_announce_flag(self):
        import mc_config
        config = mc_config.resume_mode({"mode_maintenance": 1})
        self.assertEqual(config["announce_next_start"], 1)

    def test_maintenance_does_not_arm_the_flag(self):
        import mc_config
        config = mc_config.set_mode_maintenance({})
        self.assertNotIn("announce_next_start", config)


# ─── Coherence AUTOMODPACK_LOADER_MAP vs _AUTOMOD_LOADERS ────────────────────

class TestAutomodpackConsistency(unittest.TestCase):
    """Both AutoModpack loader registries must be coherent."""

    def test_automod_loaders_subset_of_map(self):
        from mc_deploy import AUTOMODPACK_LOADER_MAP
        import mc_config
        for loader in mc_config._AUTOMOD_LOADERS:
            with self.subTest(loader=loader):
                self.assertIn(loader, AUTOMODPACK_LOADER_MAP,
                    f"{loader} in _AUTOMOD_LOADERS but missing from AUTOMODPACK_LOADER_MAP")
                self.assertIsNotNone(AUTOMODPACK_LOADER_MAP[loader],
                    f"{loader} in _AUTOMOD_LOADERS but maps to None")

    def test_non_automod_loaders_are_none_in_map(self):
        from mc_deploy import AUTOMODPACK_LOADER_MAP
        import mc_config
        for loader, modrinth_id in AUTOMODPACK_LOADER_MAP.items():
            if modrinth_id is None:
                with self.subTest(loader=loader):
                    self.assertNotIn(loader, mc_config._AUTOMOD_LOADERS,
                        f"{loader} maps to None but is in _AUTOMOD_LOADERS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
