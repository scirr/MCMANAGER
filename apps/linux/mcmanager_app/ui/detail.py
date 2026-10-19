import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..i18n import t  # noqa: E402
from ..models import ACTIONS, PLAYER_LISTS, BackupsModel, ConsoleModel, PlayersModel, ServerDetailModel, players_text  # noqa: E402
from .common import make_runner  # noqa: E402
from .content_tabs import DatapacksTab, ModsTab, WorldTab  # noqa: E402
from .manage_tabs import SettingsTab, TasksTab  # noqa: E402


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
    def __init__(self, client, name, toast):
        super().__init__()
        self.toast = toast
        self.model = PlayersModel(client, name, make_runner())
        self.online = Adw.PreferencesGroup()
        self.add(self.online)
        self.groups = {}
        self.entries = {}
        self.rows = {kind: [] for kind in PLAYER_LISTS}
        self.online_rows = []
        for kind in PLAYER_LISTS:
            group = Adw.PreferencesGroup(title=t("list_" + kind))
            entry = Adw.EntryRow(title=t("player_name"))
            entry.set_show_apply_button(False)
            button = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER)
            button.set_tooltip_text(t("player_add"))
            button.update_property([Gtk.AccessibleProperty.LABEL], [t("player_add")])
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, k=kind: self.add_player(k))
            entry.connect("entry-activated", lambda _e, k=kind: self.add_player(k))
            entry.add_suffix(button)
            group.add(entry)
            self.add(group)
            self.groups[kind], self.entries[kind] = group, entry
        self.row = None
        self.model.subscribe(self.refresh)
        self.model.load()

    def add_player(self, kind):
        entry = self.entries[kind]
        if self.model.add(kind, entry.get_text()):
            entry.set_text("")

    def remove_button(self, label, callback):
        button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        button.add_css_class("flat")
        button.set_tooltip_text(label)
        button.update_property([Gtk.AccessibleProperty.LABEL], [label])
        button.connect("clicked", lambda _b: callback())
        return button

    def show(self, row):
        self.row = row
        self.refresh()

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        for widget in self.online_rows:
            self.online.remove(widget)
        self.online_rows = []
        names = self.row["players"] if self.row else []
        self.online.set_title(players_text(self.row) if self.row else "")
        for name in names or [None]:
            widget = Adw.ActionRow(title=name or t("no_players"))
            if name and editable:
                button = self.remove_button(t("player_kick", name=name), lambda n=name: self.model.kick(n))
                button.set_sensitive(not busy)
                widget.add_suffix(button)
            self.online.add(widget)
            self.online_rows.append(widget)
        for kind in PLAYER_LISTS:
            for widget in self.rows[kind]:
                self.groups[kind].remove(widget)
            self.rows[kind] = []
            entries = self.model.lists[kind]
            for item in entries or [None]:
                name = item["name"] if item else None
                widget = Adw.ActionRow(title=name or t("list_empty"))
                if name and editable:
                    button = self.remove_button(t("player_remove", name=name),
                                                lambda k=kind, n=name: self.model.remove(k, n))
                    button.set_sensitive(not busy)
                    widget.add_suffix(button)
                self.groups[kind].add(widget)
                self.rows[kind].append(widget)
            self.entries[kind].set_sensitive(not busy)
            self.entries[kind].set_visible(editable)
        if self.model.error:
            self.toast(self.model.error)
            self.model.error = None
        elif self.model.message:
            self.toast(self.model.message)
            self.model.message = None


class BackupsTab(Adw.PreferencesPage):
    def __init__(self, client, name, toast):
        super().__init__()
        self.toast = toast
        self.model = BackupsModel(client, name, make_runner())
        self.actions = Adw.PreferencesGroup()
        self.create_button = Gtk.Button(label=t("backup_now"), css_classes=["suggested-action"], halign=Gtk.Align.START)
        self.create_button.connect("clicked", lambda _b: self.model.create())
        self.progress = Gtk.ProgressBar(visible=False, margin_top=12)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.create_button)
        box.append(self.progress)
        self.actions.add(box)
        self.group = Adw.PreferencesGroup()
        self.add(self.actions)
        self.add(self.group)
        self.rows = []
        self.model.subscribe(self.refresh)
        self.model.load()

    def ask_restore(self, entry):
        dialog = Adw.AlertDialog(heading=t("backup_restore_title"), body=t("backup_restore_body", date=entry["date"]))
        dialog.add_response("cancel", t("backup_cancel"))
        dialog.add_response("restore", t("backup_restore"))
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: self.model.restore(entry["id"], response == "restore"))
        dialog.present(self)

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        for widget in self.rows:
            self.group.remove(widget)
        self.rows = []
        for entry in self.model.backups or [None]:
            if entry:
                subtitle = "%s - %s" % (entry["size_text"], entry["origin_text"])
                if entry["encrypted"]:
                    subtitle += " - " + t("backup_encrypted")
                widget = Adw.ActionRow(title=entry["date"], subtitle=subtitle)
                button = Gtk.Button(label=t("backup_restore"), valign=Gtk.Align.CENTER, sensitive=not busy)
                button.connect("clicked", lambda _b, e=entry: self.ask_restore(e))
                if editable:
                    widget.add_suffix(button)
            else:
                widget = Adw.ActionRow(title=t("backup_empty"))
            self.group.add(widget)
            self.rows.append(widget)
        self.create_button.set_sensitive(not busy)
        self.create_button.set_visible(editable)
        self.progress.set_visible(busy)
        self.progress.set_fraction(self.model.progress / 100)
        if self.model.error:
            self.toast(self.model.error)
            self.model.error = None
        elif self.model.message:
            self.toast(self.model.message)
            self.model.message = None


class ServerDetailPage(Adw.NavigationPage):
    """Server sheet: action buttons and the Console, Players, Backups, Mods, Datapacks, World, Tasks and Settings tabs."""

    def __init__(self, client, list_model, name, toast):
        super().__init__(title=name, tag="detail")
        self.client, self.list_model, self.name, self.toast = client, list_model, name, toast
        self.model = ServerDetailModel(client, name, make_runner())
        self.console = ConsoleTab(ConsoleModel(client, name, make_runner()), toast)
        self.players = PlayersTab(client, name, toast)
        self.backups = BackupsTab(client, name, toast)
        self.mods = ModsTab(client, name, toast)
        self.datapacks = DatapacksTab(client, name, toast)
        self.world = WorldTab(client, name, toast)
        self.tasks = TasksTab(client, name, toast)
        self.settings = SettingsTab(client, name, toast)
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
        self.stack.add_titled_with_icon(self.backups, "backups", t("tab_backups"), "document-save-symbolic")
        self.stack.add_titled_with_icon(self.mods, "mods", t("tab_mods"), "application-x-addon-symbolic")
        self.stack.add_titled_with_icon(self.datapacks, "datapacks", t("tab_datapacks"), "package-x-generic-symbolic")
        self.stack.add_titled_with_icon(self.world, "world", t("tab_world"), "applications-science-symbolic")
        self.stack.add_titled_with_icon(self.tasks, "tasks", t("tab_tasks"), "alarm-symbolic")
        self.stack.add_titled_with_icon(self.settings, "settings", t("tab_settings"), "emblem-system-symbolic")
        switcher = Adw.ViewSwitcherBar(stack=self.stack, reveal=True)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.stack)
        view.add_bottom_bar(switcher)
        self.set_child(view)
        self.model.subscribe(self.refresh)
        list_model.subscribe(self.refresh)
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
        for message in (self.model.error, self.model.message):
            if message:
                self.toast(message)
        self.model.error = self.model.message = None
