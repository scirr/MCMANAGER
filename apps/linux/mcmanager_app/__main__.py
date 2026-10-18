import sys

from . import i18n


def main(argv=None):
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        print("MC Manager needs PyGObject with GTK 4 and libadwaita 1.5+ (%s)." % exc, file=sys.stderr)
        print("Debian/Ubuntu: apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1", file=sys.stderr)
        return 1
    if Adw.get_minor_version() < 5 and Adw.get_major_version() == 1:
        print("libadwaita 1.5 or newer is required.", file=sys.stderr)
        return 1
    i18n.set_language(i18n.system_language())
    from .ui.application import Application
    return Application().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
