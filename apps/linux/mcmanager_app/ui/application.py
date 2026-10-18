import json
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import APP_ID, client as api  # noqa: E402
from ..i18n import t  # noqa: E402
from ..models import ConnectionModel, ServerListModel  # noqa: E402
from .common import make_runner  # noqa: E402
from .detail import ServerDetailPage  # noqa: E402
from .server_list import ServerListView, refresh_button  # noqa: E402
from .welcome import RemotePage, WelcomePage  # noqa: E402


def choice_path():
    return os.path.join(GLib.get_user_config_dir(), "mcmanager-app", "connection.json")


def load_choice():
    try:
        with open(choice_path(), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def save_choice(mode, profile):
    path = choice_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"mode": mode, "profile": profile}, handle)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title=t("app_title"), default_width=1000, default_height=680)
        self.runner = make_runner()
        self.connection = ConnectionModel(api.LocalTransport.discover, api.RemoteTransport.from_profile,
                                          api.pair_remote, api.probe_fingerprint, self.runner)
        self.list_model = None
        self.detail = None
        self.warned = False
        self.overlay = Adw.ToastOverlay()
        self.set_content(self.overlay)
        self.navigation = Adw.NavigationView()
        self.overlay.set_child(self.navigation)
        self.connect("close-request", self.on_close)
        choice = load_choice()
        if choice and self.restore(choice):
            return
        self.show_welcome()

    def toast(self, message):
        self.overlay.add_toast(Adw.Toast(title=message))

    def restore(self, choice):
        if choice.get("mode") == "local":
            client = self.connection.use_local()
        else:
            client = self.connection.use_profile(choice.get("profile") or "default")
        if client is None:
            return False
        self.show_dashboard(client)
        return True

    def show_welcome(self):
        self.connection.error = None
        self.navigation.replace([WelcomePage(self.connection, self.connected, self.show_remote)])

    def show_remote(self):
        self.navigation.push(RemotePage(self.connection, self.connected))

    def connected(self, mode, profile):
        save_choice(mode, profile)
        self.show_dashboard(self.connection.client)

    def show_dashboard(self, client):
        if self.list_model:
            self.list_model.stop_events()
        self.client = client
        self.list_model = ServerListModel(client, self.runner)
        self.list_model.subscribe(self.on_list_changed)
        self.split = Adw.NavigationSplitView()
        sidebar_view = Adw.ToolbarView()
        header = Adw.HeaderBar(title_widget=Gtk.Label(label=t("servers")))
        header.pack_start(refresh_button(self.list_model))
        header.pack_end(self.build_menu())
        sidebar_view.add_top_bar(header)
        sidebar_view.set_content(ServerListView(self.list_model, self.select))
        self.sidebar = Adw.NavigationPage(title=t("servers"), child=sidebar_view)
        self.placeholder = Adw.NavigationPage(title=t("app_title"), child=self.placeholder_view())
        self.split.set_sidebar(self.sidebar)
        self.split.set_content(self.placeholder)
        page = Adw.NavigationPage(title=t("app_title"), tag="dashboard", child=self.split)
        self.navigation.replace([page])
        self.list_model.refresh()
        self.list_model.start_events()

    def placeholder_view(self):
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(Adw.StatusPage(icon_name="io.github.scirr.MCManager", title=t("select_server")))
        return view

    def build_menu(self):
        menu = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text=t("menu"))
        menu.update_property([Gtk.AccessibleProperty.LABEL], [t("menu")])
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        for label, handler in ((t("this_machine"), self.switch_local), (t("remote_server"), self.show_welcome_again)):
            button = Gtk.Button(label=label, css_classes=["flat"])
            button.connect("clicked", lambda _b, h=handler: (popover.popdown(), h()))
            box.append(button)
        popover.set_child(box)
        menu.set_popover(popover)
        return menu

    def switch_local(self):
        client = self.connection.use_local()
        if client is None:
            self.toast(self.connection.error)
            return
        self.connected("local", None)

    def show_welcome_again(self):
        self.show_welcome()

    def select(self, name):
        if self.detail:
            self.detail.close()
        detail = ServerDetailPage(self.client, self.list_model, name, self.toast)
        self.detail = detail
        self.split.set_content(detail)
        self.split.set_show_content(True)

    def on_list_changed(self):
        model = self.list_model
        if model.error:
            self.toast(model.error)
            model.error = None
        if not model.connected and not self.warned:
            self.toast(t("connection_lost"))
        self.warned = not model.connected

    def on_close(self, _window):
        if self.detail:
            self.detail.close()
        if self.list_model:
            self.list_model.stop_events()
        return False


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()
