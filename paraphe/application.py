# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 melvincouwez-alt
import os

from gi.repository import Gdk, Gio, GLib, Granite, Gtk

from . import APP_ID, VERSION
from .window import Window

HERE = os.path.dirname(os.path.abspath(__file__))


def _data_dir():
    """data/ next to the package in a checkout, /usr/share/paraphe once installed."""
    for path in (os.path.join(HERE, "..", "data"), "/usr/share/paraphe"):
        if os.path.isdir(os.path.join(path, "icons")):
            return os.path.abspath(path)
    return None


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        GLib.set_application_name("Paraphe")

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Granite.init()
        display = Gdk.Display.get_default()
        data = _data_dir()
        if data:
            Gtk.IconTheme.get_for_display(display).add_search_path(os.path.join(data, "icons"))
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(HERE, "style.css"))
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        granite = Granite.Settings.get_default()
        gtk_settings = Gtk.Settings.get_default()

        def follow(*args):
            dark = granite.props.prefers_color_scheme == Granite.SettingsColorScheme.DARK
            gtk_settings.props.gtk_application_prefer_dark_theme = dark or bool(os.environ.get("PARAPHE_DEV_DARK"))
        granite.connect("notify::prefers-color-scheme", follow)
        follow()

        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._about)
        self.add_action(about)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *a: [w.close() for w in self.get_windows()])
        self.add_action(quit_action)
        accels = {
            "win.open": ["<Control>o"], "win.save": ["<Control>s"], "win.save-as": ["<Control><Shift>s"],
            "win.undo": ["<Control>z"], "win.redo": ["<Control><Shift>z", "<Control>y"],
            "win.zoom-in": ["<Control>plus", "<Control>equal", "<Control>KP_Add"],
            "win.zoom-out": ["<Control>minus", "<Control>KP_Subtract"],
            "win.zoom-fit": ["<Control>0"], "win.sidebar": ["F9"],
            "win.print": ["<Control>p"], "win.mode::pages": ["<Control><Shift>p"], "win.mode::annotate": ["<Control>e"], "win.close": ["<Control>w"],
            "app.quit": ["<Control>q"],
        }
        for action, keys in accels.items():
            self.set_accels_for_action(action, keys)

    def do_activate(self):
        window = self.get_active_window() or Window(self)
        window.present()
        self._dev_hooks(window)

    def do_open(self, files, n_files, hint):
        window = self.get_active_window()
        for file in files:
            if window is None or window.document is not None:
                window = Window(self)
            window.present()
            window.open_path(file.get_path())
        self._dev_hooks(window)

    def _about(self, *args):
        window = self.get_active_window()
        dialog = Gtk.AboutDialog(
            transient_for=window, modal=True, program_name="Paraphe", version=VERSION,
            logo_icon_name=APP_ID, comments="Annoter, remplir, signer, fusionner et découper des PDF.",
            license_type=Gtk.License.AGPL_3_0, authors=["melvincouwez-alt"],
            copyright="© 2026 melvincouwez-alt",
            website="https://github.com/melvincouwez-alt/paraphe")
        dialog.add_credit_section("Bâti sur", ["PyMuPDF (Artifex, AGPL)", "pyHanko (Matthias Valvekens, MIT)",
                                               "uharfbuzz (HarfBuzz, Apache-2.0)", "fontTools (MIT)",
                                               "GTK et Granite (elementary)"])
        dialog.add_credit_section("Icône", ["Courbe du symbole PDF tirée des icônes elementary (GPL-3.0)"])
        dialog.present()

    # Development: PARAPHE_DEV_SCRIPT runs a Python file with the window in
    # scope, PARAPHE_DEV_CAPTURE saves the window as PNG, then the app quits.
    def _dev_hooks(self, window):
        script = os.environ.get("PARAPHE_DEV_SCRIPT")
        capture = os.environ.get("PARAPHE_DEV_CAPTURE")
        if not (script or capture) or getattr(self, "_dev_done", False):
            return
        self._dev_done = True

        def run():
            if script:
                scope = {"window": window, "app": self, "GLib": GLib, "Gtk": Gtk}
                with open(script) as f:
                    exec(compile(f.read(), script, "exec"), scope)
                step = scope.get("steps")
                if step:
                    GLib.timeout_add(600, _steps, iter(step))
                    return False
            GLib.timeout_add(600, finish)
            return False

        def _steps(it):
            try:
                next(it)()
            except StopIteration:
                GLib.timeout_add(600, finish)
                return False
            return True

        def finish():
            if capture:
                save_capture(window, capture)
            if not os.environ.get("PARAPHE_DEV_STAY"):
                self.quit()
            return False
        GLib.timeout_add(1200, run)


def save_capture(widget, path):
    paintable = Gtk.WidgetPaintable.new(widget)
    width, height = widget.get_width(), widget.get_height()
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        return
    texture = widget.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(path)
