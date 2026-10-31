import unittest

from tests.support import FakeClient, sync_runner

from mcmanager_app import i18n
from mcmanager_app.client import ApiError
from mcmanager_app.host_panels import (AlertsModel, DevicesModel, DoctorModel, JavaModel, NotificationPrefs,
                                       NotificationsModel, RouterModel, UpdateModel, notification_for)
from mcmanager_app.panels import CreateServerModel, ModsModel


class HostCase(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.client = FakeClient()
        self.runner = sync_runner()


class TestAlerts(HostCase):
    def setUp(self):
        super().setUp()
        self.client.channels = [
            {"name": "ntfy", "type": "ntfy", "events": ["crash", "backup_failed"], "topic": "mc"},
            {"name": "discord", "type": "discord", "events": ["*"], "legacy": True},
        ]
        self.model = AlertsModel(self.client, "a", self.runner)
        self.model.load()

    def test_rows(self):
        first, legacy = self.model.channels
        self.assertEqual((first["type_text"], first["target"], first["events_text"]), ("ntfy", "mc", "Crash, Backup failed"))
        self.assertTrue(legacy["legacy"])
        self.assertEqual(legacy["events_text"], "all events")

    def test_add_sends_only_the_fields_of_the_type(self):
        self.assertTrue(self.model.add("email", {"host": "smtp.x", "port": "2525", "password": "pw", "sender": "a@x",
                                                 "to": "b@x", "token": "ignored"}, ["crash"], " mine "))
        call = self.client.calls[0]
        self.assertEqual(call[:4], ("add_alert", "email", "crash", "mine"))
        self.assertEqual(call[4]["port"], 2525)
        self.assertNotIn("token", call[4])

    def test_add_refuses_unknown_type_and_bad_port(self):
        self.assertFalse(self.model.add("fax", {}))
        self.assertFalse(self.model.add("email", {"port": "99999"}))
        self.assertEqual(self.model.error, "Invalid port")
        self.assertEqual(self.client.calls, [])

    def test_remove_needs_confirmation(self):
        self.assertFalse(self.model.remove("ntfy"))
        self.assertTrue(self.model.remove("ntfy", True))
        self.assertEqual(self.client.calls[0], ("remove_alert", "ntfy"))
        self.assertEqual(self.model.message, "Channel ntfy removed")

    def test_failed_test_names_the_channels(self):
        def failing(name, channel=None):
            raise ApiError("alert_test_failed", "", 200, {"failed": "ntfy"})
        self.client.send_alert_test = failing
        self.model.test()
        self.assertEqual(self.model.error, "The test failed for: ntfy")

    def test_forbidden_makes_the_tab_read_only(self):
        self.client.fail["add_alert"] = "forbidden"
        self.model.add("ntfy", {"topic": "x"})
        self.assertTrue(self.model.read_only)


class TestJava(HostCase):
    def setUp(self):
        super().setUp()
        self.client.java_host = {"runtimes": {"21": "/j/21", "8": "/j/8"},
                                 "servers": [{"server": "a", "java": 21}, {"server": "b", "java": "21"}]}
        self.model = JavaModel(self.client, self.runner)
        self.model.load()

    def test_rows_and_usage(self):
        self.assertEqual([row["major"] for row in self.model.runtimes], ["8", "21"])
        self.assertEqual(self.model.runtimes[1]["servers"], ["a", "b"])
        self.assertEqual(self.model.installable(), ["11", "17", "25"])

    def test_install_is_a_job(self):
        self.assertTrue(self.model.install("17"))
        self.assertEqual(self.client.calls[:2], [("install_java", "17"), ("wait", "j_install_java")])
        self.assertEqual(self.model.message, "Java 17 installed")

    def test_remove_needs_confirmation(self):
        self.assertFalse(self.model.remove("8"))
        self.assertTrue(self.model.remove("8", True))
        self.assertEqual(self.model.message, "Java 8 removed")

    def test_invalid_version(self):
        self.assertFalse(self.model.install("abc"))
        self.assertEqual(self.model.error, "Unknown Java version")


class TestDevices(HostCase):
    def setUp(self):
        super().setUp()
        self.client.device_list = [
            {"id": "d_1", "name": "Phone", "roles": {"default": "operator"}, "last_seen": "2026-10-29T10:00:00",
             "last_ip": "10.0.0.2", "servers": ["a"]},
            {"id": "d_2", "name": "Old", "roles": {"default": "viewer"}, "last_seen": None, "revoked": True},
        ]
        self.client.audit = [{"at": "2026-10-29T10:00:00", "action": "stopServer", "ok": False, "device": "d_1",
                              "server": "a"}]
        self.client.remote = {"enabled": True, "fingerprint": "AA:BB"}
        self.model = DevicesModel(self.client, self.runner)
        self.model.load()

    def test_state(self):
        self.assertEqual([row["name"] for row in self.model.devices], ["Phone"])
        self.assertEqual(self.model.devices[0]["role_text"], "Operator")
        self.assertEqual(self.model.devices[0]["last_seen"], "2026-10-29 10:00:00")
        self.assertEqual(self.model.remote, {"enabled": True, "bind": "", "fingerprint": "AA:BB"})
        self.assertEqual((self.model.audit[0]["action"], self.model.audit[0]["ok"]), ("stopServer", False))

    def test_pairing_code(self):
        self.assertTrue(self.model.new_code(" tablet ", "viewer"))
        self.assertEqual(self.client.calls[0], ("pairing_code", "tablet", "viewer"))
        self.assertEqual(self.model.code, {"code": "12345678", "minutes": 5})
        self.assertFalse(self.model.new_code("x", "root"))

    def test_roles_revocation_and_remote_switch(self):
        self.assertTrue(self.model.set_role("d_1", "admin"))
        self.assertFalse(self.model.set_role("d_1", "root"))
        self.assertFalse(self.model.revoke("d_1"))
        self.assertTrue(self.model.revoke("d_1", True))
        self.assertFalse(self.model.set_remote(True))
        self.assertTrue(self.model.set_remote(False))
        self.assertEqual([call[0] for call in self.client.calls if call[0] != "wait"],
                         ["set_roles", "revoke_device", "set_remote"])

    def test_forbidden_hides_the_actions(self):
        self.client.fail["devices"] = "forbidden"
        self.model.load()
        self.assertTrue(self.model.read_only)


class TestUpdate(HostCase):
    def test_apply_needs_an_available_version_and_confirmation(self):
        model = UpdateModel(self.client, self.runner)
        model.load()
        self.assertFalse(model.apply(True))
        self.client.update_doc = {"current": "3.0.0", "latest": "3.1.0", "update_available": True,
                                  "rollback_available": True}
        model.load()
        self.assertEqual((model.info["available"], model.info["latest"]), (True, "3.1.0"))
        self.assertFalse(model.apply())
        self.assertTrue(model.apply(True))
        self.assertEqual(model.message, "Update installed")
        self.assertTrue(model.rollback(True))
        self.assertIn("rollback_update", [call[0] for call in self.client.calls])

    def test_failed_check_is_reported(self):
        self.client.fail["check_update"] = "check_failed"
        model = UpdateModel(self.client, self.runner)
        model.load()
        self.assertEqual(model.error, "The check failed")


class TestDoctor(HostCase):
    def test_report(self):
        self.client.doctor_doc = {"checks": [
            {"server": None, "name": "java", "ok": True, "level": "ok", "detail": "Java 21", "fix": None},
            {"server": "a", "name": "port", "ok": False, "level": "err", "detail": "busy", "fix": "mc configure"}],
            "errors": 1, "warnings": 0}
        model = DoctorModel(self.client, self.runner)
        model.load()
        self.assertEqual([check["level"] for check in model.checks], ["ok", "err"])
        self.assertEqual(model.checks[1]["fix"], "mc configure")
        self.assertEqual(model.summary(), "1 error(s) to fix")
        self.assertIsNone(model.busy)

    def test_clean_report(self):
        model = DoctorModel(self.client, self.runner)
        model.load()
        self.assertEqual(model.summary(), "Nothing to report")


class TestRouter(HostCase):
    def setUp(self):
        super().setUp()
        self.client.router_doc = {"config": {"enabled": True, "port": 25565, "default": "a",
                                             "routes": {"b.example.org": "b"}, "allow": ["10.0.0.0/8"], "deny": []},
                                  "pending_restart": ["b"]}
        self.model = RouterModel(self.client, self.runner)
        self.model.load()

    def test_state(self):
        state = self.model.state
        self.assertEqual((state["enabled"], state["default"], state["routes"], state["pending"]),
                         (True, "a", [("b.example.org", "b")], ["b"]))
        self.assertEqual(self.model.servers, ["a", "b"])

    def test_route_edition(self):
        self.assertTrue(self.model.add_route(" Mine.Example.org ", "b"))
        self.assertEqual(self.client.calls[0], ("set_route", "mine.example.org", "b"))
        self.assertFalse(self.model.add_route("", "b"))
        self.assertFalse(self.model.add_route("x.org", "zzz"))
        self.assertFalse(self.model.remove_route("b.example.org"))
        self.assertTrue(self.model.remove_route("b.example.org", True))

    def test_toggle_default_and_access(self):
        self.assertFalse(self.model.toggle(True))
        self.assertTrue(self.model.toggle(False))
        self.assertFalse(self.model.set_default("a"))
        self.assertTrue(self.model.set_default("b"))
        self.assertFalse(self.model.edit_access("block", "add", "1.2.3.4"))
        self.assertTrue(self.model.edit_access("deny", "add", " 1.2.3.0/24 "))
        self.assertEqual(self.client.calls[-1], ("router_access", "deny", "add", "1.2.3.0/24"))


class TestModpacks(HostCase):
    def test_lookup_then_creation_follows_the_job(self):
        model = CreateServerModel(self.client, self.runner)
        self.assertFalse(model.lookup(" "))
        self.assertTrue(model.lookup("cobblemon"))
        self.assertEqual(model.pack["loader"], "fabric")
        self.client.result = {"server": "cobblemon"}
        self.assertFalse(model.create_modpack("cobblemon", eula=False))
        self.assertTrue(model.create_modpack("cobblemon", ram="4g", eula=True))
        self.assertEqual(self.client.calls[-2], ("install_modpack", "cobblemon", None, "4G", None, None))
        self.assertEqual(model.created, "cobblemon")

    def test_modpack_update_reports_an_up_to_date_pack(self):
        self.client.result = {"code": "pack_up_to_date"}
        model = ModsModel(self.client, "a", self.runner)
        model.update_modpack()
        self.assertEqual(model.message, "The modpack is already up to date")


class TestNotifications(HostCase):
    def setUp(self):
        super().setUp()
        self.saved = []
        self.prefs = NotificationPrefs(lambda: {"join": False}, self.saved.append)

    def test_alert_events(self):
        crash = {"type": "alert", "server": "a", "event": "crash", "detail": "exit 1"}
        self.assertEqual(notification_for(crash, self.prefs), ("crash-a", "a crashed", "exit 1"))
        loop = dict(crash, event="crash_loop")
        self.assertEqual(notification_for(loop, self.prefs)[1], "a keeps crashing")
        failed = dict(crash, event="backup_failed", detail=None)
        self.assertEqual(notification_for(failed, self.prefs), ("backup_failed-a", "Backup of a failed", ""))
        self.assertIsNone(notification_for(dict(crash, event="start"), self.prefs))

    def test_joins_follow_the_preference(self):
        event = {"type": "players", "server": "a", "joined": ["Steve", "Alex"], "left": []}
        self.assertIsNone(notification_for(event, self.prefs))
        self.prefs.set("join", True)
        self.assertEqual(self.saved[-1]["join"], True)
        self.assertEqual(notification_for(event, self.prefs), ("join-a", "Player connected on a", "Steve, Alex"))
        self.assertIsNone(notification_for({"type": "players", "server": "a", "joined": []}, self.prefs))

    def test_disabling_a_kind_silences_it(self):
        self.prefs.set("crash", False)
        self.assertIsNone(notification_for({"type": "alert", "server": "a", "event": "crash"}, self.prefs))

    def test_events_of_the_list_model_reach_the_notifier(self):
        from mcmanager_app.models import ServerListModel
        sent = []
        model = ServerListModel(self.client, self.runner)
        model.on_event = NotificationsModel(self.prefs, lambda *args: sent.append(args)).on_event
        model.apply_event({"type": "alert", "server": "a", "event": "crash", "detail": None})
        self.assertEqual(sent, [("crash-a", "a crashed", "")])


if __name__ == "__main__":
    unittest.main()
