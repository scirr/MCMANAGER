import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..i18n import t  # noqa: E402
from ..panels import LOADERS, CreateServerModel  # noqa: E402
from .common import combo_row, entry_row, flush, icon_button, make_runner, progress_bar, show_progress  # noqa: E402


class CreateServerDialog(Adw.Dialog):
    """Assistant to create a server; closes itself and reports the new name once the job succeeded."""

    def __init__(self, client, toast, on_created):
        super().__init__(title=t("create_title"), content_width=480)
        self.toast, self.on_created = toast, on_created
        self.model = CreateServerModel(client, make_runner())
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(description=t("create_hint"))
        self.name = entry_row(t("create_name"))
        self.pack = entry_row(t("create_modpack"))
        self.pack.set_show_apply_button(False)
        self.check = icon_button("system-search-symbolic", t("create_modpack_check"), "flat")
        self.check.set_valign(Gtk.Align.CENTER)
        self.check.connect("clicked", lambda _b: self.model.lookup(self.pack.get_text()))
        self.pack.add_suffix(self.check)
        self.pack_info = Adw.ActionRow(title=t("create_modpack_found"), visible=False)
        self.loader = combo_row(t("create_loader"), LOADERS)
        self.version = entry_row(t("create_version"))
        self.ram = entry_row(t("create_ram"))
        self.port = entry_row(t("create_port"))
        self.rcon_port = entry_row(t("create_rcon_port"))
        self.eula = Adw.SwitchRow(title=t("create_eula"), subtitle=t("create_eula_hint"))
        for widget in (self.name, self.pack, self.pack_info, self.loader, self.version, self.ram, self.port,
                       self.rcon_port, self.eula):
            group.add(widget)
        self.pack.connect("changed", lambda _e: self.sync_source())
        page.add(group)
        self.progress = progress_bar()
        self.submit = Gtk.Button(label=t("create_submit"), css_classes=["suggested-action"], halign=Gtk.Align.CENTER)
        self.submit.connect("clicked", lambda _b: self.send())
        footer = Adw.PreferencesGroup()
        footer.add(self.progress)
        footer.add(self.submit)
        page.add(footer)
        header = Adw.HeaderBar()
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(page)
        self.set_child(view)
        self.model.subscribe(self.refresh)

    def sync_source(self):
        modpack = bool(self.pack.get_text().strip())
        self.loader.set_visible(not modpack)
        self.version.set_visible(not modpack)
        self.pack_info.set_visible(modpack and bool(self.model.pack))

    def send(self):
        if self.pack.get_text().strip():
            self.model.create_modpack(self.pack.get_text(), self.name.get_text(), self.ram.get_text(),
                                      self.eula.get_active(), self.port.get_text(), self.rcon_port.get_text())
            return
        self.model.create(self.name.get_text(), LOADERS[self.loader.get_selected()], self.version.get_text(),
                          self.ram.get_text(), self.eula.get_active(), self.port.get_text(), self.rcon_port.get_text())

    def refresh(self):
        busy = self.model.busy is not None
        for widget in (self.name, self.pack, self.check, self.loader, self.version, self.ram, self.port,
                       self.rcon_port, self.eula, self.submit):
            widget.set_sensitive(not busy)
        pack = self.model.pack
        if pack:
            parts = [part for part in (pack["title"], pack["version"], pack["mc_version"], pack["loader"]) if part]
            self.pack_info.set_subtitle(" - ".join(parts))
        self.pack_info.set_visible(bool(pack) and bool(self.pack.get_text().strip()))
        show_progress(self.progress, self.model)
        created = self.model.created
        flush(self.model, self.toast)
        if created:
            self.model.created = None
            self.on_created(created)
            self.close()


def add_server_button(client, parent, toast, on_created):
    button = icon_button("list-add-symbolic", t("create_server"))
    button.connect("clicked", lambda _b: CreateServerDialog(client, toast, on_created).present(parent))
    return button
