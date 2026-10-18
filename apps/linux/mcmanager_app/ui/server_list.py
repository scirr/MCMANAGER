import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..i18n import t  # noqa: E402
from ..models import players_text  # noqa: E402
from .common import icon_button  # noqa: E402

STATE_CLASS = {"running": "success", "crashed": "error", "starting": "warning", "sleeping": "dim-label"}


class ServerListView(Gtk.Box):
    """Sidebar content: one row per server (name, state, players, RAM)."""

    def __init__(self, model, on_select):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.model, self.on_select = model, on_select
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.connect("row-activated", self.activated)
        self.empty = Adw.StatusPage(icon_name="computer-symbolic", title=t("no_servers"),
                                    description=t("no_servers_hint"), vexpand=True)
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.ScrolledWindow(child=self.listbox, vexpand=True), "list")
        self.stack.add_named(self.empty, "empty")
        self.append(self.stack)
        self.names = []
        model.subscribe(self.refresh)

    def activated(self, _box, row):
        self.on_select(self.names[row.get_index()])

    def refresh(self):
        self.listbox.remove_all()
        self.names = list(self.model.rows)
        for name in self.names:
            self.listbox.append(self.make_row(self.model.rows[name]))
        self.stack.set_visible_child_name("list" if self.names else "empty")

    def make_row(self, row):
        subtitle = " - ".join(part for part in (row["state_text"], players_text(row), row["ram_text"]) if part)
        widget = Adw.ActionRow(title=row["name"], subtitle=subtitle, activatable=True)
        dot = Gtk.Image(icon_name="media-record-symbolic")
        dot.add_css_class(STATE_CLASS.get(row["state"], "dim-label"))
        dot.update_property([Gtk.AccessibleProperty.LABEL], [row["state_text"]])
        widget.add_prefix(dot)
        return widget


def refresh_button(model):
    button = icon_button("view-refresh-symbolic", t("refresh"))
    button.connect("clicked", lambda _b: model.refresh())
    return button
