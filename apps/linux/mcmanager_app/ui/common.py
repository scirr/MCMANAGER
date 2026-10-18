import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

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
