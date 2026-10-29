import glob
import os
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
                     "invalid_name", "kick_offline", "player_not_online", "rcon_failed", "backup_not_found", "backup_failed", "stop_first", "confirm_required"):
            self.assertNotIn("(", i18n.error_text(code))

    def test_every_literal_key_used_by_the_sources_exists(self):
        package = os.path.join(os.path.dirname(__file__), "..", "mcmanager_app")
        missing = set()
        for path in glob.glob(os.path.join(package, "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            for key in re.findall(r"(?<![\w.])t\(\"([a-z_0-9-]+)\"[,)]", source):
                if key not in i18n.TEXTS["en"]:
                    missing.add(key)
        self.assertEqual(missing, set())

    def test_computed_keys_exist(self):
        from mcmanager_app import panels
        keys = ["mod_source_" + (source or "auto") for source in panels.MOD_SOURCES]
        keys += ["pack_placement_" + (item or "default") for item in panels.DATAPACK_PLACEMENTS]
        keys += ["task_action_" + action for action in panels.TASK_ACTIONS]
        keys += ["mode_" + mode for mode in panels.MODES]
        keys += ["secret_" + key for key in panels.SECRET_KEYS]
        keys += ["setting_" + key for key in panels.SETTING_KINDS]
        keys += ["settings_" + name for name, _fields in panels.SETTING_GROUPS]
        keys += ["sleep_join_" + mode for mode in panels.JOIN_MODES]
        keys += ["pack_problem_nested", "pack_problem_not_a_pack", "pack_enable_name", "pack_disable_name",
                 "task_enable_name", "task_disable_name", "dimension_overworld", "dimension_nether", "dimension_end"]
        self.assertEqual([key for key in keys if key not in i18n.TEXTS["en"]], [])

    def test_computed_keys_of_the_host_panels_exist(self):
        from mcmanager_app import host_panels
        keys = ["alert_type_" + kind for kind in host_panels.ALERT_TYPES]
        keys += ["alert_event_" + event for event in host_panels.ALERT_EVENTS + ("all",)]
        keys += ["alert_field_" + key for fields in host_panels.ALERT_FIELDS.values() for key, _kind in fields]
        keys += ["role_" + role for role in host_panels.ROLES]
        keys += ["notify_pref_" + kind for kind in host_panels.NOTIFY_KINDS]
        keys += ["notify_crash", "notify_crash_loop", "notify_backup_failed", "notify_join"]
        keys += ["tab_" + name for name in ("alerts", "java", "devices", "router", "update", "doctor", "notifications")]
        keys += ["update_current", "update_available", "router_allow", "router_deny"]
        self.assertEqual([key for key in keys if key not in i18n.TEXTS["en"]], [])

    def test_api_error_codes_of_the_host_panels_are_translated(self):
        for code in ("bad_type", "bad_events", "bad_channel_name", "missing_host", "missing_addresses", "bad_port",
                     "missing_telegram", "missing_topic", "bad_url", "channel_exists", "channel_not_found",
                     "no_channel", "alert_test_failed", "router_port_conflict", "router_usage", "tls_unavailable",
                     "device_not_found", "device_revoked", "pair_locked", "no_previous", "bad_signature", "not_listed",
                     "bad_checksum", "unsigned", "no_asset", "unknown_pack", "pack_no_server_files", "port_taken",
                     "no_modpack", "pack_not_updatable", "source_required", "java_unavailable",
                     "java_download_failed", "java_unknown_version", "source_unreachable", "check_failed"):
            self.assertNotIn("(", i18n.error_text(code), code)

    def test_api_error_codes_of_the_tabs_are_translated(self):
        for code in ("forbidden", "mod_not_found", "mod_exists", "mod_ambiguous", "defines_blocks", "pack_not_found",
                     "pack_nested", "pack_not_a_pack", "pack_broken_worldgen", "task_not_found", "task_name_taken",
                     "invalid_cron", "invalid_warn", "command_required", "warn_not_allowed", "chunky_missing",
                     "pregen_offline", "invalid_radius", "invalid_center", "overworld_protected", "unknown_dimension",
                     "confirmation_required", "sleep_after_too_short", "sleep_needs_rcon", "unsupported_on_windows", "invalid_value", "key_not_found", "config_conflict", "java_bad_choice",
                     "invalid_time", "name_required", "unknown_loader", "eula_required", "folder_not_empty",
                     "job_failed", "server_offline", "stop_first", "server_running"):
            self.assertNotIn("(", i18n.error_text(code), code)

    def test_unknown_code_falls_back_on_the_api_message(self):
        self.assertEqual(i18n.error_text("brand_new", "Readable text"), "Readable text")
        self.assertIn("brand_new", i18n.error_text("brand_new"))


if __name__ == "__main__":
    unittest.main()
