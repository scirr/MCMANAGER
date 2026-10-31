import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..host_panels import (NOTIFY_KINDS, ROLES, DevicesModel, DoctorModel, JavaModel, RouterModel,  # noqa: E402
                           UpdateModel)
from ..i18n import t  # noqa: E402
from .common import (clear_rows, combo_row, confirm_dialog, entry_row, flush, icon_button, make_runner,  # noqa: E402
                     progress_bar, show_progress, text_button)

LEVEL_ICONS = {"ok": "emblem-ok-symbolic", "info": "dialog-information-symbolic",
               "warn": "dialog-warning-symbolic", "err": "dialog-error-symbolic"}


def trash_button(label, callback, sensitive=True):
    button = icon_button("user-trash-symbolic", label, "flat")
    button.set_valign(Gtk.Align.CENTER)
    button.set_sensitive(sensitive)
    button.connect("clicked", lambda _b: callback())
    return button


class JavaTab(Adw.PreferencesPage):
    def __init__(self, client, toast):
        super().__init__()
        self.toast = toast
        self.model = JavaModel(client, make_runner())
        self.group = Adw.PreferencesGroup(title=t("tab_java"), description=t("java_hint"))
        self.progress = progress_bar()
        self.group.add(self.progress)
        self.install = Adw.PreferencesGroup(title=t("java_install"))
        self.major = combo_row(t("java_version"), [])
        self.install_button = text_button(t("java_install_button"), "suggested-action")
        self.install_button.connect("clicked", lambda _b: self.install_selected())
        self.install.add(self.major)
        self.install.add(self.install_button)
        self.add(self.group)
        self.add(self.install)
        self.rows = []
        self.choices = []
        self.model.subscribe(self.refresh)
        self.model.load()

    def install_selected(self):
        if self.choices:
            self.model.install(self.choices[self.major.get_selected()])

    def ask_remove(self, row):
        confirm_dialog(self, t("java_remove_title"), t("java_remove_body", major=row["major"]), t("java_remove"),
                       lambda: self.model.remove(row["major"], True))

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        self.rows = clear_rows(self.group, self.rows)
        for row in self.model.runtimes or [None]:
            if row is None:
                widget = Adw.ActionRow(title=t("java_empty"))
            else:
                used = t("java_used_by", servers=", ".join(row["servers"])) if row["servers"] else t("java_unused")
                widget = Adw.ActionRow(title=t("java_runtime", major=row["major"]), subtitle=used)
                if editable:
                    widget.add_suffix(trash_button(t("java_remove_name", major=row["major"]),
                                                   lambda r=row: self.ask_remove(r), not busy))
            self.group.add(widget)
            self.rows.append(widget)
        choices = self.model.installable()
        if choices != self.choices:
            self.choices = choices
            self.major.set_model(Gtk.StringList.new(choices))
        self.install.set_visible(editable)
        self.install_button.set_sensitive(not busy and bool(self.choices))
        show_progress(self.progress, self.model)
        flush(self.model, self.toast)


class DevicesTab(Adw.PreferencesPage):
    def __init__(self, client, toast):
        super().__init__()
        self.toast = toast
        self.model = DevicesModel(client, make_runner())
        self.loading = False
        self.remote_group = Adw.PreferencesGroup(title=t("remote_access_title"), description=t("remote_hint"))
        self.remote_switch = Adw.SwitchRow(title=t("remote_enabled_label"))
        self.remote_switch.connect("notify::active", lambda *_a: self.apply_remote())
        self.fingerprint = Adw.ActionRow(title=t("remote_fingerprint"), subtitle_selectable=True)
        self.remote_group.add(self.remote_switch)
        self.remote_group.add(self.fingerprint)
        self.pair_group = Adw.PreferencesGroup(title=t("pair_title"), description=t("pair_hint"))
        self.pair_name = entry_row(t("pair_device_name"))
        self.pair_role = combo_row(t("pair_role"), [t("role_" + role) for role in ROLES])
        self.pair_role.set_selected(1)
        self.pair_button = text_button(t("pair_generate"), "suggested-action")
        self.pair_button.connect("clicked", lambda _b: self.model.new_code(
            self.pair_name.get_text(), ROLES[self.pair_role.get_selected()]))
        self.pair_code = Adw.ActionRow(title=t("pair_code_label"), subtitle_selectable=True, visible=False)
        for widget in (self.pair_name, self.pair_role, self.pair_button, self.pair_code):
            self.pair_group.add(widget)
        self.devices_group = Adw.PreferencesGroup(title=t("devices_title"))
        self.audit_group = Adw.PreferencesGroup(title=t("audit_title"))
        self.progress = progress_bar()
        self.devices_group.add(self.progress)
        for group in (self.remote_group, self.pair_group, self.devices_group, self.audit_group):
            self.add(group)
        self.device_rows = []
        self.audit_rows = []
        self.model.subscribe(self.refresh)
        self.model.load()

    def apply_remote(self):
        if not self.loading:
            self.model.set_remote(self.remote_switch.get_active())

    def ask_revoke(self, row):
        confirm_dialog(self, t("device_revoke_title"), t("device_revoke_body", name=row["name"]), t("device_revoke"),
                       lambda: self.model.revoke(row["id"], True))

    def role_dropdown(self, row, busy):
        dropdown = Gtk.DropDown.new_from_strings([t("role_" + role) for role in ROLES])
        dropdown.set_valign(Gtk.Align.CENTER)
        dropdown.update_property([Gtk.AccessibleProperty.LABEL], [t("device_role_name", name=row["name"])])
        dropdown.set_selected(ROLES.index(row["role"]) if row["role"] in ROLES else 0)
        dropdown.set_sensitive(not busy)
        dropdown.connect("notify::selected", lambda d, _p, r=row: self.change_role(r, ROLES[d.get_selected()]))
        return dropdown

    def change_role(self, row, role):
        if role != row["role"]:
            self.model.set_role(row["id"], role)

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        self.loading = True
        self.remote_switch.set_active(bool(self.model.remote.get("enabled")))
        self.loading = False
        self.remote_switch.set_sensitive(not busy and editable)
        self.fingerprint.set_subtitle(self.model.remote.get("fingerprint") or "-")
        self.fingerprint.set_visible(bool(self.model.remote.get("fingerprint")))
        self.pair_group.set_visible(editable)
        self.pair_button.set_sensitive(not busy)
        code = self.model.code
        self.pair_code.set_visible(bool(code))
        if code:
            self.pair_code.set_subtitle(t("pair_code_value", code=code["code"], minutes=code["minutes"]))
        self.device_rows = clear_rows(self.devices_group, self.device_rows)
        for row in self.model.devices or [None]:
            if row is None:
                widget = Adw.ActionRow(title=t("devices_empty"))
            else:
                parts = [part for part in (row["last_ip"], t("device_last_seen", date=row["last_seen"])
                                           if row["last_seen"] else t("device_never_seen")) if part]
                if row["servers"]:
                    parts.append(", ".join(row["servers"]))
                widget = Adw.ActionRow(title=row["name"], subtitle=" - ".join(parts))
                if editable:
                    widget.add_suffix(self.role_dropdown(row, busy))
                    widget.add_suffix(trash_button(t("device_revoke_name", name=row["name"]),
                                                   lambda r=row: self.ask_revoke(r), not busy))
                else:
                    widget.add_suffix(Gtk.Label(label=row["role_text"]))
            self.devices_group.add(widget)
            self.device_rows.append(widget)
        self.audit_rows = clear_rows(self.audit_group, self.audit_rows)
        for entry in self.model.audit[:50] or [None]:
            if entry is None:
                widget = Adw.ActionRow(title=t("audit_empty"))
            else:
                who = " - ".join(part for part in (entry["device"], entry["server"]) if part)
                widget = Adw.ActionRow(title=entry["action"], subtitle=" - ".join(
                    part for part in (entry["at"], who, "" if entry["ok"] else t("audit_refused")) if part))
            self.audit_group.add(widget)
            self.audit_rows.append(widget)
        self.audit_group.set_visible(editable)
        show_progress(self.progress, self.model)
        flush(self.model, self.toast)


class RouterTab(Adw.PreferencesPage):
    def __init__(self, client, toast):
        super().__init__()
        self.toast = toast
        self.model = RouterModel(client, make_runner())
        self.loading = False
        self.shown_servers = None
        self.main = Adw.PreferencesGroup(title=t("tab_router"), description=t("router_hint"))
        self.switch = Adw.SwitchRow(title=t("router_enabled_label"))
        self.switch.connect("notify::active", lambda *_a: self.apply_toggle())
        self.default = combo_row(t("router_default"), [])
        self.default.connect("notify::selected", lambda *_a: self.apply_default())
        self.pending = Adw.ActionRow(title=t("router_pending"), visible=False)
        for widget in (self.switch, self.default, self.pending):
            self.main.add(widget)
        self.routes_group = Adw.PreferencesGroup(title=t("router_routes"))
        self.new_host = entry_row(t("router_host"))
        self.new_server = combo_row(t("router_server"), [])
        self.route_button = text_button(t("router_route_add"), "suggested-action")
        self.route_button.connect("clicked", lambda _b: self.add_route())
        self.access_group = Adw.PreferencesGroup(title=t("router_access"), description=t("router_access_hint"))
        self.access_kind = combo_row(t("router_access_list"), [t("router_allow"), t("router_deny")])
        self.cidr = entry_row(t("router_cidr"))
        self.access_button = text_button(t("router_access_add"))
        self.access_button.connect("clicked", lambda _b: self.add_access())
        self.progress = progress_bar()
        self.routes_group.add(self.progress)
        for group in (self.main, self.routes_group, self.access_group):
            self.add(group)
        self.form = Adw.PreferencesGroup(title=t("router_route_new"))
        for widget in (self.new_host, self.new_server, self.route_button):
            self.form.add(widget)
        self.add(self.form)
        for widget in (self.access_kind, self.cidr, self.access_button):
            self.access_group.add(widget)
        self.route_rows = []
        self.access_rows = []
        self.model.subscribe(self.refresh)
        self.model.load()

    def apply_toggle(self):
        if not self.loading:
            self.model.toggle(self.switch.get_active())

    def apply_default(self):
        servers = self.model.servers
        if not self.loading and servers:
            self.model.set_default(servers[self.default.get_selected()])

    def add_route(self):
        servers = self.model.servers
        if servers and self.model.add_route(self.new_host.get_text(), servers[self.new_server.get_selected()]):
            self.new_host.set_text("")

    def add_access(self):
        kind = ("allow", "deny")[self.access_kind.get_selected()]
        if self.model.edit_access(kind, "add", self.cidr.get_text()):
            self.cidr.set_text("")

    def ask_remove_route(self, host):
        confirm_dialog(self, t("router_route_remove_title"), t("router_route_remove_body", host=host),
                       t("router_route_remove"), lambda: self.model.remove_route(host, True))

    def refresh(self):
        busy = self.model.busy is not None
        editable = not self.model.read_only
        state = self.model.state
        servers = self.model.servers
        self.loading = True
        self.switch.set_active(state["enabled"])
        if servers != self.shown_servers:
            self.shown_servers = list(servers)
            self.default.set_model(Gtk.StringList.new(servers))
            self.new_server.set_model(Gtk.StringList.new(servers))
        if state["default"] in servers:
            self.default.set_selected(servers.index(state["default"]))
        self.loading = False
        self.pending.set_visible(bool(state["pending"]))
        self.pending.set_subtitle(", ".join(state["pending"]))
        self.route_rows = clear_rows(self.routes_group, self.route_rows)
        for host, server in state["routes"] or [(None, None)]:
            if host is None:
                widget = Adw.ActionRow(title=t("router_routes_empty"))
            else:
                widget = Adw.ActionRow(title=host, subtitle=server)
                if editable:
                    widget.add_suffix(trash_button(t("router_route_remove_name", host=host),
                                                   lambda h=host: self.ask_remove_route(h), not busy))
            self.routes_group.add(widget)
            self.route_rows.append(widget)
        self.access_rows = clear_rows(self.access_group, self.access_rows)
        for kind in ("allow", "deny"):
            for cidr in state[kind]:
                widget = Adw.ActionRow(title=cidr, subtitle=t("router_" + kind))
                if editable:
                    widget.add_suffix(trash_button(t("router_access_remove_name", cidr=cidr),
                                                   lambda k=kind, c=cidr: self.model.edit_access(k, "remove", c), not busy))
                self.access_group.add(widget)
                self.access_rows.append(widget)
        for widget in (self.switch, self.default):
            widget.set_sensitive(editable and not busy)
        self.form.set_visible(editable)
        self.access_group.set_sensitive(editable and not busy)
        self.route_button.set_sensitive(not busy)
        show_progress(self.progress, self.model)
        flush(self.model, self.toast)


class UpdateTab(Adw.PreferencesPage):
    def __init__(self, client, toast):
        super().__init__()
        self.toast = toast
        self.model = UpdateModel(client, make_runner())
        self.group = Adw.PreferencesGroup(title=t("tab_update"), description=t("update_hint"))
        self.status = Adw.ActionRow(title=t("update_status"))
        self.check_button = text_button(t("update_check"))
        self.check_button.connect("clicked", lambda _b: self.model.load())
        self.apply_button = text_button(t("update_apply"), "suggested-action")
        self.apply_button.connect("clicked", lambda _b: self.ask_apply())
        self.rollback_button = text_button(t("update_rollback"), "destructive-action")
        self.rollback_button.connect("clicked", lambda _b: self.ask_rollback())
        buttons = Gtk.Box(spacing=6, margin_top=6)
        for button in (self.check_button, self.apply_button, self.rollback_button):
            buttons.append(button)
        self.progress = progress_bar()
        for widget in (self.status, buttons, self.progress):
            self.group.add(widget)
        self.add(self.group)
        self.model.subscribe(self.refresh)
        self.model.load()

    def ask_apply(self):
        confirm_dialog(self, t("update_apply_title"), t("update_apply_body", version=self.model.info.get("latest", "")),
                       t("update_apply"), lambda: self.model.apply(True))

    def ask_rollback(self):
        confirm_dialog(self, t("update_rollback_title"), t("update_rollback_body"), t("update_rollback"),
                       lambda: self.model.rollback(True))

    def refresh(self):
        info = self.model.info
        busy = self.model.busy is not None
        editable = not self.model.read_only
        if info:
            key = "update_available" if info["available"] else "update_current"
            self.status.set_subtitle(t(key, current=info["current"], latest=info["latest"]))
        self.apply_button.set_visible(editable and bool(info.get("available")))
        self.rollback_button.set_visible(editable and bool(info.get("rollback")))
        self.check_button.set_sensitive(not busy)
        self.apply_button.set_sensitive(not busy)
        self.rollback_button.set_sensitive(not busy)
        show_progress(self.progress, self.model)
        flush(self.model, self.toast)


class DoctorTab(Adw.PreferencesPage):
    def __init__(self, client, toast):
        super().__init__()
        self.toast = toast
        self.model = DoctorModel(client, make_runner())
        self.group = Adw.PreferencesGroup(title=t("tab_doctor"), description=t("doctor_hint"))
        self.run_button = text_button(t("doctor_run"), "suggested-action")
        self.run_button.connect("clicked", lambda _b: self.model.load())
        self.summary = Adw.ActionRow(title=t("doctor_summary"), visible=False)
        self.group.add(self.run_button)
        self.group.add(self.summary)
        self.add(self.group)
        self.rows = []
        self.ran = False
        self.model.subscribe(self.refresh)
        self.model.load()

    def refresh(self):
        busy = self.model.busy is not None
        self.rows = clear_rows(self.group, self.rows)
        for check in self.model.checks:
            title = "%s - %s" % (check["server"], check["name"]) if check["server"] else check["name"]
            subtitle = check["detail"] + ("\n" + t("doctor_fix", fix=check["fix"]) if check["fix"] else "")
            widget = Adw.ActionRow(title=title, subtitle=subtitle, subtitle_lines=0)
            widget.add_prefix(Gtk.Image.new_from_icon_name(LEVEL_ICONS.get(check["level"], LEVEL_ICONS["info"])))
            self.group.add(widget)
            self.rows.append(widget)
        self.ran = self.ran or bool(self.model.checks)
        self.summary.set_visible(self.ran)
        self.summary.set_subtitle(self.model.summary())
        self.run_button.set_sensitive(not busy)
        flush(self.model, self.toast)


class NotificationsTab(Adw.PreferencesPage):
    def __init__(self, prefs):
        super().__init__()
        self.prefs = prefs
        self.loading = False
        group = Adw.PreferencesGroup(title=t("tab_notifications"), description=t("notifications_hint"))
        self.switches = {}
        for kind in NOTIFY_KINDS:
            row = Adw.SwitchRow(title=t("notify_pref_" + kind))
            row.connect("notify::active", lambda r, _p, k=kind: self.apply(k, r))
            group.add(row)
            self.switches[kind] = row
        self.add(group)
        prefs.subscribe(self.refresh)
        self.refresh()

    def apply(self, kind, row):
        if not self.loading:
            self.prefs.set(kind, row.get_active())

    def refresh(self):
        self.loading = True
        for kind, row in self.switches.items():
            row.set_active(self.prefs.enabled[kind])
        self.loading = False


class SystemPage(Adw.NavigationPage):
    """Host-wide settings: Java, remote access and devices, router, updates, diagnostics and notifications."""

    def __init__(self, client, prefs, toast):
        super().__init__(title=t("system_title"), tag="system")
        self.tabs = {
            "java": JavaTab(client, toast),
            "devices": DevicesTab(client, toast),
            "router": RouterTab(client, toast),
            "update": UpdateTab(client, toast),
            "doctor": DoctorTab(client, toast),
            "notifications": NotificationsTab(prefs),
        }
        icons = {"java": "applications-engineering-symbolic", "devices": "network-wireless-symbolic",
                 "router": "network-server-symbolic", "update": "software-update-available-symbolic",
                 "doctor": "emblem-system-symbolic", "notifications": "preferences-system-notifications-symbolic"}
        self.stack = Adw.ViewStack()
        for key, tab in self.tabs.items():
            self.stack.add_titled_with_icon(tab, key, t("tab_" + key), icons[key])
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(self.stack)
        view.add_bottom_bar(Adw.ViewSwitcherBar(stack=self.stack, reveal=True))
        self.set_child(view)
