# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 melvincouwez-alt
"""The empty window: open or merge files, or pick a recent one."""

import os

from gi.repository import Gio, GLib, Gtk

from . import APP_ID

RECENT_COUNT = 6


class Welcome(Gtk.ScrolledWindow):
    __gtype_name__ = "ParapheWelcome"

    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.window = window
        self.add_css_class("welcome")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER,
                      valign=Gtk.Align.CENTER, margin_top=48, margin_bottom=48, margin_start=24, margin_end=24)
        box.set_size_request(440, -1)

        icon = Gtk.Image(icon_name=APP_ID, pixel_size=96)
        box.append(icon)
        title = Gtk.Label(label="Paraphe")
        title.add_css_class("welcome-title")
        box.append(title)
        subtitle = Gtk.Label(label="Annotez, remplissez, signez, fusionnez et découpez vos PDF.",
                             wrap=True, justify=Gtk.Justification.CENTER)
        subtitle.add_css_class("dim-label")
        box.append(subtitle)

        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=16)
        open_button = Gtk.Button(label="Ouvrir un PDF…", action_name="win.open")
        open_button.add_css_class("suggested-action")
        open_button.add_css_class("pill")
        merge = Gtk.Button(label="Fusionner des PDF…", action_name="win.merge")
        merge.add_css_class("pill")
        buttons.append(open_button)
        buttons.append(merge)
        box.append(buttons)
        hint = Gtk.Label(label="Vous pouvez aussi glisser un fichier dans la fenêtre.")
        hint.add_css_class("dim-label")
        hint.add_css_class("small-label")
        box.append(hint)

        self.recent_title = Gtk.Label(label="Récents", xalign=0, margin_top=28)
        self.recent_title.add_css_class("section-title")
        box.append(self.recent_title)
        self.recent = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.recent.add_css_class("recent-list")
        self.recent.connect("row-activated", self._on_row)
        box.append(self.recent)
        self.set_child(box)
        self.connect("map", lambda w: self.refresh())

    def refresh(self):
        self.recent.remove_all()
        items = []
        for info in Gtk.RecentManager.get_default().get_items():
            if info.get_mime_type() != "application/pdf" or not info.exists():
                continue
            path = GLib.filename_from_uri(info.get_uri())[0]
            items.append((info.get_modified().to_unix(), path))
        items.sort(reverse=True)
        for _, path in items[:RECENT_COUNT]:
            self.recent.append(self._row(path))
        self.recent_title.set_visible(bool(items))
        self.recent.set_visible(bool(items))

    def _row(self, path):
        row = Gtk.ListBoxRow()
        row.path = path
        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        box.append(Gtk.Image(gicon=Gio.content_type_get_icon("application/pdf"), pixel_size=32))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        name = Gtk.Label(label=os.path.basename(path), xalign=0, ellipsize=3)
        folder = Gtk.Label(label=os.path.dirname(path).replace(GLib.get_home_dir(), "~", 1),
                           xalign=0, ellipsize=1)
        folder.add_css_class("dim-label")
        folder.add_css_class("small-label")
        text.append(name)
        text.append(folder)
        box.append(text)
        row.set_child(box)
        return row

    def _on_row(self, listbox, row):
        self.window.open_path(row.path)
