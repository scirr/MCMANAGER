import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..host_panels import ALERT_EVENTS, ALERT_FIELDS, ALERT_TYPES, AlertsModel  # noqa: E402
from ..i18n import t  # noqa: E402
from .common import (clear_rows, combo_row, confirm_dialog, entry_row, flush, icon_button, make_runner,  # noqa: E402
                     progress_bar, show_progress, text_button)

FIELD_KEYS = sorted({key for fields in ALERT_FIELDS.values() for key, _kind in fields})
SECRET_FIELDS = {key for fields in ALERT_FIELDS.values() for key, kind in fields if kind == "secret"}


class AlertsTab(Adw.PreferencesPage):
    def __init__(self, client, name, toast):
        super().__init__()
        self.toast = toast
        self.model = AlertsModel(client, name, make_runner())
        self.group = Adw.PreferencesGroup(title=t("tab_alerts"), description=t("alerts_hint"))
        self.progress = progress_bar()
        self.test_button = text_button(t("alert_test_all"))
        self.test_button.connect("clicked", lambda _b: self.model.test())
        self.group.add(self.test_button)
        self.group.add(self.progress)
        self.form = Adw.PreferencesGroup(title=t("alert_new"))
        self.kind = combo_row(t("alert_type"), [t("alert_type_" + kind) for kind in ALERT_TYPES])
        self.kind.connect("notify::selected", lambda *_a: self.sync_form())
        self.channel_name = entry_row(t("alert_name"))
        self.form.add(self.kind)
        self.form.add(self.channel_name)
        self.fields = {}
        for key in FIELD_KEYS:
            widget = Adw.PasswordEntryRow(title=t("alert_field_" + key)) if key in SECRET_FIELDS else entry_row(t("alert_field_" + key))
            self.fields[key] = widget
            self.form.add(widget)
        self.events = Adw.ExpanderRow(title=t("alert_events"), subtitle=t("alert_events_hint"))
        self.event_switches = {}
        for event in ALERT_EVENTS:
            row = Adw.SwitchRow(title=t("alert_event_" + event))
            self.events.add_row(row)
            self.event_switches[event] = row
        self.form.add(self.events)
        self.add_button = text_button(t("alert_add"), "suggested-action")
        self.add_button.connect("clicked", lambda _b: self.create())
        self.form.add(self.add_button)
        self.add(self.group)
        self.add(self.form)
        self.rows = []
        self.sync_form()
        self.model.subscribe(self.refresh)
        self.model.load()

    def selected_kind(self):
        return ALERT_TYPES[self.kind.get_selected()]

    def sync_form(self):
        shown = {key for key, _kind in ALERT_FIELDS[self.selected_kind()]}
        for key, widget in self.fields.items():
            widget.set_visible(key in shown)

    def create(self):
        kind = self.selected_kind()
        values = {key: self.fields[key].get_text() for key, _kind in ALERT_FIELDS[kind]}
        events = [event for event, row in self.event_switches.items() if row.get_active()]
        if self.model.add(kind, values, events, self.channel_name.get_text()):
            for widget in self.fields.values():
                widget.set_text("")
            self.channel_name.set_text("")

    def ask_remove(self, row):
        confirm_dialog(self, t("alert_remove_title"), t("alert_remove_body", name=row["name"]), t("alert_remove"),
                       lambda: self.model.remove(row["name"], True))

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        self.rows = clear_rows(self.group, self.rows)
        for row in self.model.channels or [None]:
            if row is None:
                widget = Adw.ActionRow(title=t("alert_empty"))
            else:
                parts = [part for part in (row["type_text"], row["target"], row["events_text"]) if part]
                if row["legacy"]:
                    parts.append(t("alert_legacy"))
                widget = Adw.ActionRow(title=row["name"], subtitle=" - ".join(parts))
                if editable:
                    test = icon_button("mail-send-symbolic", t("alert_test_name", name=row["name"]), "flat")
                    test.set_valign(Gtk.Align.CENTER)
                    test.set_sensitive(not busy)
                    test.connect("clicked", lambda _b, r=row: self.model.test(r["name"]))
                    widget.add_suffix(test)
                if editable and not row["legacy"]:
                    remove = icon_button("user-trash-symbolic", t("alert_remove_name", name=row["name"]), "flat")
                    remove.set_valign(Gtk.Align.CENTER)
                    remove.set_sensitive(not busy)
                    remove.connect("clicked", lambda _b, r=row: self.ask_remove(r))
                    widget.add_suffix(remove)
            self.group.add(widget)
            self.rows.append(widget)
        self.form.set_visible(editable)
        self.add_button.set_sensitive(not busy)
        self.test_button.set_sensitive(not busy and bool(self.model.channels))
        self.test_button.set_visible(editable)
        show_progress(self.progress, self.model)
        flush(self.model, self.toast)
