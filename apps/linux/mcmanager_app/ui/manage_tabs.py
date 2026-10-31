import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..i18n import t  # noqa: E402
from ..panels import (JOIN_MODES, MODES, SECRET_KEYS, SETTING_GROUPS, TASK_ACTIONS, WARN_ACTIONS, SettingsModel,  # noqa: E402
                      TasksModel)
from .common import (clear_rows, combo_row, confirm_dialog, entry_row, flush, icon_button, make_runner,  # noqa: E402
                     progress_bar, show_progress, text_button)


class TasksTab(Adw.PreferencesPage):
    def __init__(self, client, name, toast):
        super().__init__()
        self.toast = toast
        self.model = TasksModel(client, name, make_runner())
        self.form = Adw.PreferencesGroup(title=t("task_new"))
        self.action = combo_row(t("task_action"), [t("task_action_" + key) for key in TASK_ACTIONS])
        self.action.connect("notify::selected", lambda *_a: self.sync_form())
        self.cron = entry_row(t("task_cron"))
        self.title = entry_row(t("task_name"))
        self.command = entry_row(t("task_command"))
        self.warn = entry_row(t("task_warn"))
        self.create_button = text_button(t("task_create"), "suggested-action")
        self.create_button.connect("clicked", lambda _b: self.create())
        for widget in (self.action, self.cron, self.title, self.command, self.warn, self.create_button):
            self.form.add(widget)
        self.progress = progress_bar()
        self.group = Adw.PreferencesGroup(title=t("tab_tasks"))
        self.group.add(self.progress)
        self.add(self.form)
        self.add(self.group)
        self.rows = []
        self.sync_form()
        self.model.subscribe(self.refresh)
        self.model.load()

    def selected_action(self):
        return TASK_ACTIONS[self.action.get_selected()]

    def sync_form(self):
        action = self.selected_action()
        self.command.set_visible(action == "command")
        self.warn.set_visible(action in WARN_ACTIONS)

    def create(self):
        if self.model.create(self.selected_action(), self.cron.get_text(), self.title.get_text(),
                             self.command.get_text(), self.warn.get_text()):
            for entry in (self.cron, self.title, self.command, self.warn):
                entry.set_text("")

    def ask_delete(self, row):
        confirm_dialog(self, t("task_delete_title"), t("task_delete_body", name=row["name"]), t("task_delete"),
                       lambda: self.model.delete(row["id"], True))

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        self.rows = clear_rows(self.group, self.rows)
        for row in self.model.tasks or [None]:
            if row is None:
                widget = Adw.ActionRow(title=t("task_empty"))
            else:
                parts = [row["cron"], row["action_text"]]
                if row["warn_text"]:
                    parts.append(t("task_warn_value", value=row["warn_text"]))
                if row["enabled"] and row["next_text"]:
                    parts.append(t("task_next", date=row["next_text"]))
                if not row["enabled"]:
                    parts.append(t("task_disabled"))
                if row["last_text"]:
                    parts.append(row["last_text"])
                widget = Adw.ActionRow(title=row["name"], subtitle=" - ".join(parts))
                if editable:
                    toggle = text_button(t("task_disable") if row["enabled"] else t("task_enable"))
                    toggle.update_property([Gtk.AccessibleProperty.LABEL],
                                           [t("task_disable_name" if row["enabled"] else "task_enable_name", name=row["name"])])
                    toggle.set_sensitive(not busy)
                    toggle.connect("clicked", lambda _b, r=row: self.model.set_enabled(r["id"], not r["enabled"]))
                    run = icon_button("media-playback-start-symbolic", t("task_run_name", name=row["name"]), "flat")
                    run.set_valign(Gtk.Align.CENTER)
                    run.set_sensitive(not busy)
                    run.connect("clicked", lambda _b, r=row: self.model.run(r["id"], True))
                    delete = icon_button("user-trash-symbolic", t("task_delete_name", name=row["name"]), "flat")
                    delete.set_valign(Gtk.Align.CENTER)
                    delete.set_sensitive(not busy)
                    delete.connect("clicked", lambda _b, r=row: self.ask_delete(r))
                    for button in (toggle, run, delete):
                        widget.add_suffix(button)
            self.group.add(widget)
            self.rows.append(widget)
        self.form.set_visible(editable)
        self.create_button.set_sensitive(not busy)
        show_progress(self.progress, self.model)
        flush(self.model, self.toast)


class SettingsTab(Adw.PreferencesPage):
    def __init__(self, client, name, toast):
        super().__init__()
        self.toast = toast
        self.model = SettingsModel(client, name, make_runner())
        self.shown = {}
        self.entries = {}
        self.groups = []
        for group_name, fields in SETTING_GROUPS:
            group = Adw.PreferencesGroup(title=t("settings_" + group_name))
            for key, _kind in fields:
                entry = entry_row(t("setting_" + key))
                entry.set_show_apply_button(True)
                entry.connect("apply", lambda e, k=key: self.model.set_value(k, e.get_text()))
                group.add(entry)
                self.entries[key] = entry
            self.add(group)
            self.groups.append(group)
        self.mode = combo_row(t("settings_mode"), [t("mode_" + mode) for mode in MODES])
        self.mode.connect("notify::selected", lambda *_a: self.apply_mode())
        self.open = entry_row(t("settings_open"))
        self.close = entry_row(t("settings_close"))
        for entry in (self.open, self.close):
            entry.set_show_apply_button(True)
            entry.connect("apply", lambda _e: self.model.set_schedule(self.open.get_text(), self.close.get_text()))
        self.java = combo_row(t("settings_java"), [])
        self.java.connect("notify::selected", lambda *_a: self.apply_java())
        run = Adw.PreferencesGroup(title=t("settings_running"))
        for widget in (self.mode, self.open, self.close, self.java):
            run.add(widget)
        self.add(run)
        self.groups.append(run)
        self.sleep_group = Adw.PreferencesGroup(title=t("settings_sleep"), description=t("settings_sleep_hint"))
        self.sleep_enabled = Adw.SwitchRow(title=t("sleep_enabled"))
        self.sleep_minutes = entry_row(t("sleep_minutes"))
        self.sleep_join = combo_row(t("sleep_join_mode"), [t("sleep_join_" + mode) for mode in JOIN_MODES])
        self.sleep_freeze = Adw.SwitchRow(title=t("sleep_freeze"), subtitle=t("sleep_freeze_hint"))
        self.sleep_apply = text_button(t("sleep_apply"), "suggested-action")
        self.sleep_apply.connect("clicked", lambda _b: self.apply_sleep())
        for widget in (self.sleep_enabled, self.sleep_minutes, self.sleep_join, self.sleep_freeze, self.sleep_apply):
            self.sleep_group.add(widget)
        self.add(self.sleep_group)
        self.groups.append(self.sleep_group)
        self.secret_group = Adw.PreferencesGroup(title=t("settings_secrets"), description=t("settings_secrets_hint"))
        self.secrets = {}
        for key in SECRET_KEYS:
            entry = Adw.PasswordEntryRow(title=t("secret_" + key))
            entry.set_show_apply_button(True)
            entry.connect("apply", lambda e, k=key: self.apply_secret(k, e))
            self.secret_group.add(entry)
            self.secrets[key] = entry
        self.add(self.secret_group)
        self.groups.append(self.secret_group)
        self.loading = False
        self.model.subscribe(self.refresh)
        self.model.load()

    def apply_secret(self, key, entry):
        if self.model.set_secret(key, entry.get_text()):
            entry.set_text("")

    def apply_sleep(self):
        self.model.set_sleep(self.sleep_enabled.get_active(), self.sleep_minutes.get_text(),
                             JOIN_MODES[self.sleep_join.get_selected()], self.sleep_freeze.get_active())

    def apply_mode(self):
        if not self.loading:
            self.model.set_mode(MODES[self.mode.get_selected()])

    def apply_java(self):
        if not self.loading and self.model.java_choices:
            self.model.set_java(self.model.java_choices[self.java.get_selected()])

    def show_values(self):
        model = self.model
        self.loading = True
        for key, entry in self.entries.items():
            entry.set_text(model.values.get(key, ""))
        self.mode.set_selected(MODES.index(model.mode))
        self.open.set_text(model.open_time)
        self.close.set_text(model.close_time)
        self.java.set_model(Gtk.StringList.new([t("java_system") if c == "system" else c for c in model.java_choices]))
        if model.java in model.java_choices:
            self.java.set_selected(model.java_choices.index(model.java))
        sleep = model.sleep
        if sleep:
            self.sleep_enabled.set_active(sleep["enabled"])
            self.sleep_minutes.set_text(sleep["minutes"])
            self.sleep_join.set_selected(JOIN_MODES.index(sleep["join_mode"]) if sleep["join_mode"] in JOIN_MODES else 0)
            self.sleep_freeze.set_active(sleep["freeze"])
            self.sleep_freeze.set_visible(sleep["freeze_supported"])
        for key, entry in self.secrets.items():
            state = t("secret_set") if key in model.secrets_set else t("secret_unset")
            entry.set_title("%s (%s)" % (t("secret_" + key), state))
        self.loading = False

    def refresh(self):
        model = self.model
        signature = (model.values, tuple(model.secrets_set), model.mode, model.open_time, model.close_time,
                     model.java, tuple(model.java_choices), tuple(sorted(model.sleep.items())))
        if signature != self.shown:
            self.shown = signature
            self.show_values()
        for group in self.groups:
            group.set_sensitive(model.busy is None and not model.read_only)
        flush(model, self.toast)
