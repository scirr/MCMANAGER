import unittest

from tests.support import api_environment, local_client, start_api

from mcmanager_app.client import ApiClient, ApiError


class RecordingTransport:
    def __init__(self):
        self.requests = []

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        return 200, {"ok": True}


class TestRequests(unittest.TestCase):
    def setUp(self):
        self.transport = RecordingTransport()
        self.client = ApiClient(self.transport)

    def last(self):
        return self.transport.requests[-1]

    def test_mods(self):
        self.client.add_mod("a b", "sodium", "modrinth", True)
        self.assertEqual(self.last(), ("POST", "/v1/servers/a%20b/mods",
                                       {"ref": "sodium", "source": "modrinth", "server_only": True}))
        self.client.add_mod("a", "x.jar")
        self.assertEqual(self.last()[2], {"ref": "x.jar"})
        self.client.remove_mod("a", "x y.jar", True)
        self.assertEqual(self.last(), ("DELETE", "/v1/servers/a/mods/x%20y.jar?confirm_blocks=true", None))
        self.client.remove_mod("a", "x.jar")
        self.assertEqual(self.last()[1], "/v1/servers/a/mods/x.jar")
        self.client.update_mods("a")
        self.assertEqual(self.last(), ("POST", "/v1/servers/a/mods/update", {"name": None}))

    def test_datapacks_send_placement_only_when_enabling(self):
        self.client.set_datapack("a", "p.zip", True, "first")
        self.assertEqual(self.last(), ("PUT", "/v1/servers/a/datapacks/p.zip", {"enabled": True, "first": True}))
        self.client.set_datapack("a", "p.zip", False, "first")
        self.assertEqual(self.last()[2], {"enabled": False})

    def test_world(self):
        self.client.start_pregen("a", 3000, "0,0")
        self.assertEqual(self.last(), ("POST", "/v1/servers/a/worlds/pregen", {"radius": 3000, "center": "0,0"}))
        self.client.reset_dimension("a", "nether")
        self.assertEqual(self.last(), ("POST", "/v1/servers/a/worlds/nether/reset",
                                       {"confirmed": True, "include_overworld": False}))

    def test_tasks(self):
        self.client.create_task("a", "restart", "0 4 * * *", "n", None, "5m,1m")
        self.assertEqual(self.last(), ("POST", "/v1/servers/a/tasks",
                                       {"action": "restart", "cron": "0 4 * * *", "name": "n", "warn": "5m,1m"}))
        self.client.update_task("a", 3, False)
        self.assertEqual(self.last(), ("PATCH", "/v1/servers/a/tasks/3", {"enabled": False}))
        self.client.run_task("a", 3, True)
        self.assertEqual(self.last(), ("POST", "/v1/servers/a/tasks/3/run", {"skip_warn": True}))
        self.client.delete_task("a", 3)
        self.assertEqual(self.last()[:2], ("DELETE", "/v1/servers/a/tasks/3"))

    def test_settings_and_creation(self):
        self.client.set_config_value("a", "port", 25570)
        self.assertEqual(self.last(), ("PUT", "/v1/servers/a/config/port", {"value": 25570}))
        self.client.set_mode("a", "always-on")
        self.assertEqual(self.last(), ("PUT", "/v1/servers/a/mode", {"mode": "always-on"}))
        self.client.set_schedule("a", 20, 0, 3, 30)
        self.assertEqual(self.last()[2], {"open_hour": 20, "open_minute": 0, "close_hour": 3, "close_minute": 30})
        self.client.set_server_java("a", 21)
        self.assertEqual(self.last(), ("PUT", "/v1/servers/a/java", {"choice": "21"}))
        self.client.create_server("s", "Paper", True, "1.21.1", "4G", None, None)
        self.assertEqual(self.last(), ("POST", "/v1/servers", {"name": "s", "loader": "Paper", "accept_eula": True,
                                                                "version": "1.21.1", "ram": "4G"}))


class TestAgainstLocalApi(unittest.TestCase):
    def setUp(self):
        manager = api_environment()
        self.env = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.api = start_api(self.env)
        self.addCleanup(self.api.stop)
        self.client = local_client(self.env)

    def code(self, function, *args):
        with self.assertRaises(ApiError) as caught:
            function(*args)
        return caught.exception.code

    def test_empty_listings(self):
        self.assertEqual(self.client.list_mods("a")["mods"], [])
        self.assertEqual(self.client.list_datapacks("a")["packs"], [])
        self.assertEqual(self.client.list_worlds("a")["dimensions"], [])

    def test_task_round_trip(self):
        created = self.client.create_task("a", "backup", "0 3 * * *", "nightly")["task"]
        self.assertEqual(self.client.list_tasks("a")["tasks"][0]["name"], "nightly")
        self.assertFalse(self.client.update_task("a", created["id"], False)["task"]["enabled"])
        self.client.delete_task("a", created["id"])
        self.assertEqual(self.client.list_tasks("a")["tasks"], [])

    def test_task_errors_are_typed(self):
        self.assertEqual(self.code(self.client.create_task, "a", "backup", "nonsense"), "invalid_cron")
        self.assertEqual(self.code(self.client.delete_task, "a", 99), "task_not_found")

    def test_config_mode_and_schedule(self):
        self.assertEqual(self.client.set_config_value("a", "nom_serveur", "Zed")["key"], "nom_serveur")
        self.assertEqual(self.client.config("a")["config"]["nom_serveur"], "Zed")
        self.assertEqual(self.code(self.client.set_config_value, "a", "port", "abc"), "invalid_value")
        self.assertEqual(self.client.set_mode("a", "maintenance")["mode"], "maintenance")
        self.assertEqual(self.client.set_schedule("a", 20, 0, 3, 0)["open"], "20:00")

    def test_content_errors_are_typed(self):
        self.assertEqual(self.code(self.client.remove_mod, "a", "zz"), "mod_not_found")
        self.assertEqual(self.code(self.client.set_datapack, "a", "zz.zip", False), "pack_not_found")
        self.assertEqual(self.code(self.client.reset_dimension, "a", "nether"), "unknown_dimension")
        self.assertEqual(self.code(self.client.create_server, "s2", "Paper", False), "eula_required")

    def test_java_listing(self):
        self.assertEqual(self.client.server_java("a")["servers"][0]["server"], "a")


if __name__ == "__main__":
    unittest.main()
