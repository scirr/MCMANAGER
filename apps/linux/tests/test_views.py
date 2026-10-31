import unittest

from tests.support import FakeClient, sync_runner

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    HAVE_GTK = Gtk.init_check()
except (ImportError, ValueError):
    HAVE_GTK = False


@unittest.skipUnless(HAVE_GTK, "GTK 4 and libadwaita with a display are required")
class TestViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        from mcmanager_app import i18n
        i18n.set_language("en")
        self.client = FakeClient()
        self.client.servers = [{"name": "a", "state": "running", "rss_kb": 1048576, "active": True},
                               {"name": "b", "state": "stopped"}]
        self.client.player_docs["a"] = {"online": 1, "max": 20, "players": ["Steve"]}

    def test_server_list_shows_one_row_per_server(self):
        from mcmanager_app.models import ServerListModel
        from mcmanager_app.ui.server_list import ServerListView
        model = ServerListModel(self.client, sync_runner())
        picked = []
        view = ServerListView(model, picked.append)
        model.refresh()
        self.assertEqual(view.listbox.get_row_at_index(0).get_title(), "a")
        self.assertIsNotNone(view.listbox.get_row_at_index(1))
        self.assertIsNone(view.listbox.get_row_at_index(2))
        view.listbox.emit("row-activated", view.listbox.get_row_at_index(1))
        self.assertEqual(picked, ["b"])

    def test_empty_list_shows_the_status_page(self):
        from mcmanager_app.models import ServerListModel
        from mcmanager_app.ui.server_list import ServerListView
        self.client.servers = []
        model = ServerListModel(self.client, sync_runner())
        view = ServerListView(model, lambda name: None)
        model.refresh()
        self.assertEqual(view.stack.get_visible_child_name(), "empty")

    def test_detail_page_follows_the_model(self):
        from mcmanager_app.models import ServerListModel
        from mcmanager_app.ui import common, detail
        common.make_runner = sync_runner
        detail.make_runner = sync_runner
        model = ServerListModel(self.client, sync_runner())
        model.refresh()
        toasts = []
        page = detail.ServerDetailPage(self.client, model, "a", toasts.append)
        page.refresh()
        self.assertTrue(page.buttons["stop"].get_sensitive())
        self.assertFalse(page.buttons["start"].get_sensitive())
        self.assertEqual(self.client.streams[0].started, True)
        page.console.console.add_line("hello")
        self.assertIn("hello", page.console.text.get_buffer().get_text(
            page.console.text.get_buffer().get_start_iter(), page.console.text.get_buffer().get_end_iter(), False))
        page.close()
        self.assertTrue(self.client.streams[0].stopped)

    def test_new_tabs_follow_their_models(self):
        from mcmanager_app.ui import common, content_tabs, create, manage_tabs
        for module in (common, content_tabs, manage_tabs, create):
            module.make_runner = sync_runner
        self.client.mods = [{"file": "a.jar", "name": "A", "source": "modrinth", "adds_blocks": False}]
        self.client.packs = [{"id": "file/p.zip", "file": "p.zip", "enabled": False, "order": None,
                              "worldgen": False, "problem": None}]
        self.client.dimensions = [{"id": "overworld", "paths": [], "size_bytes": 10}]
        self.client.tasks = [{"id": 1, "name": "n", "cron": "0 4 * * *", "action": "restart", "enabled": True,
                              "warn": [60], "next_run": None, "last_result": None}]
        toasts = []
        mods = content_tabs.ModsTab(self.client, "a", toasts.append)
        self.assertEqual(mods.rows[0].get_title(), "A")
        packs = content_tabs.DatapacksTab(self.client, "a", toasts.append)
        self.assertEqual(packs.rows[0].get_title(), "p.zip")
        world = content_tabs.WorldTab(self.client, "a", toasts.append)
        self.assertEqual(world.rows[0].get_title(), "Overworld")
        tasks = manage_tabs.TasksTab(self.client, "a", toasts.append)
        self.assertEqual(tasks.rows[0].get_title(), "n")
        settings = manage_tabs.SettingsTab(self.client, "a", toasts.append)
        self.assertEqual(settings.entries["port"].get_text(), "25565")
        for tab in (mods, packs, world, tasks, settings):
            tab.model.read_only = True
            tab.model.notify()

    def test_alerts_tab_and_system_page_follow_their_models(self):
        from mcmanager_app.host_panels import NotificationPrefs
        from mcmanager_app.ui import alerts, common, system
        for module in (common, alerts, system):
            module.make_runner = sync_runner
        self.client.channels = [{"name": "ntfy", "type": "ntfy", "events": ["crash"], "topic": "mc"},
                                {"name": "discord", "type": "discord", "events": ["*"], "legacy": True}]
        self.client.java_host = {"runtimes": {"21": "/j"}, "servers": [{"server": "a", "java": 21}]}
        self.client.device_list = [{"id": "d_1", "name": "Phone", "roles": {"default": "operator"},
                                    "last_seen": None, "servers": None}]
        self.client.audit = [{"at": "2026-10-29T10:00:00", "action": "stopServer", "ok": True}]
        self.client.remote = {"enabled": True, "fingerprint": "AA"}
        self.client.update_doc = {"current": "3.0.0", "latest": "3.1.0", "update_available": True,
                                  "rollback_available": True}
        self.client.doctor_doc = {"checks": [{"server": "a", "name": "port", "ok": False, "level": "err",
                                              "detail": "busy", "fix": "fix it"}], "errors": 1, "warnings": 0}
        self.client.router_doc = {"config": {"enabled": True, "default": "a", "routes": {"h.example.org": "a"},
                                             "allow": ["10.0.0.0/8"], "deny": []}, "pending_restart": ["a"]}
        toasts = []
        tab = alerts.AlertsTab(self.client, "a", toasts.append)
        self.assertEqual([row.get_title() for row in tab.rows], ["ntfy", "discord"])
        tab.kind.set_selected(0)
        tab.fields["host"].set_text("smtp")
        tab.model.read_only = True
        tab.model.notify()
        self.assertFalse(tab.form.get_visible())
        prefs = NotificationPrefs()
        page = system.SystemPage(self.client, prefs, toasts.append)
        tabs = page.tabs
        self.assertEqual(tabs["java"].rows[0].get_title(), "Java 21")
        self.assertEqual(tabs["devices"].device_rows[0].get_title(), "Phone")
        self.assertTrue(tabs["devices"].remote_switch.get_active())
        self.assertEqual(tabs["router"].route_rows[0].get_title(), "h.example.org")
        self.assertTrue(tabs["router"].pending.get_visible())
        self.assertTrue(tabs["update"].apply_button.get_visible())
        self.assertEqual(len(tabs["doctor"].rows), 1)
        tabs["notifications"].switches["join"].set_active(False)
        self.assertFalse(prefs.enabled["join"])
        for tab in tabs.values():
            if hasattr(tab, "model"):
                tab.model.read_only = True
                tab.model.notify()
        self.assertFalse(tabs["update"].apply_button.get_visible())

    def test_creation_dialog_creates_from_a_modpack(self):
        from mcmanager_app.ui import common, create
        common.make_runner = create.make_runner = sync_runner
        self.client.result = {"server": "pack"}
        created = []
        dialog = create.CreateServerDialog(self.client, lambda message: None, created.append)
        dialog.pack.set_text("cobblemon")
        self.assertFalse(dialog.loader.get_visible())
        dialog.check.emit("clicked")
        self.assertTrue(dialog.pack_info.get_visible())
        dialog.eula.set_active(True)
        dialog.send()
        self.assertEqual(created, ["pack"])

    def test_creation_dialog_reports_the_new_server(self):
        from mcmanager_app.ui import common, create
        common.make_runner = create.make_runner = sync_runner
        created = []
        dialog = create.CreateServerDialog(self.client, lambda message: None, created.append)
        dialog.name.set_text("s")
        dialog.eula.set_active(True)
        dialog.send()
        self.assertEqual(created, ["s"])

    def test_welcome_pages_build(self):
        from mcmanager_app.models import ConnectionModel
        from mcmanager_app.ui.welcome import RemotePage, WelcomePage
        model = ConnectionModel(lambda: None, lambda name: None, None, lambda address: "AA", sync_runner())
        welcome = WelcomePage(model, lambda *a: None, lambda: None)
        remote = RemotePage(model, lambda *a: None)
        welcome.choose_local(None)
        self.assertTrue(welcome.error_label.get_visible())
        model.fetch_fingerprint("h:1")
        self.assertTrue(remote.code.get_visible())


if __name__ == "__main__":
    unittest.main()
