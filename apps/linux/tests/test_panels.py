import unittest

from tests.support import FakeClient, sync_runner

from mcmanager_app import i18n
from mcmanager_app.panels import (CreateServerModel, DatapacksModel, ModsModel, SettingsModel, TasksModel,
                                  WorldModel, format_duration, parse_time)


class PanelCase(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.client = FakeClient()
        self.runner = sync_runner()


class TestHelpers(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual([format_duration(v) for v in (300, 60, 3600, 90)], ["5m", "1m", "1h", "90s"])

    def test_parse_time(self):
        self.assertEqual(parse_time("20:05"), (20, 5))
        self.assertEqual(parse_time(" 7:00 "), (7, 0))
        for bad in ("24:00", "12:60", "noon", "", None):
            self.assertIsNone(parse_time(bad))


class TestMods(PanelCase):
    def setUp(self):
        super().setUp()
        self.client.mods = [
            {"file": "lithium-0.13.jar", "id": "lithium", "name": "Lithium", "version": "0.13", "loader": "fabric",
             "source": "modrinth", "server": True, "modpack": False, "adds_blocks": False},
            {"file": "custom.jar", "id": None, "name": None, "version": None, "loader": None, "server": True,
             "modpack": True, "adds_blocks": True},
        ]
        self.model = ModsModel(self.client, "a", self.runner)
        self.model.load()

    def test_rows(self):
        first, second = self.model.mods
        self.assertEqual((first["name"], first["source_text"]), ("Lithium", "modrinth"))
        self.assertEqual((second["name"], second["source_text"], second["adds_blocks"]), ("custom.jar", "local file", True))

    def test_add_follows_the_job_and_reloads(self):
        self.assertTrue(self.model.add("  sodium ", "modrinth", False))
        self.assertEqual(self.client.calls[:2], [("add_mod", "sodium", "modrinth", False), ("wait", "j_add_mod")])
        self.assertEqual(self.model.message, "sodium installed")
        self.assertEqual(self.model.progress, 40)
        self.assertIsNone(self.model.busy)

    def test_add_refuses_blank_reference_and_unknown_source(self):
        self.assertFalse(self.model.add("  "))
        self.assertFalse(self.model.add("x", "elsewhere"))
        self.assertEqual(self.client.calls, [])

    def test_restart_hint_is_appended(self):
        self.client.result = {"restart_required": True}
        self.model.update()
        self.assertEqual(self.model.message, "Mods updated Restart the server to apply.")
        self.assertEqual(self.client.calls[0], ("update_mods", None))

    def test_update_one(self):
        self.model.update("lithium-0.13.jar")
        self.assertEqual(self.client.calls[0], ("update_mods", "lithium-0.13.jar"))

    def test_remove_needs_confirmation(self):
        self.assertFalse(self.model.remove("custom.jar"))
        self.assertEqual(self.client.calls, [])
        self.assertTrue(self.model.remove("custom.jar", confirmed=True))
        self.assertEqual(self.client.calls[0], ("remove_mod", "custom.jar", False))
        self.assertEqual(self.model.message, "custom.jar moved to quarantine")

    def test_blocks_need_a_second_confirmation(self):
        self.client.fail["remove_mod"] = "defines_blocks"
        self.model.remove("custom.jar", confirmed=True)
        self.assertEqual(self.model.blocks_pending, "custom.jar")
        self.assertEqual(self.model.error, "This mod adds blocks to the world")
        del self.client.fail["remove_mod"]
        self.model.remove("custom.jar", confirmed=True, confirm_blocks=True)
        self.assertIsNone(self.model.blocks_pending)
        self.assertEqual(self.client.calls[-1], ("remove_mod", "custom.jar", True))

    def test_forbidden_makes_the_tab_read_only(self):
        self.client.fail["add_mod"] = "forbidden"
        self.model.add("x")
        self.assertTrue(self.model.read_only)
        self.assertEqual(self.model.error, "Your role does not allow this action")

    def test_job_failure_is_translated(self):
        i18n.set_language("fr")
        self.client.fail["wait"] = "mod_not_found"
        self.model.add("zzz")
        self.assertEqual(self.model.error, "Mod introuvable")
        self.assertIsNone(self.model.busy)

    def test_busy_blocks_a_second_operation(self):
        self.model.busy = "add"
        self.assertFalse(self.model.update())


class TestDatapacks(PanelCase):
    def setUp(self):
        super().setUp()
        self.client.packs = [
            {"id": "file/a.zip", "file": "a.zip", "enabled": True, "order": 1, "worldgen": True, "problem": None},
            {"id": "file/b.zip", "file": "b.zip", "enabled": False, "order": None, "worldgen": False, "problem": None},
            {"id": "file/c", "file": "c", "enabled": False, "order": None, "worldgen": False, "problem": "nested"},
        ]
        self.model = DatapacksModel(self.client, "a", self.runner)
        self.model.load()

    def test_rows_and_states(self):
        self.assertEqual([p["state_text"] for p in self.model.packs],
                         ["Enabled", "Disabled", "Folder nested one level too deep"])

    def test_stopped_server_state_is_unknown(self):
        self.client.running = False
        self.client.packs[0]["enabled"] = None
        self.model.load()
        self.assertFalse(self.model.running)
        self.assertEqual(self.model.packs[0]["state_text"], "State unknown, the server is stopped")

    def test_toggle_rules(self):
        enabled, disabled, broken = self.model.packs
        self.assertTrue(self.model.can_toggle(disabled, True))
        self.assertFalse(self.model.can_toggle(broken, True))
        self.client.running = False
        self.model.load()
        self.assertFalse(self.model.can_toggle(disabled, True))
        self.assertTrue(self.model.can_toggle(disabled, False))

    def test_enable_with_placement_and_disable(self):
        self.assertTrue(self.model.toggle("b.zip", True, "first"))
        self.assertEqual(self.client.calls[-1], ("set_datapack", "b.zip", True, "first"))
        self.assertEqual(self.model.message, "b.zip enabled")
        self.model.toggle("a.zip", False)
        self.assertEqual(self.client.calls[-1], ("set_datapack", "a.zip", False, None))
        self.assertEqual(self.model.message, "a.zip disabled")

    def test_unknown_placement_is_refused(self):
        self.assertFalse(self.model.toggle("b.zip", True, "middle"))

    def test_world_generation_pack_asks_for_a_restart(self):
        self.client.result = {"restart_required": True}
        self.model.toggle("a.zip", False)
        self.assertIn("Restart the server", self.model.message)

    def test_server_offline_error(self):
        self.client.fail["set_datapack"] = "server_offline"
        self.model.toggle("b.zip", True)
        self.assertEqual(self.model.error, "The server is not running")


class TestWorld(PanelCase):
    def setUp(self):
        super().setUp()
        self.client.dimensions = [{"id": "overworld", "paths": ["/w"], "size_bytes": 1610612736},
                                  {"id": "nether", "paths": ["/w/DIM-1"], "size_bytes": 536870912}]
        self.client.pregen = {"progress": "Task running (11.2%)"}
        self.model = WorldModel(self.client, "a", self.runner)
        self.model.load()

    def test_load_dimensions_and_progress(self):
        self.assertEqual([(d["id"], d["size_text"]) for d in self.model.dimensions],
                         [("overworld", "1.5 GB"), ("nether", "512.0 MB")])
        self.assertEqual(self.model.total_text, "2.0 GB")
        self.assertEqual(self.model.pregen_text, "Task running (11.2%)")

    def test_pregen_unavailable_is_a_note_not_an_error(self):
        self.client.fail["pregen_status"] = "chunky_missing"
        self.model.load()
        self.assertEqual((self.model.pregen_text, self.model.pregen_note), ("", "The Chunky mod is not installed"))
        self.assertIsNone(self.model.error)

    def test_start_pregen_validates_locally(self):
        for radius, center in (("", ""), ("0", ""), ("abc", ""), ("100", "12"), ("100", "a,b")):
            self.assertFalse(self.model.start_pregen(radius, center))
        self.assertEqual(self.model.error, "Invalid centre, use x,z")
        self.assertEqual(self.client.calls, [])

    def test_start_pregen(self):
        self.client.result = {"progress": "Task running."}
        self.assertTrue(self.model.start_pregen("3000", " -10,20 "))
        self.assertEqual(self.client.calls[-1], ("start_pregen", 3000, "-10,20"))
        self.assertEqual((self.model.message, self.model.pregen_text), ("Pre-generation started", "Task running."))

    def test_reset_needs_confirmation_and_is_a_job(self):
        self.assertFalse(self.model.reset("nether"))
        self.assertEqual(self.client.calls, [])
        self.assertTrue(self.model.reset("nether", confirmed=True))
        self.assertEqual(self.client.calls[0], ("reset_dimension", "nether", False))
        self.assertEqual(self.model.message, "nether reset")
        self.assertEqual(self.model.progress, 40)

    def test_overworld_reset_sets_the_explicit_flag(self):
        self.model.reset("overworld", confirmed=True)
        self.assertEqual(self.client.calls[0], ("reset_dimension", "overworld", True))

    def test_reset_error_is_translated(self):
        i18n.set_language("fr")
        self.client.fail["reset_dimension"] = "server_running"
        self.model.reset("nether", confirmed=True)
        self.assertEqual(self.model.error, "Le serveur tourne déjà")


class TestTasks(PanelCase):
    def setUp(self):
        super().setUp()
        self.client.tasks = [{"id": 1, "name": "nightly", "cron": "0 4 * * *", "action": "restart", "enabled": True,
                              "warn": [300, 60], "next_run": "2026-10-09T04:00:00",
                              "last_result": {"ok": False, "code": "task_error"}},
                             {"id": 2, "name": "cmd", "cron": "*/5 * * * *", "action": "command", "command": "list",
                              "enabled": False, "warn": [], "next_run": None, "last_result": None}]
        self.model = TasksModel(self.client, "a", self.runner)
        self.model.load()

    def test_rows(self):
        first, second = self.model.tasks
        self.assertEqual((first["warn_text"], first["next_text"], first["action_text"]),
                         ("5m, 1m", "2026-10-09 04:00:00", "Restart"))
        self.assertEqual(first["last_text"], "last run failed (task_error)")
        self.assertEqual((second["last_text"], second["next_text"], second["command"]), ("", "", "list"))

    def test_create_validates_cron_and_command(self):
        self.assertFalse(self.model.create("restart", "0 4 * *"))
        self.assertEqual(self.model.error, "Invalid schedule, use 5 cron fields")
        self.assertFalse(self.model.create("command", "0 4 * * *"))
        self.assertEqual(self.model.error, "A command is required")
        self.assertFalse(self.model.create("explode", "0 4 * * *"))
        self.assertEqual(self.client.calls, [])

    def test_create_drops_fields_the_action_does_not_take(self):
        self.assertTrue(self.model.create("backup", " 0 3 * * * ", "b", "say hi", "5m"))
        self.assertEqual(self.client.calls[0], ("create_task", "backup", "0 3 * * *", "b", "", ""))
        self.assertEqual(self.model.message, "Task created")
        self.model.create("restart", "0 3 * * *", "", "say hi", "5m,1m")
        self.assertEqual(self.client.calls[-1], ("create_task", "restart", "0 3 * * *", "", "", "5m,1m"))

    def test_create_command(self):
        self.model.create("command", "0 3 * * *", "", " say hi ", "")
        self.assertEqual(self.client.calls[0][1:], ("command", "0 3 * * *", "", "say hi", ""))

    def test_name_taken(self):
        i18n.set_language("fr")
        self.client.fail["create_task"] = "task_name_taken"
        self.model.create("backup", "0 3 * * *", "dup")
        self.assertEqual(self.model.error, "Une tâche porte déjà ce nom")

    def test_enable_disable_run_delete(self):
        self.model.set_enabled(2, True)
        self.assertEqual(self.client.calls[0], ("update_task", 2, True))
        self.assertEqual(self.model.message, "Task enabled")
        self.model.set_enabled(2, False)
        self.assertEqual(self.model.message, "Task disabled")
        self.model.run(1, True)
        self.assertEqual(self.client.calls[-2:], [("run_task", 1, True), ("wait", "j_run_task")])
        self.assertEqual(self.model.message, "Task finished")

    def test_delete_needs_confirmation(self):
        self.assertFalse(self.model.delete(1))
        self.assertEqual(self.client.calls, [])
        self.assertTrue(self.model.delete(1, confirmed=True))
        self.assertEqual(self.client.calls[0], ("delete_task", 1))
        self.assertEqual(self.model.message, "Task deleted")

    def test_viewer_role_hides_actions(self):
        self.client.fail["update_task"] = "forbidden"
        self.model.set_enabled(1, False)
        self.assertTrue(self.model.read_only)


class TestSettings(PanelCase):
    def setUp(self):
        super().setUp()
        self.client.config_doc = {
            "config": {"port": 25565, "ram_allocation": "6G", "nom_serveur": "Survie", "always_on": 0,
                       "mode_maintenance": 0, "heure_ouverture": 20, "minute_ouverture": 0, "heure_fermeture": 3,
                       "minute_fermeture": 30, "java_major": 21},
            "secrets_set": ["mcrcon_pass", "alerts"]}
        self.client.java_doc = {"runtimes": {"17": "/j17", "21": "/j21"},
                                "servers": [{"server": "b", "java": "system"}, {"server": "a", "java": 17}]}
        self.model = SettingsModel(self.client, "a", self.runner)
        self.model.load()

    def test_load(self):
        self.assertEqual(self.model.values["port"], "25565")
        self.assertEqual(self.model.values["domaine"], "")
        self.assertEqual((self.model.mode, self.model.open_time, self.model.close_time),
                         ("schedule", "20:00", "03:30"))
        self.assertEqual((self.model.java, self.model.java_choices), ("17", ["system", "17", "21"]))

    def test_secret_values_are_never_kept(self):
        self.assertEqual(self.model.secrets_set, ["mcrcon_pass"])
        self.assertNotIn("mcrcon_pass", self.model.values)

    def test_mode_is_derived_from_the_flags(self):
        self.client.config_doc["config"]["always_on"] = 1
        self.model.load()
        self.assertEqual(self.model.mode, "always-on")
        self.client.config_doc["config"]["mode_maintenance"] = 1
        self.model.load()
        self.assertEqual(self.model.mode, "maintenance")

    def test_set_value_converts_integers_and_reloads(self):
        self.assertTrue(self.model.set_value("port", "25570"))
        self.assertEqual(self.client.calls[0], ("set_config", "port", 25570))
        self.assertEqual(self.model.message, "Setting saved")

    def test_set_value_rejects_bad_input_and_no_change(self):
        self.assertFalse(self.model.set_value("port", "abc"))
        self.assertEqual(self.model.error, "Invalid value")
        self.assertFalse(self.model.set_value("ram_allocation", "lots"))
        self.assertFalse(self.model.set_value("port", "25565"))
        self.assertFalse(self.model.set_value("mcrcon_pass", "x"))
        self.assertFalse(self.model.set_value("unknown", "x"))
        self.assertEqual(self.client.calls, [])

    def test_ram_accepts_megabytes_and_gigabytes(self):
        self.assertTrue(self.model.set_value("ram_allocation", "8G"))
        self.assertTrue(self.model.set_value("ram_allocation", "512M"))

    def test_empty_secret_leaves_it_unchanged(self):
        self.assertFalse(self.model.set_secret("mcrcon_pass", ""))
        self.assertFalse(self.model.set_secret("port", "x"))
        self.assertEqual(self.client.calls, [])
        self.assertTrue(self.model.set_secret("webhook_url", "https://example.invalid/h"))
        self.assertEqual(self.client.calls[0], ("set_config", "webhook_url", "https://example.invalid/h"))

    def test_restart_hint(self):
        self.client.result = {"restart_required": True}
        self.model.set_value("ram_allocation", "8G")
        self.assertEqual(self.model.message, "Setting saved Restart the server to apply.")

    def test_mode(self):
        self.assertFalse(self.model.set_mode("schedule"))
        self.assertFalse(self.model.set_mode("weird"))
        self.assertTrue(self.model.set_mode("maintenance"))
        self.assertEqual(self.client.calls[0], ("set_mode", "maintenance"))

    def test_schedule(self):
        self.assertFalse(self.model.set_schedule("25:00", "03:00"))
        self.assertEqual(self.model.error, "Invalid time, use HH:MM")
        self.assertTrue(self.model.set_schedule("18:30", "2:05"))
        self.assertEqual(self.client.calls[0], ("set_schedule", 18, 30, 2, 5))

    def test_java(self):
        self.assertFalse(self.model.set_java("17"))
        self.assertFalse(self.model.set_java("99"))
        self.assertTrue(self.model.set_java("21"))
        self.assertEqual(self.client.calls[0], ("set_java", "21"))

    def test_server_error_without_translation_shows_the_api_message(self):
        from mcmanager_app.client import ApiError
        self.client._check = lambda name: (_ for _ in ()).throw(ApiError("brand_new", "Readable text")) if name == "set_config" else None
        self.model.set_value("port", "1")
        self.assertEqual(self.model.error, "Readable text")


class TestCreateServer(PanelCase):
    def setUp(self):
        super().setUp()
        self.model = CreateServerModel(self.client, self.runner)

    def test_form_validation(self):
        self.assertFalse(self.model.create(" ", "Paper", eula=True))
        self.assertEqual(self.model.error, "A name is required")
        self.assertFalse(self.model.create("s", "Nope", eula=True))
        self.assertFalse(self.model.create("s", "Paper", eula=False))
        self.assertEqual(self.model.error, "Accept the Minecraft EULA first")
        self.assertFalse(self.model.create("s", "Paper", ram="lots", eula=True))
        self.assertFalse(self.model.create("s", "Paper", eula=True, port="70000"))
        self.assertFalse(self.model.create("s", "Paper", eula=True, rcon_port="x"))
        self.assertEqual(self.client.calls, [])

    def test_create_follows_the_job_and_reports_the_name(self):
        seen = []
        self.model.subscribe(lambda: seen.append(self.model.created))
        self.assertTrue(self.model.create(" survie ", "Paper", "1.21.1", "4g", True, "25570", ""))
        self.assertEqual(self.client.calls[:2], [("create_server", "survie", "Paper", "1.21.1", "4G", 25570, None),
                                                 ("wait", "j_create_server")])
        self.assertEqual(self.model.created, "survie")
        self.assertEqual(self.model.message, "Server survie created")
        self.assertEqual(seen[-1], "survie")

    def test_failure_keeps_the_dialog_open(self):
        i18n.set_language("fr")
        self.client.fail["wait"] = "folder_not_empty"
        self.model.create("s", "Paper", eula=True)
        self.assertIsNone(self.model.created)
        self.assertEqual(self.model.error, "Le dossier existe déjà et n'est pas vide")
        self.assertIsNone(self.model.busy)

    def test_defaults_send_only_what_is_needed(self):
        self.model.create("s", "Vanilla", eula=True)
        self.assertEqual(self.client.calls[0], ("create_server", "s", "Vanilla", None, None, None, None))


if __name__ == "__main__":
    unittest.main()
