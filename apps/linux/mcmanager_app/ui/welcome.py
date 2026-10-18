import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..i18n import t  # noqa: E402


class WelcomePage(Adw.NavigationPage):
    """First launch: this machine, or a remote server."""

    def __init__(self, model, on_connected, on_remote):
        super().__init__(title=t("app_title"), tag="welcome")
        self.model, self.on_connected = model, on_connected
        page = Adw.StatusPage(icon_name="io.github.scirr.MCManager", title=t("welcome_title"),
                              description=t("welcome_text"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        local = Gtk.Button(label=t("this_machine"))
        local.add_css_class("suggested-action")
        local.add_css_class("pill")
        local.connect("clicked", self.choose_local)
        remote = Gtk.Button(label=t("remote_server"))
        remote.add_css_class("pill")
        remote.connect("clicked", lambda _b: on_remote())
        box.append(local)
        box.append(remote)
        page.set_child(box)
        self.error_label = Gtk.Label(wrap=True, css_classes=["error"], visible=False)
        box.append(self.error_label)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(page)
        self.set_child(view)

    def choose_local(self, _button):
        client = self.model.use_local()
        if client is None:
            self.error_label.set_label(self.model.error or "")
            self.error_label.set_visible(True)
            return
        self.on_connected("local", None)


class RemotePage(Adw.NavigationPage):
    """Address, fingerprint confirmation and pairing code."""

    def __init__(self, model, on_connected):
        super().__init__(title=t("remote_title"), tag="remote")
        self.model, self.on_connected = model, on_connected
        model.subscribe(self.refresh)
        group = Adw.PreferencesGroup(title=t("remote_title"), description=t("remote_text"))
        self.address = Adw.EntryRow(title=t("address"))
        self.address.connect("apply", self.look_up)
        self.address.set_show_apply_button(True)
        self.fingerprint = Adw.ActionRow(title=t("fingerprint_confirm"), visible=False, subtitle_selectable=True)
        self.code = Adw.EntryRow(title=t("pair_code"), visible=False)
        self.device = Adw.EntryRow(title=t("device_name"), visible=False, text="MC Manager")
        for row in (self.address, self.fingerprint, self.code, self.device):
            group.add(row)
        self.pair = Gtk.Button(label=t("pair"), halign=Gtk.Align.CENTER, visible=False)
        self.pair.add_css_class("suggested-action")
        self.pair.add_css_class("pill")
        self.pair.connect("clicked", self.submit)
        self.spinner = Gtk.Spinner(visible=False)
        self.error_label = Gtk.Label(wrap=True, visible=False, css_classes=["error"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=24,
                      margin_start=12, margin_end=12)
        for widget in (group, self.pair, self.spinner, self.error_label):
            box.append(widget)
        clamp = Adw.Clamp(maximum_size=480, child=box)
        scroller = Gtk.ScrolledWindow(child=clamp)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(scroller)
        self.set_child(view)

    def look_up(self, _row):
        self.model.fetch_fingerprint(self.address.get_text().strip())

    def submit(self, _button):
        self.model.submit_pairing(self.address.get_text().strip(), self.code.get_text(), self.device.get_text() or "MC Manager")

    def refresh(self):
        self.spinner.set_visible(self.model.busy)
        self.spinner.set_spinning(self.model.busy)
        self.error_label.set_label(self.model.error or "")
        self.error_label.set_visible(bool(self.model.error))
        shown = bool(self.model.fingerprint)
        self.fingerprint.set_subtitle(self.model.fingerprint or "")
        for widget in (self.fingerprint, self.code, self.device, self.pair):
            widget.set_visible(shown)
        if self.model.client is not None:
            self.on_connected("remote", "default")
