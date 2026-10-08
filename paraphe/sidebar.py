# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Paraphe contributors
"""Page thumbnails: pick, reorder by drag and drop, rotate, delete, extract,
and drop PDF files between pages to insert them."""

import pymupdf
from gi.repository import Gdk, GLib, GObject, Gtk

THUMB_WIDTH = 112


class PageSidebar(Gtk.Box):
    __gtype_name__ = "ParapheSidebar"
    __gsignals__ = {
        "page-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        # Paths of files dropped, and the index to insert them at.
        "files-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, int)),
    }

    def __init__(self, page_menu):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("paraphe-sidebar")
        self.document = None
        self._handlers = []
        self._syncing = False
        self._render_source = 0

        header = Gtk.Box(spacing=6, margin_start=14, margin_end=8, margin_top=8, margin_bottom=2)
        self.count_label = Gtk.Label(label="Pages", xalign=0, hexpand=True)
        self.count_label.add_css_class("section-title")
        header.append(self.count_label)
        actions = Gtk.MenuButton(icon_name="paraphe-more-symbolic", menu_model=page_menu,
                                 tooltip_text="Actions sur les pages sélectionnées")
        actions.add_css_class("flat")
        header.append(actions)
        self.append(header)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.MULTIPLE)
        self.list.set_activate_on_single_click(True)
        self.list.add_css_class("thumbnails")
        self.list.connect("row-activated", self._on_activated)
        scroller = Gtk.ScrolledWindow(child=self.list, vexpand=True,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.append(scroller)

        # Right click: the same page actions, on the row under the pointer.
        self.context = Gtk.PopoverMenu.new_from_model(page_menu)
        # Not a child of the list: ListBox.remove_all() would loop on it.
        self.context.set_parent(self)
        self.context.set_has_arrow(False)
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._on_context)
        self.list.add_controller(click)

        drop = Gtk.DropTarget.new(GObject.TYPE_NONE, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.set_gtypes([GObject.TYPE_STRING, Gdk.FileList])
        drop.connect("drop", self._on_drop)
        drop.connect("motion", self._on_drop_motion)
        drop.connect("leave", lambda t: self.list.drag_unhighlight_row())
        self.list.add_controller(drop)

    def _on_context(self, gesture, n, x, y):
        row = self.list.get_row_at_y(int(y))
        if row is None:
            return
        if not row.is_selected():
            self.list.unselect_all()
            self.list.select_row(row)
        x, y = self.list.translate_coordinates(self, x, y)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self.context.set_pointing_to(rect)
        self.context.popup()

    def set_document(self, document):
        for handler in self._handlers:
            self.document.disconnect(handler)
        self.document = document
        self._handlers = [
            document.connect("structure-changed", lambda d: self.rebuild()),
            document.connect("page-changed", self._on_page_changed),
        ]
        self.rebuild()

    def rebuild(self):
        if self._render_source:
            GLib.source_remove(self._render_source)
            self._render_source = 0
        self.list.remove_all()
        self.pictures = []
        for index in range(self.document.page_count):
            self.list.append(self._row(index))
        count = self.document.page_count
        self.count_label.set_label(f"{count} page{'s' if count > 1 else ''}")
        self._pending = list(range(count))
        self._render_source = GLib.idle_add(self._render_some)

    def _row(self, index):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
        picture.add_css_class("thumbnail")
        w, h = self.document.doc[index].rect.width, self.document.doc[index].rect.height
        picture.set_size_request(THUMB_WIDTH, int(THUMB_WIDTH * h / max(w, 1)))
        picture.set_halign(Gtk.Align.CENTER)
        box.append(picture)
        label = Gtk.Label(label=str(index + 1), halign=Gtk.Align.CENTER)
        label.add_css_class("page-number")
        box.append(label)
        row = Gtk.ListBoxRow(child=box)
        row.index = index

        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_drag_prepare, row)
        row.add_controller(source)
        self.pictures.append(picture)
        return row

    def _render(self, index):
        page = self.document.doc[index]
        zoom = THUMB_WIDTH * 2 / max(page.rect.width, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        texture = Gdk.MemoryTexture.new(pix.width, pix.height, Gdk.MemoryFormat.R8G8B8,
                                        GLib.Bytes.new(pix.samples), pix.stride)
        self.pictures[index].set_paintable(texture)

    def _render_some(self):
        for _ in range(4):
            if not self._pending:
                self._render_source = 0
                return GLib.SOURCE_REMOVE
            index = self._pending.pop(0)
            if index < len(self.pictures):
                self._render(index)
        return GLib.SOURCE_CONTINUE

    def _on_page_changed(self, document, index):
        if 0 <= index < len(self.pictures):
            self._render(index)

    def _on_activated(self, listbox, row):
        if not self._syncing:
            self.emit("page-activated", row.index)

    def show_page(self, index):
        """Follow the page shown in the viewer, unless several are picked."""
        if len(self.list.get_selected_rows()) > 1:
            return
        row = self.list.get_row_at_index(index)
        if row and not row.is_selected():
            self._syncing = True
            self.list.unselect_all()
            self.list.select_row(row)
            self._syncing = False
            # Bring the row into view without stealing keyboard focus.
            ok, bounds = row.compute_bounds(self.list)
            adj = self.list.get_parent().get_vadjustment() if isinstance(self.list.get_parent(), Gtk.Viewport) else None
            if ok and adj:
                top, bottom = bounds.origin.y, bounds.origin.y + bounds.size.height
                if top < adj.get_value() or bottom > adj.get_value() + adj.get_page_size():
                    adj.set_value(max(0, top - 12))

    def selected_pages(self):
        return sorted(row.index for row in self.list.get_selected_rows())

    # Drag and drop

    def _on_drag_prepare(self, source, x, y, row):
        picture = self.pictures[row.index]
        paintable = picture.get_paintable()
        if paintable:
            source.set_icon(paintable, int(x), int(y))
        moving = self.selected_pages() if row.is_selected() else [row.index]
        return Gdk.ContentProvider.new_for_value(",".join(map(str, moving)))

    def _target_index(self, y):
        row = self.list.get_row_at_y(int(y))
        if row is None:
            return self.document.page_count, None
        ok, bounds = row.compute_bounds(self.list)
        after = ok and y > bounds.origin.y + bounds.size.height / 2
        return row.index + (1 if after else 0), row

    def _on_drop_motion(self, target, x, y):
        _, row = self._target_index(y)
        if row:
            self.list.drag_highlight_row(row)
        return Gdk.DragAction.MOVE

    def _on_drop(self, target, value, x, y):
        self.list.drag_unhighlight_row()
        index, _ = self._target_index(y)
        if isinstance(value, Gdk.FileList):
            paths = [f.get_path() for f in value.get_files() if f.get_path()]
            if paths:
                self.emit("files-dropped", paths, index)
            return True
        if isinstance(value, str) and value:
            moving = [int(i) for i in value.split(",")]
            self._move(moving, index)
            return True
        return False

    def _move(self, moving, index):
        if all(i == index or i + 1 == index for i in moving) and len(moving) == 1:
            return
        order = [i for i in range(self.document.page_count) if i not in moving]
        before = sum(1 for i in order if i < index)
        order[before:before] = moving

        def change(doc):
            doc.select(order)
        self.document.edit(change)
