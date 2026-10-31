import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..i18n import t  # noqa: E402
from ..panels import DATAPACK_PLACEMENTS, MOD_SOURCES, DatapacksModel, ModsModel, WorldModel  # noqa: E402
from .common import (clear_rows, combo_row, confirm_dialog, entry_row, flush, icon_button, make_runner,  # noqa: E402
                     progress_bar, show_progress, text_button)


class ModsTab(Adw.PreferencesPage):
    def __init__(self, client, name, toast):
        super().__init__()
        self.toast = toast
        self.model = ModsModel(client, name, make_runner())
        self.install = Adw.PreferencesGroup(title=t("mod_install"))
        self.ref = entry_row(t("mod_ref"))
        self.ref.connect("entry-activated", lambda _e: self.add_mod())
        self.source = combo_row(t("mod_source"), [t("mod_source_" + (key or "auto")) for key in MOD_SOURCES])
        self.server_only = Adw.SwitchRow(title=t("mod_server_only"), subtitle=t("mod_server_only_hint"))
        self.add_button = text_button(t("mod_add"), "suggested-action")
        self.add_button.connect("clicked", lambda _b: self.add_mod())
        self.update_button = text_button(t("mod_update_all"))
        self.update_button.connect("clicked", lambda _b: self.model.update())
        self.pack_button = text_button(t("modpack_update"))
        self.pack_button.connect("clicked", lambda _b: self.model.update_modpack())
        buttons = Gtk.Box(spacing=6, margin_top=6)
        buttons.append(self.add_button)
        buttons.append(self.update_button)
        buttons.append(self.pack_button)
        self.progress = progress_bar()
        self.install.add(self.ref)
        self.install.add(self.source)
        self.install.add(self.server_only)
        self.install.add(buttons)
        self.install.add(self.progress)
        self.group = Adw.PreferencesGroup(title=t("tab_mods"))
        self.add(self.install)
        self.add(self.group)
        self.rows = []
        self.model.subscribe(self.refresh)
        self.model.load()

    def add_mod(self):
        source = MOD_SOURCES[self.source.get_selected()]
        if self.model.add(self.ref.get_text(), source, self.server_only.get_active()):
            self.ref.set_text("")

    def ask_remove(self, row, confirm_blocks=False):
        body = t("mod_blocks_body", name=row["name"]) if confirm_blocks else t("mod_remove_body", name=row["name"])
        confirm_dialog(self, t("mod_remove_title"), body, t("mod_remove"),
                       lambda: self.model.remove(row["file"], True, confirm_blocks))

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        self.rows = clear_rows(self.group, self.rows)
        for row in self.model.mods or [None]:
            if row is None:
                widget = Adw.ActionRow(title=t("mod_empty"))
            else:
                parts = [part for part in (row["version"], row["loader"], row["source_text"]) if part]
                if row["adds_blocks"]:
                    parts.append(t("mod_adds_blocks"))
                widget = Adw.ActionRow(title=row["name"], subtitle=" - ".join(parts))
                if editable:
                    update = icon_button("software-update-available-symbolic", t("mod_update_one", name=row["name"]), "flat")
                    update.set_valign(Gtk.Align.CENTER)
                    update.set_sensitive(not busy and row["source"] is not None)
                    update.connect("clicked", lambda _b, r=row: self.model.update(r["file"]))
                    remove = icon_button("user-trash-symbolic", t("mod_remove_name", name=row["name"]), "flat")
                    remove.set_valign(Gtk.Align.CENTER)
                    remove.set_sensitive(not busy)
                    remove.connect("clicked", lambda _b, r=row: self.ask_remove(r))
                    widget.add_suffix(update)
                    widget.add_suffix(remove)
            self.group.add(widget)
            self.rows.append(widget)
        self.install.set_visible(editable)
        self.add_button.set_sensitive(not busy)
        self.update_button.set_sensitive(not busy)
        self.pack_button.set_sensitive(not busy)
        show_progress(self.progress, self.model)
        pending = self.model.blocks_pending
        if pending:
            self.model.blocks_pending = None
            self.model.error = None
            row = next((r for r in self.model.mods if r["file"] == pending), None)
            if row:
                self.ask_remove(row, True)
        flush(self.model, self.toast)


class DatapacksTab(Adw.PreferencesPage):
    def __init__(self, client, name, toast):
        super().__init__()
        self.toast = toast
        self.model = DatapacksModel(client, name, make_runner())
        self.options = Adw.PreferencesGroup()
        self.placement = combo_row(t("pack_placement"), [t("pack_placement_" + (key or "default"))
                                                         for key in DATAPACK_PLACEMENTS])
        self.options.add(self.placement)
        self.group = Adw.PreferencesGroup(title=t("tab_datapacks"))
        self.add(self.options)
        self.add(self.group)
        self.rows = []
        self.model.subscribe(self.refresh)
        self.model.load()

    def refresh(self):
        self.rows = clear_rows(self.group, self.rows)
        editable = not self.model.read_only
        for row in self.model.packs or [None]:
            if row is None:
                widget = Adw.ActionRow(title=t("pack_empty"))
            else:
                subtitle = row["state_text"]
                if row["worldgen"]:
                    subtitle += " - " + t("pack_worldgen")
                widget = Adw.ActionRow(title=row["file"], subtitle=subtitle)
                if editable and not row["problem"]:
                    enable = row["enabled"] is not True
                    button = text_button(t("pack_enable") if enable else t("pack_disable"),
                                         "suggested-action" if enable else None)
                    button.update_property([Gtk.AccessibleProperty.LABEL],
                                           [t("pack_enable_name" if enable else "pack_disable_name", name=row["file"])])
                    button.set_sensitive(self.model.can_toggle(row, enable))
                    button.connect("clicked", lambda _b, r=row, e=enable: self.toggle(r, e))
                    widget.add_suffix(button)
            self.group.add(widget)
            self.rows.append(widget)
        self.options.set_visible(editable)
        flush(self.model, self.toast)

    def toggle(self, row, enable):
        placement = DATAPACK_PLACEMENTS[self.placement.get_selected()] if enable else ""
        self.model.toggle(row["file"], enable, placement)


class WorldTab(Adw.PreferencesPage):
    def __init__(self, client, name, toast):
        super().__init__()
        self.toast = toast
        self.model = WorldModel(client, name, make_runner())
        self.group = Adw.PreferencesGroup(title=t("tab_world"))
        self.progress = progress_bar()
        self.pregen = Adw.PreferencesGroup(title=t("pregen_title"), description=t("pregen_hint"))
        self.radius = entry_row(t("pregen_radius"))
        self.center = entry_row(t("pregen_center"))
        self.status = Adw.ActionRow(title=t("pregen_status"), subtitle_selectable=True)
        refresh = icon_button("view-refresh-symbolic", t("pregen_refresh"), "flat")
        refresh.set_valign(Gtk.Align.CENTER)
        refresh.connect("clicked", lambda _b: self.model.refresh_pregen())
        self.status.add_suffix(refresh)
        self.start_button = text_button(t("pregen_start"), "suggested-action")
        self.start_button.connect("clicked", lambda _b: self.model.start_pregen(self.radius.get_text(), self.center.get_text()))
        self.pregen.add(self.radius)
        self.pregen.add(self.center)
        self.pregen.add(self.status)
        self.pregen.add(self.start_button)
        self.add(self.group)
        self.add(self.pregen)
        self.group.add(self.progress)
        self.rows = []
        self.model.subscribe(self.refresh)
        self.model.load()

    def ask_reset(self, row):
        body_key = "world_reset_overworld_body" if row["id"] == "overworld" else "world_reset_body"
        confirm_dialog(self, t("world_reset_title"), t(body_key, name=self.dimension_name(row["id"])),
                       t("world_reset"), lambda: self.model.reset(row["id"], True))

    @staticmethod
    def dimension_name(identifier):
        key = "dimension_" + identifier
        return t(key) if t(key) != key else identifier

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        self.rows = clear_rows(self.group, self.rows)
        self.group.set_description(t("world_total", size=self.model.total_text) if self.model.dimensions else "")
        for row in self.model.dimensions or [None]:
            if row is None:
                widget = Adw.ActionRow(title=t("world_empty"))
            else:
                name = self.dimension_name(row["id"])
                widget = Adw.ActionRow(title=name, subtitle=row["size_text"])
                if editable:
                    button = text_button(t("world_reset"), "destructive-action")
                    button.update_property([Gtk.AccessibleProperty.LABEL], [t("world_reset_name", name=name)])
                    button.set_sensitive(not busy)
                    button.connect("clicked", lambda _b, r=row: self.ask_reset(r))
                    widget.add_suffix(button)
            self.group.add(widget)
            self.rows.append(widget)
        self.status.set_subtitle(self.model.pregen_text or self.model.pregen_note or t("pregen_idle"))
        for control in (self.radius, self.center, self.start_button):
            control.set_visible(editable)
        self.start_button.set_sensitive(not busy)
        show_progress(self.progress, self.model)
        flush(self.model, self.toast)
