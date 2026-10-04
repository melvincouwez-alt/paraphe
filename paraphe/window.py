# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 melvincouwez-alt
"""The main window: header bar, tool bar, page sidebar and viewer."""

import os

import pymupdf
from gi.repository import Gdk, Gio, GLib, GObject, Granite, Gtk

from . import dialogs
from .document import Document
from .sidebar import PageSidebar
from .signatures import SignatureMenu
from .organizer import Organizer
from .viewer import Viewer
from .welcome import Welcome

TOOLS = (
    ("select", "paraphe-select-symbolic", "Sélectionner, remplir, suivre les liens"),
    ("highlight", "paraphe-highlight-symbolic", "Surligner"),
    ("underline", "format-text-underline-symbolic", "Souligner"),
    ("strike", "format-text-strikethrough-symbolic", "Barrer"),
    ("text", "paraphe-text-symbolic", "Ajouter du texte"),
    ("note", "paraphe-note-symbolic", "Ajouter une note"),
    ("draw", "paraphe-draw-symbolic", "Dessiner à main levée"),
    ("rect", "paraphe-rect-symbolic", "Encadrer"),
)

PALETTE = (
    (1.0, 0.82, 0.25), (0.55, 0.82, 0.35), (0.35, 0.62, 0.95),
    (0.93, 0.45, 0.62), (0.85, 0.2, 0.22), (0.12, 0.14, 0.2),
)

# Sizes offered for free text, in points.
TEXT_SIZES = (8, 10, 11, 14, 18, 24)

PDF_FILTER = Gtk.FileFilter(name="Documents PDF")
PDF_FILTER.add_mime_type("application/pdf")
PDF_FILTER.add_suffix("pdf")


def _filters(*filters):
    store = Gio.ListStore.new(Gtk.FileFilter)
    for f in filters:
        store.append(f)
    return store


class Window(Gtk.ApplicationWindow):
    __gtype_name__ = "ParapheWindow"

    def __init__(self, app):
        super().__init__(application=app, title="Paraphe", default_width=1180, default_height=820)
        self.add_css_class("paraphe")
        self.document = None
        self._doc_handlers = []
        self._pending_signature = None
        self._build()
        self._actions()
        self._update_state()

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_window_drop)
        self.add_controller(drop)
        self.connect("close-request", self._on_close_request)

        granite = Granite.Settings.get_default()
        granite.connect("notify::prefers-color-scheme", lambda *a: self._follow_scheme())
        Gtk.Settings.get_default().connect("notify::gtk-application-prefer-dark-theme",
                                           lambda *a: self._follow_scheme())
        self._follow_scheme()

    def _follow_scheme(self):
        if Gtk.Settings.get_default().props.gtk_application_prefer_dark_theme:
            self.add_css_class("dark")
        else:
            self.remove_css_class("dark")

    # Layout

    def _build(self):
        header = Gtk.HeaderBar()
        header.add_css_class("paraphe-header")
        self.set_titlebar(header)

        self.sidebar_button = Gtk.ToggleButton(icon_name="view-sidebar-start-symbolic",
                                               tooltip_text="Pages (F9)", active=True,
                                               valign=Gtk.Align.CENTER)
        self.sidebar_button.add_css_class("header-toggle")
        header.pack_start(self.sidebar_button)
        header.pack_start(Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Ouvrir (Ctrl+O)",
                                     action_name="win.open"))
        self.mode_switch = Gtk.Box(valign=Gtk.Align.CENTER)
        self.mode_switch.add_css_class("linked")
        self.mode_switch.add_css_class("mode-switch")
        for mode, label, tip in (("annotate", "Annoter", "Annoter, remplir, signer"),
                                 ("pages", "Pages", "Réordonner, fusionner, découper (Ctrl+Maj+P)")):
            button = Gtk.ToggleButton(label=label, tooltip_text=tip, action_name="win.mode",
                                      action_target=GLib.Variant("s", mode))
            self.mode_switch.append(button)
        header.pack_start(self.mode_switch)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.title_label = Gtk.Label(label="Paraphe", ellipsize=3, max_width_chars=48)
        self.title_label.add_css_class("title")
        self.subtitle_label = Gtk.Label(visible=False)
        self.subtitle_label.add_css_class("subtitle")
        titles.append(self.title_label)
        titles.append(self.subtitle_label)
        header.set_title_widget(titles)

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Imprimer…", "win.print")
        section.append("Enregistrer sous…", "win.save-as")
        section.append("Enregistrer une copie aplatie…", "win.save-flat")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Fusionner des PDF…", "win.merge")
        section.append("Insérer un PDF…", "win.insert-pdf")
        section.append("Découper le document…", "win.split")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Ouvrir avec une autre application", "win.open-with")
        section.append("À propos de Paraphe", "app.about")
        menu.append_section(None, section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Menu", primary=True))
        self.save_button = Gtk.Button(label="Enregistrer", tooltip_text="Enregistrer (Ctrl+S)",
                                      action_name="win.save", valign=Gtk.Align.CENTER)
        self.save_button.add_css_class("save-button")
        header.pack_end(self.save_button)
        self.print_button = Gtk.Button(icon_name="printer-symbolic", tooltip_text="Imprimer (Ctrl+P)",
                                       action_name="win.print", valign=Gtk.Align.CENTER)
        header.pack_end(self.print_button)

        # Viewer and the floating controls over it
        self.viewer = Viewer()
        self.viewer.set_hexpand(True)
        self.viewer.set_vexpand(True)
        self.viewer.connect("current-page", self._on_current_page)
        self.viewer.connect("zoom-changed", lambda v, z: self.zoom_button.set_label(f"{round(z * 100)} %"))
        self.viewer.connect("zone-drawn", self._on_zone_drawn)
        self.viewer.connect("notify-user", lambda v, text: self.toast(text))
        self.viewer.connect("selection-changed", lambda v: self._update_state())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_viewer_key)
        self.viewer.add_controller(keys)

        self.overlay = Gtk.Overlay(child=self.viewer)
        self.palette = self._build_palette()
        self.overlay.add_overlay(self.palette)

        self.sidebar = PageSidebar(self._page_menu())
        self.sidebar.set_size_request(184, -1)
        self.sidebar.connect("page-activated", lambda s, i: self.viewer.scroll_to_page(i))
        self.sidebar.connect("files-dropped", lambda s, paths, i: self.insert_files(paths, i))
        self.sidebar_button.bind_property("active", self.sidebar, "visible",
                                          GObject.BindingFlags.SYNC_CREATE)
        paned = Gtk.Paned(start_child=self.sidebar, end_child=self.overlay,
                          shrink_start_child=False, resize_start_child=False, position=196)
        paned.add_css_class("paraphe-paned")

        self.organizer = Organizer(self._build_page_actions())
        self.organizer.connect("open-page", self._on_organizer_open)
        self.organizer.connect("files-dropped", lambda o, paths, i: self.insert_files(paths, i))
        self.organizer.connect("selection-changed", lambda o: self._update_page_actions())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_organizer_key)
        self.organizer.add_controller(keys)
        self.modes = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150)
        self.modes.add_named(paned, "annotate")
        self.modes.add_named(self.organizer, "pages")

        self.welcome = Welcome(self)
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.Overlay(child=self.welcome), "welcome")
        self.stack.add_named(self.modes, "document")
        self.set_child(self.stack)

    def _build_palette(self):
        """The floating tool bar: tools, colours of the current tool, signature, undo."""
        bar = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=18)
        bar.add_css_class("palette")
        self.tool_buttons = {}
        for name, icon, tip in TOOLS:
            button = Gtk.ToggleButton(icon_name=icon, tooltip_text=tip, action_name="win.tool",
                                      action_target=GLib.Variant("s", name))
            button.add_css_class("tool")
            bar.append(button)
            self.tool_buttons[name] = button

        self.signature_menu = SignatureMenu()
        self.signature_menu.add_css_class("tool")
        self.signature_menu.connect("chosen", self._on_signature_chosen)
        self.signature_menu.connect("certificate", self._on_certificate)
        bar.append(self.signature_menu)

        self.colour_separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        bar.append(self.colour_separator)
        self.colour_box = Gtk.Box(spacing=2)
        self.colour_buttons = []
        for colour in PALETTE:
            area = Gtk.DrawingArea(content_width=18, content_height=18)
            area.set_draw_func(self._draw_dot, colour)
            button = Gtk.Button(child=area, tooltip_text="Couleur")
            button.add_css_class("dot")
            button.connect("clicked", self._on_colour, colour)
            self.colour_box.append(button)
            self.colour_buttons.append((button, area, colour))
        bar.append(self.colour_box)
        sizes = Gio.Menu()
        for size in TEXT_SIZES:
            sizes.append(f"{size} pt", f"win.text-size::{size}")
        # A custom child, not a label: a labelled menu button adds an arrow.
        self.size_label = Gtk.Label(label="11 pt")
        self.size_button = Gtk.MenuButton(child=self.size_label, menu_model=sizes,
                                          tooltip_text="Taille du texte", direction=Gtk.ArrowType.UP)
        self.size_button.add_css_class("tool")
        self.size_button.add_css_class("text-size")
        bar.append(self.size_button)

        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        for icon, tip, action in (("edit-undo-symbolic", "Annuler (Ctrl+Z)", "win.undo"),
                                  ("edit-redo-symbolic", "Rétablir (Ctrl+Maj+Z)", "win.redo")):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip, action_name=action)
            button.add_css_class("tool")
            bar.append(button)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        bar.append(self._build_zoom())
        return bar

    def _build_zoom(self):
        box = Gtk.Box()
        out = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text="Zoom arrière (Ctrl+−)",
                         action_name="win.zoom-out")
        self.zoom_button = Gtk.Button(label="100 %", tooltip_text="Ajuster à la largeur (Ctrl+0)",
                                      action_name="win.zoom-fit")
        self.zoom_button.add_css_class("zoom-label")
        zin = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text="Zoom avant (Ctrl++)",
                         action_name="win.zoom-in")
        for button in (out, self.zoom_button, zin):
            button.add_css_class("tool")
            box.append(button)
        return box

    def _page_menu(self):
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Pivoter à gauche", "win.rotate-left")
        section.append("Pivoter à droite", "win.rotate-right")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Extraire…", "win.extract-pages")
        section.append("Insérer un PDF après…", "win.insert-pdf")
        section.append("Découper le document…", "win.split")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Supprimer", "win.delete-pages")
        menu.append_section(None, section)
        return menu

    def _draw_dot(self, area, cr, width, height, colour):
        import math
        cr.arc(width / 2, height / 2, min(width, height) / 2 - 1, 0, 2 * math.pi)
        cr.set_source_rgb(*colour)
        cr.fill_preserve()
        cr.set_source_rgba(0, 0, 0, 0.2)
        cr.set_line_width(1)
        cr.stroke()

    def _refresh_colours(self):
        tool = self.viewer.tool
        current = self.viewer.colours.get(tool)
        shown = current is not None
        self.colour_box.set_visible(shown)
        self.colour_separator.set_visible(shown)
        self.size_button.set_visible(tool == "text")
        for button, area, colour in self.colour_buttons:
            if colour == current:
                button.add_css_class("selected")
            else:
                button.remove_css_class("selected")

    def _on_colour(self, button, colour):
        if self.viewer.tool in self.viewer.colours:
            self.viewer.colours[self.viewer.tool] = colour
            self._refresh_colours()

    # Actions

    def _actions(self):
        simple = {
            "open": self.choose_open, "save": self.save, "save-as": self.save_as,
            "save-flat": self.save_flat, "merge": self.choose_merge, "insert-pdf": self.choose_insert,
            "split": self.split, "extract-pages": self.extract_pages,
            "rotate-left": lambda: self.rotate(-90), "rotate-right": lambda: self.rotate(90),
            "delete-pages": self.delete_pages, "undo": self.undo, "redo": self.redo,
            "zoom-in": lambda: self.viewer.set_zoom(self.viewer.zoom * 1.2),
            "zoom-out": lambda: self.viewer.set_zoom(self.viewer.zoom / 1.2),
            "zoom-fit": lambda: self.viewer.set_zoom(0, fit=True),
            "zoom-100": lambda: self.viewer.set_zoom(1.0),
            "sidebar": lambda: self.sidebar_button.set_active(not self.sidebar_button.get_active()),
            "open-with": self.open_with, "close": self.close, "print": self.print_document,
            "duplicate-pages": self.duplicate_pages, "select-all-pages": lambda: self.organizer.select_all(),
        }
        self.actions = {}
        for name, callback in simple.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda a, p, c=callback: c())
            self.add_action(action)
            self.actions[name] = action
        tool = Gio.SimpleAction.new_stateful("tool", GLib.VariantType.new("s"), GLib.Variant("s", "select"))
        tool.connect("change-state", self._on_tool)
        self.add_action(tool)
        self.actions["tool"] = tool
        size = Gio.SimpleAction.new_stateful("text-size", GLib.VariantType.new("s"), GLib.Variant("s", "11"))
        size.connect("change-state", self._on_text_size)
        self.add_action(size)
        self.actions["text-size"] = size
        mode = Gio.SimpleAction.new_stateful("mode", GLib.VariantType.new("s"), GLib.Variant("s", "annotate"))
        mode.connect("change-state", self._on_mode)
        self.add_action(mode)
        self.actions["mode"] = mode

    def _on_tool(self, action, value):
        action.set_state(value)
        name = value.get_string()
        if name != "signature":
            self.viewer.signature = None
        self.viewer.set_tool(name)
        self.signature_menu.set_active_look(name == "signature")
        self._refresh_colours()

    def _on_text_size(self, action, value):
        action.set_state(value)
        self.viewer.text_size = int(value.get_string())
        self.size_label.set_label(f"{value.get_string()} pt")

    def set_tool(self, name):
        self.actions["tool"].change_state(GLib.Variant("s", name))

    def _update_state(self):
        has_doc = self.document is not None
        for name in ("print", "save", "save-as", "save-flat", "insert-pdf", "split", "extract-pages",
                     "rotate-left", "rotate-right", "delete-pages", "duplicate-pages", "select-all-pages", "mode", "zoom-in", "zoom-out",
                     "zoom-fit", "zoom-100", "sidebar", "tool", "open-with"):
            self.actions[name].set_enabled(has_doc)
        self.actions["undo"].set_enabled(has_doc and self.document.can_undo)
        self.actions["redo"].set_enabled(has_doc and self.document.can_redo)
        self.save_button.set_visible(has_doc)
        self.print_button.set_visible(has_doc)
        if not has_doc:
            self.title_label.set_label("Paraphe")
            self.subtitle_label.set_visible(False)
            self.set_title("Paraphe")
            return
        # The save button only calls for attention when there is something to save.
        if self.document.modified:
            self.save_button.add_css_class("suggested-action")
        else:
            self.save_button.remove_css_class("suggested-action")
        self.title_label.set_label(self.document.title)
        self._update_subtitle()
        self.set_title(f"{self.document.title} – Paraphe")

    def _update_subtitle(self):
        if not self.document:
            return
        count = self.document.page_count
        if self._in_pages_mode() or count == 1:
            text = f"{count} page{'s' if count > 1 else ''}"
        else:
            text = f"Page {self.viewer.current_page + 1} sur {count}"
        if self.document.modified:
            text += " · modifié"
        self.subtitle_label.set_label(text)
        self.subtitle_label.set_visible(True)

    # Documents

    def set_document(self, document):
        if self.document:
            for handler in self._doc_handlers:
                self.document.disconnect(handler)
            self.document.close()
        self.document = document
        self._doc_handlers = [
            document.connect("state-changed", lambda d: self._update_state()),
            document.connect("structure-changed", lambda d: self._on_current_page(self.viewer, self.viewer.current_page)),
        ]
        self.viewer.set_document(document)
        self.sidebar.set_document(document)
        self.organizer.set_document(document)
        document.connect("structure-changed", lambda d: self._update_page_actions())
        self.stack.set_visible_child_name("document")
        self.set_mode("annotate")
        self.set_tool("select")
        self._on_current_page(self.viewer, 0)
        self._update_state()

    def open_path(self, path):
        try:
            needs = Document.needs_password(path)
        except Exception as error:
            self.error(f"Impossible d'ouvrir « {os.path.basename(path)} »", str(error))
            return
        if needs:
            dialog = dialogs.PasswordDialog(self, os.path.basename(path))
            dialog.connect("password", lambda d, pw: self._open_with_password(path, pw))
            dialog.present()
        else:
            self._open_with_password(path, None)

    def _open_with_password(self, path, password):
        try:
            document = Document.open(path, password)
        except PermissionError:
            self.error("Mot de passe incorrect", f"« {os.path.basename(path)} » n'a pas été ouvert.")
            return
        except Exception as error:
            self.error(f"Impossible d'ouvrir « {os.path.basename(path)} »", str(error))
            return
        self.set_document(document)
        Gtk.RecentManager.get_default().add_item(Gio.File.new_for_path(path).get_uri())

    def _target_window(self):
        """This window when empty, else a new one."""
        if self.document is None:
            return self
        window = Window(self.get_application())
        window.present()
        return window

    def choose_open(self):
        dialog = Gtk.FileDialog(title="Ouvrir un PDF", filters=_filters(PDF_FILTER))
        self._set_initial_folder(dialog)

        def done(dialog, result):
            try:
                files = dialog.open_multiple_finish(result)
            except GLib.Error:
                return
            for i in range(files.get_n_items()):
                self._target_window().open_path(files.get_item(i).get_path())
        dialog.open_multiple(self, None, done)

    def _set_initial_folder(self, dialog):
        if self.document and self.document.path:
            dialog.set_initial_folder(Gio.File.new_for_path(os.path.dirname(self.document.path)))

    def choose_merge(self):
        dialog = Gtk.FileDialog(title="Fichiers à fusionner, dans l'ordre", filters=_filters(PDF_FILTER))
        self._set_initial_folder(dialog)

        def done(dialog, result):
            try:
                files = dialog.open_multiple_finish(result)
            except GLib.Error:
                return
            paths = sorted(files.get_item(i).get_path() for i in range(files.get_n_items()))
            try:
                merged = Document.merge(paths)
            except Exception as error:
                self.error("Fusion impossible", str(error))
                return
            window = self._target_window()
            window.set_document(merged)
            window.set_mode("pages")
            window.toast(f"{len(paths)} fichiers fusionnés : réordonnez les pages puis enregistrez")
        dialog.open_multiple(self, None, done)

    def choose_insert(self):
        dialog = Gtk.FileDialog(title="Insérer un PDF", filters=_filters(PDF_FILTER))
        self._set_initial_folder(dialog)
        if self._in_pages_mode():
            selected = self.organizer.selected_pages()
            index = selected[-1] + 1 if selected else self.document.page_count
        else:
            selected = self.sidebar.selected_pages()
            index = (selected[-1] if selected else self.viewer.current_page) + 1

        def done(dialog, result):
            try:
                files = dialog.open_multiple_finish(result)
            except GLib.Error:
                return
            self.insert_files([files.get_item(i).get_path() for i in range(files.get_n_items())], index)
        dialog.open_multiple(self, None, done)

    def insert_files(self, paths, index):
        def change(doc):
            position = index
            for path in paths:
                with pymupdf.open(path) as src:
                    if not src.is_pdf:
                        src = pymupdf.open("pdf", src.convert_to_pdf())
                    doc.insert_pdf(src, start_at=position)
                    position += src.page_count
            return position - index
        try:
            added = self.document.edit(change)
        except Exception as error:
            self.error("Insertion impossible", str(error))
            return
        self.viewer.scroll_to_page(index)
        self.toast(f"{added} page{'s' if added > 1 else ''} insérée{'s' if added > 1 else ''}")

    def _on_window_drop(self, target, files, x, y):
        paths = [f.get_path() for f in files.get_files() if f.get_path()]
        for path in paths:
            self._target_window().open_path(path)
        return bool(paths)

    # Saving

    def save(self, then=None):
        if not self.document:
            return
        self.viewer.commit_fields()
        if not self.document.path:
            self.save_as(then)
            return
        doc = self.document.doc
        if self.document.has_signatures() and not (doc.name == self.document.path and doc.can_save_incrementally()):
            self._confirm_break_signatures(then)
            return
        self._write(self.document.path, then)

    def _write(self, path, then=None):
        try:
            self.document.save(path)
        except Exception as error:
            self.error("Enregistrement impossible", str(error))
            return
        Gtk.RecentManager.get_default().add_item(Gio.File.new_for_path(path).get_uri())
        self.toast("Document enregistré")
        if then:
            then()

    def _confirm_break_signatures(self, then):
        dialog = Granite.MessageDialog.with_image_from_icon_name(
            "Ce document porte une signature numérique",
            "L'enregistrer à la place de l'original rendra cette signature invalide. "
            "Vous pouvez plutôt enregistrer une copie.",
            "dialog-warning", Gtk.ButtonsType.NONE)
        dialog.add_button("Annuler", Gtk.ResponseType.CANCEL)
        dialog.add_button("Remplacer quand même", 1).add_css_class("destructive-action")
        dialog.add_button("Enregistrer une copie…", Gtk.ResponseType.ACCEPT).add_css_class("suggested-action")
        dialog.set_transient_for(self)
        dialog.set_modal(True)

        def response(dialog, code):
            dialog.destroy()
            if code == 1:
                self._write(self.document.path, then)
            elif code == Gtk.ResponseType.ACCEPT:
                self.save_as(then)
        dialog.connect("response", response)
        dialog.present()

    def _save_dialog(self, title, name, done):
        dialog = Gtk.FileDialog(title=title, initial_name=name, filters=_filters(PDF_FILTER))
        self._set_initial_folder(dialog)

        def finish(dialog, result):
            try:
                path = dialog.save_finish(result).get_path()
            except GLib.Error:
                return
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            done(path)
        dialog.save(self, None, finish)

    def _stem(self):
        return os.path.splitext(self.document.title)[0] if self.document.path else "document"

    def save_as(self, then=None):
        self.viewer.commit_fields()
        self._save_dialog("Enregistrer sous", f"{self._stem()}.pdf", lambda path: self._write(path, then))

    def save_flat(self):
        self.viewer.commit_fields()

        def done(path):
            try:
                self.document.save_copy(path, flatten=True)
            except Exception as error:
                self.error("Enregistrement impossible", str(error))
                return
            self.toast("Copie aplatie enregistrée : annotations et champs y sont figés")
        self._save_dialog("Enregistrer une copie aplatie", f"{self._stem()}-aplati.pdf", done)

    def extract_pages(self):
        pages = self._target_pages()
        self.viewer.commit_fields()

        def done(path):
            try:
                self.document.save_copy(path, pages=pages)
            except Exception as error:
                self.error("Extraction impossible", str(error))
                return
            self.toast(f"{len(pages)} page{'s' if len(pages) > 1 else ''} extraite{'s' if len(pages) > 1 else ''}",
                       "Ouvrir", lambda: self._target_window().open_path(path))
        label = f"{pages[0] + 1}" if len(pages) == 1 else f"{pages[0] + 1}-{pages[-1] + 1}"
        self._save_dialog("Extraire les pages", f"{self._stem()}-p{label}.pdf", done)

    def split(self):
        self.viewer.commit_fields()
        selected = self.organizer.selected_pages() if self._in_pages_mode() else self.sidebar.selected_pages()
        dialog = dialogs.SplitDialog(self, self.document, selected)

        def run(dialog, ranges, folder, stem):
            try:
                paths = self.document.split(ranges, folder, stem)
            except Exception as error:
                self.error("Découpage impossible", str(error))
                return
            folder_file = Gio.File.new_for_path(paths[0])
            self.toast(f"{len(paths)} fichiers créés", "Afficher",
                       lambda: Gtk.FileLauncher.new(folder_file).open_containing_folder(self, None, None))
        dialog.connect("split", run)
        dialog.present()

    def print_document(self, export=None):
        """Print the document as shown, annotations, fields and signatures included.

        export: write a PDF there instead of asking for a printer (tests)."""
        self.viewer.commit_fields()
        # Print from a frozen copy: the document may change while the dialog is open.
        doc = pymupdf.open("pdf", self.document.doc.tobytes(garbage=0))
        operation = Gtk.PrintOperation(n_pages=doc.page_count, job_name=self.document.title,
                                       unit=Gtk.Unit.POINTS, embed_page_setup=True)
        operation.connect("request-page-setup", self._on_print_setup, doc)
        operation.connect("draw-page", self._on_print_page, doc)
        operation.connect("done", lambda op, result: doc.close())
        if export:
            operation.set_export_filename(export)
            action = Gtk.PrintOperationAction.EXPORT
        else:
            action = Gtk.PrintOperationAction.PRINT_DIALOG
        try:
            operation.run(action, self)
        except GLib.Error as error:
            self.error("Impression impossible", error.message)

    def _on_print_setup(self, operation, context, index, setup, doc):
        rect = doc[index].rect
        setup.set_orientation(Gtk.PageOrientation.LANDSCAPE if rect.width > rect.height
                              else Gtk.PageOrientation.PORTRAIT)

    def _on_print_page(self, operation, context, index, doc):
        import io
        import cairo
        page = doc[index]
        # Raster at the printer resolution, capped: 300 dpi is sharp on paper.
        dpi = min(max(context.get_dpi_x(), 150), 300)
        pixmap = page.get_pixmap(dpi=dpi, alpha=False, annots=True)
        image = cairo.ImageSurface.create_from_png(io.BytesIO(pixmap.tobytes("png")))
        width, height = context.get_width(), context.get_height()
        scale = min(width / page.rect.width, height / page.rect.height)
        cr = context.get_cairo_context()
        cr.translate((width - page.rect.width * scale) / 2, (height - page.rect.height * scale) / 2)
        cr.scale(scale * 72 / dpi, scale * 72 / dpi)
        cr.set_source_surface(image, 0, 0)
        cr.paint()

    def open_with(self):
        if self.document and self.document.path:
            Gtk.FileLauncher.new(Gio.File.new_for_path(self.document.path)).launch(self, None, None)

    # Pages

    def _in_pages_mode(self):
        return self.actions["mode"].get_state().get_string() == "pages"

    def _target_pages(self):
        selected = self.organizer.selected_pages() if self._in_pages_mode() else self.sidebar.selected_pages()
        return selected or [self.viewer.current_page]

    def duplicate_pages(self):
        pages = self._target_pages()

        def change(doc):
            # Copies go right after the last selected page, in order.
            at = pages[-1] + 1
            for offset, index in enumerate(pages):
                doc.fullcopy_page(index, at + offset)
        self.document.edit(change)
        self.toast(f"{len(pages)} page{'s' if len(pages) > 1 else ''} dupliquée{'s' if len(pages) > 1 else ''}")

    # Pages mode

    def _build_page_actions(self):
        bar = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=18)
        bar.add_css_class("palette")
        self.selection_label = Gtk.Label(margin_start=10, margin_end=6)
        self.selection_label.add_css_class("selection-label")
        bar.append(self.selection_label)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        for icon, label, action in (("list-add-symbolic", "Ajouter un PDF", "win.insert-pdf"),
                                    ("edit-cut-symbolic", "Découper", "win.split"),
                                    ("document-export-symbolic", "Extraire", "win.extract-pages"),
                                    ("edit-copy-symbolic", "Dupliquer", "win.duplicate-pages")):
            button = Gtk.Button(action_name=action, tooltip_text=label)
            inner = Gtk.Box(spacing=6)
            inner.append(Gtk.Image(icon_name=icon))
            inner.append(Gtk.Label(label=label))
            button.set_child(inner)
            button.add_css_class("tool")
            button.add_css_class("labelled")
            bar.append(button)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        for icon, tip, action in (("object-rotate-left-symbolic", "Pivoter à gauche", "win.rotate-left"),
                                  ("object-rotate-right-symbolic", "Pivoter à droite", "win.rotate-right"),
                                  ("edit-delete-symbolic", "Supprimer (Suppr)", "win.delete-pages")):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip, action_name=action)
            button.add_css_class("tool")
            bar.append(button)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        for icon, tip, action in (("edit-undo-symbolic", "Annuler (Ctrl+Z)", "win.undo"),
                                  ("edit-redo-symbolic", "Rétablir (Ctrl+Maj+Z)", "win.redo")):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip, action_name=action)
            button.add_css_class("tool")
            bar.append(button)
        return bar

    def _update_page_actions(self):
        if not self.document:
            return
        count = len(self.organizer.selected_pages())
        total = self.document.page_count
        if count:
            self.selection_label.set_label(f"{count} sur {total} sélectionnée{'s' if count > 1 else ''}")
        else:
            self.selection_label.set_label(f"{total} page{'s' if total > 1 else ''}")

    def _on_mode(self, action, value):
        action.set_state(value)
        mode = value.get_string()
        self.modes.set_visible_child_name(mode)
        self.sidebar_button.set_visible(mode == "annotate")
        if mode == "pages":
            self.viewer.commit_fields()
            self._update_page_actions()
        self._update_subtitle()

    def set_mode(self, mode):
        self.actions["mode"].change_state(GLib.Variant("s", mode))

    def _on_organizer_open(self, organizer, index):
        self.set_mode("annotate")
        GLib.idle_add(lambda: self.viewer.scroll_to_page(index) and False)

    def _on_organizer_key(self, controller, keyval, code, state):
        if keyval == Gdk.KEY_Delete and self.organizer.selected_pages():
            self.delete_pages()
            return True
        return False

    def rotate(self, degrees):
        pages = self._target_pages()

        def change(doc):
            for i in pages:
                doc[i].set_rotation((doc[i].rotation + degrees) % 360)
        self.document.edit(change)

    def delete_pages(self):
        pages = self._target_pages()
        if len(pages) >= self.document.page_count:
            self.toast("Un document garde au moins une page")
            return
        self.document.edit(lambda doc: doc.delete_pages(pages))
        self.toast(f"{len(pages)} page{'s' if len(pages) > 1 else ''} supprimée{'s' if len(pages) > 1 else ''}",
                   "Annuler", self.undo)

    def undo(self):
        if self.document:
            self.viewer.commit_fields()
            self.document.undo()

    def redo(self):
        if self.document:
            self.document.redo()

    def _on_current_page(self, viewer, index):
        if not self.document:
            return
        self._update_subtitle()
        self.sidebar.show_page(index)

    def _on_viewer_key(self, controller, keyval, code, state):
        focus = self.get_focus()
        if isinstance(focus, (Gtk.Text, Gtk.TextView)):
            return False
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and self.viewer.selected_annot:
            self.viewer.delete_selected_annot()
            return True
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C) and self.viewer.selected_text:
            self.get_clipboard().set(self.viewer.selected_text_string())
            self.toast("Texte copié")
            return True
        if keyval == Gdk.KEY_Escape:
            self.set_tool("select")
            return True
        return False

    # Signatures

    def _on_signature_chosen(self, menu, signature):
        if not self.document:
            self.toast("Ouvrez un document pour y placer la signature")
            return
        self.set_tool("signature")
        self.viewer.signature = signature
        self.toast("Cliquez sur la page pour placer la signature, ou tracez sa taille")

    def _on_certificate(self, menu):
        if not self.document:
            self.toast("Ouvrez d'abord le document à signer")
            return
        self.viewer.commit_fields()
        dialog = dialogs.CertificateDialog(self)
        dialog.connect("ready", self._on_certificate_ready)
        dialog.present()

    def _on_certificate_ready(self, dialog, options):
        if options["visible"]:
            self._pending_signature = options
            self.set_tool("zone")
            self.toast("Tracez sur la page le cadre de la signature")
        else:
            self._sign(options)

    def _on_zone_drawn(self, viewer, index, rect):
        options, self._pending_signature = self._pending_signature, None
        self.set_tool("select")
        if options:
            page = self.document.doc[index]
            pdf_rect = (rect * ~page.transformation_matrix).normalize()
            self._sign(options, index, (pdf_rect.x0, pdf_rect.y0, pdf_rect.x1, pdf_rect.y1))

    def _sign(self, options, page=None, box=None):
        data = self.document.doc.tobytes()

        def done(path):
            try:
                dialogs.sign_pdf(data, path, options, page, box)
            except Exception as error:
                self.error("Signature impossible", str(error))
                return
            document = Document.open(path)
            self.set_document(document)
            self.toast("Document signé numériquement")
        self._save_dialog("Enregistrer le document signé", f"{self._stem()}-signé.pdf", done)

    # Messages

    def toast(self, text, action=None, callback=None):
        # One message at a time: a new one replaces the one on screen.
        if getattr(self, "_toast", None):
            self._toast.withdraw()
        toast = self._toast = Granite.Toast(title=text)
        if action:
            toast.set_default_action(action)
            toast.connect("default-action", lambda t: callback())
        overlay = self.overlay if self.stack.get_visible_child_name() == "document" else self.stack.get_child_by_name("welcome")
        overlay.add_overlay(toast)
        toast.connect("closed", lambda t: GLib.timeout_add(400, lambda: (overlay.remove_overlay(t), False)[1]))
        toast.send_notification()

    def error(self, title, detail):
        dialog = Granite.MessageDialog.with_image_from_icon_name(title, detail, "dialog-error",
                                                                  Gtk.ButtonsType.CLOSE)
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_close_request(self, window):
        if not self.document:
            return False
        self.viewer.commit_fields()
        if not self.document.modified:
            return False
        dialog = Granite.MessageDialog.with_image_from_icon_name(
            f"Enregistrer les modifications de « {self.document.title} » ?",
            "Sinon, elles seront perdues.", "dialog-warning", Gtk.ButtonsType.NONE)
        dialog.add_button("Fermer sans enregistrer", 1).add_css_class("destructive-action")
        dialog.add_button("Annuler", Gtk.ResponseType.CANCEL)
        dialog.add_button("Enregistrer", Gtk.ResponseType.ACCEPT).add_css_class("suggested-action")
        dialog.set_transient_for(self)
        dialog.set_modal(True)

        def response(dialog, code):
            dialog.destroy()
            if code == 1:
                self.document.modified = False
                self.destroy()
            elif code == Gtk.ResponseType.ACCEPT:
                self.save(then=self.destroy)
        dialog.connect("response", response)
        dialog.present()
        return True


def _swatch(cr, width, height, colour, dim=False):
    import math
    r = min(width, height) / 2 - 1
    cr.arc(width / 2, height / 2, r, 0, 2 * math.pi)
    cr.set_source_rgba(*colour, 0.35 if dim else 1)
    cr.fill_preserve()
    cr.set_source_rgba(0, 0, 0, 0.25)
    cr.set_line_width(1)
    cr.stroke()
