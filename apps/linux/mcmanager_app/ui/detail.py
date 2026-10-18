import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..i18n import t  # noqa: E402
from ..models import ACTIONS, ConsoleModel, ServerDetailModel, players_text  # noqa: E402
from .common import make_runner  # noqa: E402


class ConsoleTab(Gtk.Box):
    def __init__(self, console, toast):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.console, self.toast = console, toast
        self.shown = 0
        self.text = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                 top_margin=6, bottom_margin=6, left_margin=6, right_margin=6)
        self.text.update_property([Gtk.AccessibleProperty.LABEL], [t("tab_console")])
        self.scroller = Gtk.ScrolledWindow(child=self.text, vexpand=True)
        self.entry = Gtk.Entry(placeholder_text=t("console_placeholder"), hexpand=True)
        self.entry.update_property([Gtk.AccessibleProperty.LABEL], [t("console_placeholder")])
        self.entry.connect("activate", self.send)
        self.send_button = Gtk.Button(label=t("console_send"), css_classes=["suggested-action"])
        self.send_button.connect("clicked", self.send)
        bar = Gtk.Box(spacing=6, margin_start=6, margin_end=6, margin_bottom=6)
        bar.append(self.entry)
        bar.append(self.send_button)
        self.append(self.scroller)
        self.append(bar)
        console.subscribe(self.refresh)

    def send(self, *_args):
        if self.console.send(self.entry.get_text()):
            self.entry.set_text("")

    def refresh(self):
        buffer = self.text.get_buffer()
        buffer.set_text("\n".join(self.console.lines))
        self.send_button.set_sensitive(not self.console.sending)
        if self.console.error:
            self.toast(self.console.error)
            self.console.error = None
        adjustment = self.scroller.get_vadjustment()
        GLib.idle_add(lambda: adjustment.set_value(adjustment.get_upper()) and False)

    def stop(self):
        self.console.stop()


class PlayersTab(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.group = Adw.PreferencesGroup()
        self.add(self.group)
        self.rows = []

    def show(self, row):
        for widget in self.rows:
            self.group.remove(widget)
        self.rows = []
        names = row["players"] if row else []
        self.group.set_title(players_text(row) if row else "")
        if not names:
            names = []
            widget = Adw.ActionRow(title=t("no_players"))
            self.group.add(widget)
            self.rows.append(widget)
        for name in names:
            widget = Adw.ActionRow(title=name)
            self.group.add(widget)
            self.rows.append(widget)


class SettingsTab(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.group = Adw.PreferencesGroup()
        self.add(self.group)
        self.rows = []

    def show(self, config, secrets):
        for widget in self.rows:
            self.group.remove(widget)
        self.rows = []
        entries = sorted(config.items())
        if not entries:
            entries = [(t("settings_empty"), "")]
        for key, value in entries:
            widget = Adw.ActionRow(title=str(key), subtitle=str(value), subtitle_selectable=True)
            self.group.add(widget)
            self.rows.append(widget)
        self.group.set_description(t("secrets_set", names=", ".join(secrets)) if secrets else "")


class ServerDetailPage(Adw.NavigationPage):
    """Server sheet: action buttons and the Console, Players and Settings tabs."""

    def __init__(self, client, list_model, name, toast):
        super().__init__(title=name, tag="detail")
        self.client, self.list_model, self.name, self.toast = client, list_model, name, toast
        self.model = ServerDetailModel(client, name, make_runner())
        self.console = ConsoleTab(ConsoleModel(client, name, make_runner()), toast)
        self.players = PlayersTab()
        self.settings = SettingsTab()
        self.buttons = {}
        header = Adw.HeaderBar()
        for action in ACTIONS:
            button = Gtk.Button(label=t(action))
            button.connect("clicked", lambda _b, a=action: self.model.run_action(a))
            header.pack_end(button)
            self.buttons[action] = button
        self.spinner = Gtk.Spinner()
        header.pack_start(self.spinner)
        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(self.console, "console", t("tab_console"), "utilities-terminal-symbolic")
        self.stack.add_titled_with_icon(self.players, "players", t("tab_players"), "system-users-symbolic")
        self.stack.add_titled_with_icon(self.settings, "settings", t("tab_settings"), "emblem-system-symbolic")
        switcher = Adw.ViewSwitcherBar(stack=self.stack, reveal=True)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.stack)
        view.add_bottom_bar(switcher)
        self.set_child(view)
        self.model.subscribe(self.refresh)
        list_model.subscribe(self.refresh)
        self.model.load_config()
        self.console.console.start()
        self.connect("hidden", lambda _p: self.close())

    def close(self):
        self.console.stop()

    def refresh(self):
        row = self.list_model.rows.get(self.name)
        state = row["state"] if row else "unknown"
        allowed = self.model.can(state)
        for action, button in self.buttons.items():
            button.set_sensitive(allowed[action])
            button.set_visible(action != "wake" or state == "sleeping")
        self.spinner.set_spinning(bool(self.model.busy))
        self.players.show(row)
        self.settings.show(self.model.config, self.model.secrets_set)
        for message in (self.model.error, self.model.message):
            if message:
                self.toast(message)
        self.model.error = self.model.message = None
