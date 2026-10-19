import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..i18n import t  # noqa: E402
from ..models import Runner, thread_spawn  # noqa: E402


def main_dispatch(function, *args):
    GLib.idle_add(lambda: function(*args) and False)


def make_runner():
    return Runner(spawn=thread_spawn, dispatch=main_dispatch)


def icon_button(icon, label, css=None):
    button = Gtk.Button(icon_name=icon, tooltip_text=label)
    button.update_property([Gtk.AccessibleProperty.LABEL], [label])
    if css:
        button.add_css_class(css)
    return button


def flush(model, toast):
    if model.error:
        toast(model.error)
    elif model.message:
        toast(model.message)
    model.error = model.message = None


def clear_rows(group, rows):
    for widget in rows:
        group.remove(widget)
    return []


def confirm_dialog(parent, heading, body, label, on_confirm):
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", t("cancel"))
    dialog.add_response("confirm", label)
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, response: on_confirm() if response == "confirm" else None)
    dialog.present(parent)


def combo_row(title, labels):
    return Adw.ComboRow(title=title, model=Gtk.StringList.new(list(labels)))


def entry_row(title):
    return Adw.EntryRow(title=title)


def text_button(label, css=None, align=Gtk.Align.START):
    button = Gtk.Button(label=label, halign=align, valign=Gtk.Align.CENTER)
    if css:
        button.add_css_class(css)
    return button


def progress_bar():
    return Gtk.ProgressBar(visible=False, margin_top=12)


def show_progress(bar, model):
    bar.set_visible(model.busy is not None)
    bar.set_fraction(model.progress / 100)
