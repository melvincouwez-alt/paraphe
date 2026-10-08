# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Paraphe contributors
"""The "Pages" mode: every page as a large thumbnail, to reorder by drag and
drop, and a bar of actions on the selection: add a PDF, split, extract,
duplicate, rotate, delete."""

import pymupdf
from gi.repository import Gdk, GLib, GObject, Graphene, Gtk

THUMB = 150


class Organizer(Gtk.Overlay):
    __gtype_name__ = "ParapheOrganizer"
    __gsignals__ = {
        "open-page": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "files-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, int)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, actions):
        super().__init__()
        self.document = None
        self._handlers = []
        self._source = 0
        self.pictures = []

        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.MULTIPLE, homogeneous=True,
                                valign=Gtk.Align.START, halign=Gtk.Align.CENTER, column_spacing=18, row_spacing=18,
                                max_children_per_line=30, activate_on_single_click=False,
                                margin_top=24, margin_bottom=110, margin_start=24, margin_end=24)
        self.grid.add_css_class("organizer")
        self.grid.connect("child-activated", lambda g, c: self.emit("open-page", c.index))
        self.grid.connect("selected-children-changed", lambda g: self.emit("selection-changed"))
        scroller = Gtk.ScrolledWindow(child=self.grid, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.add_css_class("paraphe-canvas")
        self.set_child(scroller)

        drop = Gtk.DropTarget.new(GObject.TYPE_NONE, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.set_gtypes([GObject.TYPE_STRING, Gdk.FileList])
        drop.connect("drop", self._on_drop)
        drop.connect("motion", self._on_motion)
        drop.connect("leave", lambda t: self._mark(None))
        self.grid.add_controller(drop)

        self.add_overlay(actions)

    # Document

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
        selected = set(self.selected_pages())
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0
        self.grid.remove_all()
        self.pictures = []
        for index in range(self.document.page_count):
            child = self._card(index)
            self.grid.append(child)
            if index in selected:
                self.grid.select_child(child)
        self._pending = list(range(self.document.page_count))
        self._source = GLib.idle_add(self._render_some)

    def _card(self, index):
        page = self.document.doc[index]
        w, h = page.rect.width, page.rect.height
        scale = THUMB / max(w, h)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        frame = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        frame.set_size_request(THUMB, THUMB)
        picture = Thumb(int(w * scale), int(h * scale))
        picture.add_css_class("thumbnail")
        frame.append(picture)
        box.append(frame)
        label = Gtk.Label(label=str(index + 1), halign=Gtk.Align.CENTER)
        label.add_css_class("page-number")
        box.append(label)
        child = Gtk.FlowBoxChild(child=box)
        child.index = index
        child.add_css_class("organizer-card")
        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_prepare, child)
        child.add_controller(source)
        self.pictures.append(picture)
        return child

    def _render(self, index):
        page = self.document.doc[index]
        zoom = THUMB * 2 / max(page.rect.width, page.rect.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        self.pictures[index].set_paintable(Gdk.MemoryTexture.new(
            pix.width, pix.height, Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(pix.samples), pix.stride))

    def _render_some(self):
        for _ in range(4):
            if not self._pending:
                self._source = 0
                return GLib.SOURCE_REMOVE
            index = self._pending.pop(0)
            if index < len(self.pictures):
                self._render(index)
        return GLib.SOURCE_CONTINUE

    def _on_page_changed(self, document, index):
        if 0 <= index < len(self.pictures):
            self._render(index)

    def selected_pages(self):
        return sorted(child.index for child in self.grid.get_selected_children())

    def select_all(self):
        self.grid.select_all()

    # Drag and drop

    def _on_prepare(self, source, x, y, child):
        paintable = self.pictures[child.index].get_paintable()
        if paintable:
            source.set_icon(paintable, int(x), int(y))
        moving = self.selected_pages() if child.is_selected() else [child.index]
        return Gdk.ContentProvider.new_for_value(",".join(map(str, moving)))

    def _target(self, x, y):
        child = self.grid.get_child_at_pos(int(x), int(y))
        if child is None:
            return self.document.page_count, None
        ok, bounds = child.compute_bounds(self.grid)
        after = ok and x > bounds.origin.x + bounds.size.width / 2
        return child.index + (1 if after else 0), (child, after)

    def _mark(self, spot):
        for child in getattr(self, "_marked", []):
            child.remove_css_class("drop-before")
            child.remove_css_class("drop-after")
        self._marked = []
        if spot:
            child, after = spot
            child.add_css_class("drop-after" if after else "drop-before")
            self._marked = [child]

    def _on_motion(self, target, x, y):
        self._mark(self._target(x, y)[1])
        return Gdk.DragAction.MOVE

    def _on_drop(self, target, value, x, y):
        index, _ = self._target(x, y)
        self._mark(None)
        if isinstance(value, Gdk.FileList):
            paths = [f.get_path() for f in value.get_files() if f.get_path()]
            if paths:
                self.emit("files-dropped", paths, index)
            return True
        if isinstance(value, str) and value:
            moving = [int(i) for i in value.split(",")]
            order = [i for i in range(self.document.page_count) if i not in moving]
            before = sum(1 for i in order if i < index)
            order[before:before] = moving
            if order != list(range(self.document.page_count)):
                self.document.edit(lambda doc: doc.select(order))
            return True
        return False


class Thumb(Gtk.Widget):
    """A page picture of a fixed size: Gtk.Picture would grow to the pixel
    size of its texture, rendered at twice the size for sharp screens."""

    __gtype_name__ = "ParapheThumb"

    def __init__(self, width, height):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        self.size = (width, height)
        self.texture = None
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def set_paintable(self, texture):
        self.texture = texture
        self.queue_draw()

    def get_paintable(self):
        return self.texture

    def do_measure(self, orientation, for_size):
        size = self.size[0 if orientation == Gtk.Orientation.HORIZONTAL else 1]
        return size, size, -1, -1

    def do_snapshot(self, snapshot):
        if self.texture:
            snapshot.append_texture(self.texture, Graphene.Rect().init(0, 0, self.get_width(), self.get_height()))
