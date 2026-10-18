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
