# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Paraphe contributors
"""The scrolling page view and every tool that works on a page.

Coordinates: PyMuPDF keeps annotations, text and fields in unrotated page
space. A page is drawn rotated, so a pointer position goes from widget
pixels to displayed page points (divide by the zoom), then through the
page's derotation matrix. Overlays take the opposite way.
"""

import math
import re

import pymupdf
from gi.repository import Gdk, GLib, GObject, Graphene, Gtk

from . import textsel

PAGE_GAP = 16
MARGIN = 24
MIN_ZOOM = 0.2
MAX_ZOOM = 6.0
CACHE_SIZE = 24
CLICK_SLOP = 4

TEXT_TOOLS = ("highlight", "underline", "strike")
FIELD_TINT = (0.20, 0.45, 0.90, 0.10)
ERASE_TOLERANCE = 6  # pixels around the eraser that still touch an annotation

# Free text: PDF line height, room under the last line, gap kept to the page edge.
TEXT_LEADING = 1.2
TEXT_MARGIN = 18
TEXT_FONT = "helv"

DEFAULT_COLOURS = {
    "highlight": (1.0, 0.93, 0.55),
    "underline": (0.35, 0.62, 0.95),
    "strike": (0.85, 0.2, 0.22),
    "text": (0.12, 0.14, 0.2),
    "note": (1.0, 0.82, 0.25),
    "draw": (0.35, 0.62, 0.95),
    "rect": (0.85, 0.2, 0.22),
}

# Annotation types the eraser never touches.
NOT_ERASABLE = {pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_LINK}
MARKUP = {pymupdf.PDF_ANNOT_HIGHLIGHT, pymupdf.PDF_ANNOT_UNDERLINE,
          pymupdf.PDF_ANNOT_STRIKE_OUT, pymupdf.PDF_ANNOT_SQUIGGLY}

# Annotation types the select tool can move by changing their rectangle.
MOVABLE = {
    pymupdf.PDF_ANNOT_TEXT,
    pymupdf.PDF_ANNOT_FREE_TEXT,
    pymupdf.PDF_ANNOT_SQUARE,
    pymupdf.PDF_ANNOT_CIRCLE,
    pymupdf.PDF_ANNOT_STAMP,
    pymupdf.PDF_ANNOT_INK,
}


def rgba(r, g, b, a=1.0):
    colour = Gdk.RGBA()
    colour.red, colour.green, colour.blue, colour.alpha = r, g, b, a
    return colour


def grect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


class Viewer(Gtk.ScrolledWindow):
    __gtype_name__ = "ParapheViewer"
    __gsignals__ = {
        "current-page": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        # A page and a rectangle in unrotated page space, for the zone tool.
        "zone-drawn": (GObject.SignalFlags.RUN_FIRST, None, (int, object)),
        "notify-user": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.add_css_class("paraphe-canvas")
        self.document = None
        self.zoom = 1.0
        self.fit_width = True
        self.tool = "select"
        self.colours = dict(DEFAULT_COLOURS)
        # Size of the next free text, in points; kept while the app runs.
        self.text_size = 11
        self.signature = None
        self.pages = []
        self.sizes = []
        self._cache = {}
        self._words = {}
        self._anchor = None
        self._current = 0
        self._handlers = []
        # Selected annotation: (page index, xref); selected text: (page, words).
        self.selected_annot = None
        self.selected_text = None
        # The free text being typed on a page, if any.
        self.text_editor = None

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=PAGE_GAP)
        self.box.set_halign(Gtk.Align.CENTER)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.box, f"set_margin_{side}")(MARGIN)
        # Room under the last page for the floating palette.
        self.box.set_margin_bottom(96)
        self.set_child(self.box)
        # A page takes the keyboard focus when clicked; the viewport would then
        # scroll to show it whole, which jumps to the top of a zoomed page.
        self.get_child().set_scroll_to_focus(False)

        vadj = self.get_vadjustment()
        vadj.connect("value-changed", self._on_scrolled)
        vadj.connect("changed", self._on_layout)
        self.get_hadjustment().connect("notify::page-size", self._on_width)

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        scroll.connect("scroll", self._on_wheel)
        self.add_controller(scroll)

        zoom = Gtk.GestureZoom()
        zoom.connect("begin", lambda g, s: setattr(self, "_pinch", self.zoom))
        zoom.connect("scale-changed", lambda g, scale: self.set_zoom(self._pinch * scale))
        self.add_controller(zoom)

    # Document

    def set_document(self, document):
        for handler in self._handlers:
            self.document.disconnect(handler)
        self.document = document
        self._handlers = [
            document.connect("structure-changed", lambda d: self.rebuild(keep_place=True)),
            document.connect("page-changed", self._on_page_changed),
        ]
        self.rebuild()

    def rebuild(self, keep_place=False):
        anchor = self._place() if keep_place else None
        # Pages may have moved under free text still being typed: drop it.
        if self.text_editor:
            self.text_editor._done = True
            self.text_editor = None
        self.clear_selection(emit=False)
        self._cache.clear()
        self._words.clear()
        for page in self.pages:
            self.box.remove(page)
        doc = self.document.doc
        self.sizes = [(p.rect.width, p.rect.height) for p in doc]
        self.pages = [PageView(self, i) for i in range(doc.page_count)]
        for page in self.pages:
            self.box.append(page)
        if self.fit_width:
            self._fit()
        if anchor:
            self._anchor = anchor
        self.emit("selection-changed")

    def _on_page_changed(self, document, index):
        self._words.pop(index, None)
        if 0 <= index < len(self.pages):
            self.pages[index].queue_draw()
        else:
            for page in self.pages:
                page.queue_draw()

    # Rendering

    def texture(self, index, scale):
        revision = self.document.revision(index)
        key = (index, revision, round(self.zoom * scale, 3))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        page = self.document.doc[index]
        zoom = self.zoom * scale
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        texture = Gdk.MemoryTexture.new(
            pix.width, pix.height, Gdk.MemoryFormat.R8G8B8,
            GLib.Bytes.new(pix.samples), pix.stride)
        self._cache = {k: v for k, v in self._cache.items() if k[0] != index}
        if len(self._cache) >= CACHE_SIZE:
            del self._cache[next(iter(self._cache))]
        self._cache[key] = texture
        return texture

    def render_key(self, index):
        return self.document.revision(index), round(self.zoom, 3)

    def refresh_visible(self):
        for page in self.pages:
            if getattr(page, "drawn", None) != self.render_key(page.index) and self.is_near_view(page):
                page.queue_draw()

    def words(self, index):
        words = self._words.get(index)
        if words is None:
            words = self._words[index] = self.document.doc[index].get_text("words")
        return words

    def is_near_view(self, widget):
        ok, bounds = widget.compute_bounds(self.box)
        if not ok:
            return False
        vadj = self.get_vadjustment()
        top = vadj.get_value() - MARGIN - vadj.get_page_size()
        bottom = vadj.get_value() + 2 * vadj.get_page_size()
        return bounds.origin.y + bounds.size.height >= top and bounds.origin.y <= bottom

    # Zoom and scrolling

    def _viewport_width(self):
        return self.get_hadjustment().get_page_size() or self.get_width()

    def _fit(self):
        width = self._viewport_width()
        if not self.sizes or width <= 0:
            return
        widest = max(w for w, _ in self.sizes)
        zoom = (width - 2 * MARGIN - 14) / widest
        self._apply_zoom(max(MIN_ZOOM, min(MAX_ZOOM, zoom)))

    def _on_width(self, *args):
        if self.fit_width and self.pages:
            self._fit()

    def set_zoom(self, zoom, fit=False):
        self.fit_width = fit
        if fit:
            self._fit()
        else:
            self._apply_zoom(max(MIN_ZOOM, min(MAX_ZOOM, zoom)))

    def _apply_zoom(self, zoom):
        if abs(zoom - self.zoom) < 1e-3 and self.pages and self._anchor is None:
            return
        if self.pages and self._anchor is None:
            self._anchor = self._place()
        self.zoom = zoom
        for page in self.pages:
            page.zoom_changed()
        self.emit("zoom-changed", zoom)

    def _place(self):
        """The current page and how far down it the view starts, 0 to 1."""
        if not self.pages:
            return None
        page = self.pages[min(self._current, len(self.pages) - 1)]
        ok, bounds = page.compute_bounds(self.box)
        value = self.get_vadjustment().get_value()
        fraction = (value - bounds.origin.y) / bounds.size.height if ok and bounds.size.height else 0
        return page.index, fraction

    def _on_layout(self, vadj):
        GLib.idle_add(lambda: self.refresh_visible() and False)
        # "changed" fires in the middle of the allocation: a value set there
        # would leave the viewport drawn at the old offset, so wait for idle.
        if self._anchor is not None and not getattr(self, "_restore_source", 0):
            self._restore_source = GLib.idle_add(self._restore_anchor)

    def _restore_anchor(self):
        self._restore_source = 0
        if self._anchor is None:
            return GLib.SOURCE_REMOVE
        index, fraction = self._anchor
        self._anchor = None
        if index < len(self.pages):
            ok, bounds = self.pages[index].compute_bounds(self.box)
            if ok:
                self.get_vadjustment().set_value(bounds.origin.y + fraction * bounds.size.height)
        return GLib.SOURCE_REMOVE

    def _on_wheel(self, controller, dx, dy):
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            self.set_zoom(self.zoom * (0.9 if dy > 0 else 1.1))
            return True
        return False

    def _on_scrolled(self, vadj):
        self.refresh_visible()
        probe = vadj.get_value() + vadj.get_page_size() / 3
        current = self._current
        for page in self.pages:
            ok, bounds = page.compute_bounds(self.box)
            if ok and bounds.origin.y + bounds.size.height + PAGE_GAP > probe:
                current = page.index
                break
        if current != self._current:
            self._current = current
            self.emit("current-page", current)

    @property
    def current_page(self):
        return self._current

    def scroll_to_page(self, index):
        if not 0 <= index < len(self.pages):
            return
        ok, bounds = self.pages[index].compute_bounds(self.box)
        if ok:
            self.get_vadjustment().set_value(bounds.origin.y - PAGE_GAP / 2)
        self._current = index
        self.emit("current-page", index)

    # Tools

    def set_tool(self, tool):
        self.commit_text()
        self.tool = tool
        self.clear_selection()
        for page in self.pages:
            page.tool_changed()

    def clear_selection(self, emit=True):
        pages = set()
        if self.selected_annot:
            pages.add(self.selected_annot[0])
        if self.selected_text:
            pages.add(self.selected_text[0])
        self.selected_annot = None
        self.selected_text = None
        for index in pages:
            if index < len(self.pages):
                self.pages[index].queue_draw()
        if emit:
            self.emit("selection-changed")

    def selected_text_string(self):
        if not self.selected_text:
            return ""
        return textsel.as_text(self.selected_text[1])

    def delete_selected_annot(self):
        if not self.selected_annot:
            return
        index, xref = self.selected_annot
        self.clear_selection()

        def change(doc):
            page = doc[index]
            annot = page.load_annot(xref)
            if annot:
                page.delete_annot(annot)
        self.document.edit(change, index)

    # Fields: filled values waiting in an entry go to the document before
    # saving, since the user may press Ctrl+S with the caret still inside.
    def commit_fields(self):
        self.commit_text()
        for page in self.pages:
            page.commit_fields()

    def commit_text(self):
        if self.text_editor:
            self.text_editor.finish()

    def restyle_text(self):
        """The palette changed colour or size while free text is being typed."""
        editor = self.text_editor
        if editor:
            editor.colour = self.colours["text"]
            editor.size = self.text_size
            editor.page_view.queue_allocate()


class PageView(Gtk.Widget):
    __gtype_name__ = "ParaphePageView"

    def __init__(self, viewer, index):
        super().__init__()
        self.viewer = viewer
        self.index = index
        self.add_css_class("pdf-page")
        # A vertical box stretches its children to the widest page: a
        # landscape page would stretch every portrait one.
        self.set_halign(Gtk.Align.CENTER)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_focusable(True)
        self._drag = None  # (start widget point, current widget point)
        self._stroke = []
        self._hover = None
        self._editors = []  # (FieldEditor, unrotated rect)
        self._text = None   # TextEditor open on this page
        self._erase = []    # xrefs the eraser went over during a drag
        self._fields = []   # (xref, type, unrotated rect) for clickable boxes

        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_begin)
        drag.connect("drag-update", self._on_update)
        drag.connect("drag-end", self._on_end)
        self.add_controller(drag)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        self._build_fields()
        self.tool_changed()

    # Geometry

    @property
    def zoom(self):
        return self.viewer.zoom

    def _page(self):
        return self.viewer.document.doc[self.index]

    def to_page(self, x, y):
        """Widget pixels to unrotated page points."""
        page = self._page()
        return pymupdf.Point(x / self.zoom, y / self.zoom) * page.derotation_matrix

    def to_widget(self, rect, page=None):
        """An unrotated page rectangle to widget pixels (x, y, w, h)."""
        page = page or self._page()
        r = (pymupdf.Rect(rect) * page.rotation_matrix).normalize()
        z = self.zoom
        return r.x0 * z, r.y0 * z, r.width * z, r.height * z

    def do_measure(self, orientation, for_size):
        w, h = self.viewer.sizes[self.index]
        size = (w if orientation == Gtk.Orientation.HORIZONTAL else h) * self.zoom
        size = int(round(size))
        return size, size, -1, -1

    def do_size_allocate(self, width, height, baseline):
        if self._text:
            self._allocate_text(width, height)
        if not self._editors:
            return
        page = self._page()
        for editor, rect in self._editors:
            x, y, w, h = self.to_widget(rect, page)
            editor.set_zoom(self.zoom, h)
            editor.measure(Gtk.Orientation.HORIZONTAL, -1)
            editor.measure(Gtk.Orientation.VERTICAL, -1)
            transform = Gsk_translate(x, y)
            editor.allocate(max(1, int(w)), max(1, int(h)), -1, transform)

    def _allocate_text(self, width, height):
        editor = self._text
        zoom = self.zoom
        editor.set_zoom(zoom)
        w = max(1, int(round(editor.width * zoom)))
        editor.measure(Gtk.Orientation.HORIZONTAL, -1)
        natural = editor.measure(Gtk.Orientation.VERTICAL, w)[1]
        # Text growing past the bottom of the page pushes the box up.
        editor.shown_top = max(0, min(editor.top, (height - natural) / zoom - 2))
        editor.allocate(w, natural, -1, Gsk_translate(editor.left * zoom, editor.shown_top * zoom))

    def zoom_changed(self):
        self.queue_resize()

    def tool_changed(self):
        cursors = {
            "select": "default", "highlight": "text", "underline": "text",
            "strike": "text", "text": "text", "note": "cell", "draw": "crosshair",
            "rect": "crosshair", "signature": "copy", "zone": "crosshair", "erase": "crosshair",
        }
        self.set_cursor_from_name(cursors.get(self.viewer.tool, "default"))
        self._hover = None
        self.queue_draw()

    # Drawing

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        # GTK keeps this drawing until the next queue_draw(): a page drawn
        # blank while far away is redrawn by Viewer.refresh_visible().
        self.drawn = None
        if self.viewer.is_near_view(self):
            scale = self.get_native().get_surface().get_scale() if self.get_native() else 1
            texture = self.viewer.texture(self.index, scale)
            snapshot.append_texture(texture, grect(0, 0, width, height))
            self.drawn = self.viewer.render_key(self.index)
        page = self._page()
        for xref, kind, rect in self._fields:
            snapshot.append_color(rgba(*FIELD_TINT), grect(*self.to_widget(rect, page)))
        self._snapshot_selection(snapshot, page)
        self._snapshot_tool(snapshot, page)
        for editor, _ in self._editors:
            self.snapshot_child(editor, snapshot)
        if self._text:
            self.snapshot_child(self._text, snapshot)

    def _snapshot_selection(self, snapshot, page):
        viewer = self.viewer
        if viewer.selected_text and viewer.selected_text[0] == self.index:
            for rect in textsel.line_rects(viewer.selected_text[1]):
                snapshot.append_color(rgba(0.2, 0.45, 0.9, 0.3), grect(*self.to_widget(rect, page)))
        if viewer.selected_annot and viewer.selected_annot[0] == self.index:
            annot = page.load_annot(viewer.selected_annot[1])
            if annot:
                x, y, w, h = self.to_widget(annot.rect, page)
                self._frame(snapshot, x - 3, y - 3, w + 6, h + 6, rgba(0.2, 0.45, 0.9, 0.9))

    def _frame(self, snapshot, x, y, w, h, colour, width=2):
        for rect in ((x, y, w, width), (x, y + h - width, w, width),
                     (x, y, width, h), (x + w - width, y, width, h)):
            snapshot.append_color(colour, grect(*rect))

    def _snapshot_tool(self, snapshot, page):
        viewer = self.viewer
        tool = viewer.tool
        if self._drag:
            (x0, y0), (x1, y1) = self._drag
            if tool in TEXT_TOOLS or (tool == "select" and not self._moving):
                words = self._drag_words()
                colour = viewer.colours.get(tool, (0.2, 0.45, 0.9))
                if words:
                    for rect in textsel.line_rects(words):
                        snapshot.append_color(rgba(*colour, 0.35), grect(*self.to_widget(rect, page)))
                elif tool in TEXT_TOOLS:
                    snapshot.append_color(rgba(*colour, 0.35), grect(*_box(x0, y0, x1, y1)))
            elif tool in ("rect", "zone", "signature"):
                colour = rgba(*viewer.colours.get("rect", (0.2, 0.45, 0.9))) if tool == "rect" else rgba(0.2, 0.45, 0.9)
                x, y, w, h = _box(x0, y0, x1, y1)
                if tool == "zone":
                    snapshot.append_color(rgba(0.2, 0.45, 0.9, 0.12), grect(x, y, w, h))
                if tool == "signature" and viewer.signature and w > 4:
                    self._snapshot_signature(snapshot, (x, y, w, h), 1.0)
                else:
                    self._frame(snapshot, x, y, w, h, colour, 2)
            elif tool == "select" and self._moving:
                annot = page.load_annot(viewer.selected_annot[1])
                if annot:
                    x, y, w, h = self.to_widget(annot.rect, page)
                    self._frame(snapshot, x + x1 - x0, y + y1 - y0, w, h, rgba(0.2, 0.45, 0.9, 0.9))
        if tool == "draw" and len(self._stroke) > 1:
            colour = viewer.colours["draw"]
            cr = snapshot.append_cairo(grect(0, 0, self.get_width(), self.get_height()))
            cr.set_source_rgb(*colour)
            cr.set_line_width(2 * self.zoom)
            cr.set_line_cap(1)
            cr.set_line_join(1)
            cr.move_to(*self._stroke[0])
            for point in self._stroke[1:]:
                cr.line_to(*point)
            cr.stroke()
        if tool == "erase" and self._drag:
            for xref in self._erase:
                annot = page.load_annot(xref)
                if annot:
                    x, y, w, h = self.to_widget(annot.rect, page)
                    snapshot.append_color(rgba(0.85, 0.2, 0.22, 0.12), grect(x - 2, y - 2, w + 4, h + 4))
                    self._frame(snapshot, x - 2, y - 2, w + 4, h + 4, rgba(0.85, 0.2, 0.22, 0.8), 1)
            if self._stroke:
                cr = snapshot.append_cairo(grect(0, 0, self.get_width(), self.get_height()))
                cr.set_source_rgba(0.45, 0.47, 0.52, 0.35)
                cr.set_line_width(2 * ERASE_TOLERANCE)
                cr.set_line_cap(1)
                cr.set_line_join(1)
                cr.move_to(*self._stroke[0])
                for point in self._stroke:
                    cr.line_to(*point)
                cr.stroke()
        if tool == "signature" and self._hover and not self._drag and viewer.signature:
            self._snapshot_signature(snapshot, self._signature_box(*self._hover), 0.45)

    def _snapshot_signature(self, snapshot, box, alpha):
        cr = snapshot.append_cairo(grect(0, 0, self.get_width(), self.get_height()))
        self.viewer.signature.draw(cr, box, alpha)

    def _signature_box(self, x, y):
        """Default size of a signature dropped with a click, centred on it."""
        width = 150 * self.zoom
        height = width / self.viewer.signature.aspect
        return x - width / 2, y - height / 2, width, height

    # Pointer

    _moving = False

    def _on_motion(self, controller, x, y):
        if self.viewer.tool == "signature":
            self._hover = (x, y)
            self.queue_draw()
        elif self.viewer.tool == "select":
            self.set_cursor_from_name("pointer" if self._hit_link(x, y) or self._hit_field(x, y) else "default")

    def _on_leave(self, controller):
        if self._hover:
            self._hover = None
            self.queue_draw()

    def _on_begin(self, gesture, x, y):
        viewer = self.viewer
        editor = viewer.text_editor
        if editor:
            if editor.page_view is self and editor.contains_point(x, y):
                gesture.set_state(Gtk.EventSequenceState.DENIED)
                return
            # A click away from the text being typed only ends it.
            editor.finish()
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            self._drag = None
            return
        self.grab_focus()
        self._drag = ((x, y), (x, y))
        self._moving = False
        if viewer.tool == "draw":
            self._stroke = [(x, y)]
        elif viewer.tool == "erase":
            self._stroke = [(x, y)]
            self._erase = []
            self._erase_at(x, y)
        elif viewer.tool == "select":
            hit = self._hit_annot(x, y)
            if viewer.selected_annot and hit == viewer.selected_annot:
                page = self._page()
                annot = page.load_annot(hit[1])
                self._moving = annot is not None and annot.type[0] in MOVABLE
        self.queue_draw()

    def _on_update(self, gesture, dx, dy):
        if not self._drag:
            return
        (x0, y0), _ = self._drag
        self._drag = ((x0, y0), (x0 + dx, y0 + dy))
        if self.viewer.tool == "draw":
            self._stroke.append((x0 + dx, y0 + dy))
        elif self.viewer.tool == "erase":
            self._stroke.append((x0 + dx, y0 + dy))
            self._erase_at(x0 + dx, y0 + dy)
        self.queue_draw()

    def _on_end(self, gesture, dx, dy):
        if not self._drag:
            return
        (x0, y0), _ = self._drag
        x1, y1 = x0 + dx, y0 + dy
        click = math.hypot(dx, dy) < CLICK_SLOP
        words = self._drag_words() if not click else None
        self._drag = None
        stroke, self._stroke = self._stroke, []
        tool = self.viewer.tool
        try:
            handler = getattr(self, f"_finish_{tool}")
            handler(x0, y0, x1, y1, click, words=words, stroke=stroke)
        finally:
            self.queue_draw()

    def _drag_words(self):
        (x0, y0), (x1, y1) = self._drag
        return textsel.select(self.viewer.words(self.index), self.to_page(x0, y0), self.to_page(x1, y1))

    def _hit_annot(self, x, y):
        point = self.to_page(x, y)
        page = self._page()
        best = None
        for annot in page.annots():
            if annot.type[0] in (pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_LINK):
                continue
            if point in annot.rect + (-3, -3, 3, 3):
                area = annot.rect.width * annot.rect.height
                if best is None or area < best[0]:
                    best = (area, annot.xref)
        return (self.index, best[1]) if best else None

    def _erase_at(self, x, y):
        """Note every annotation under the eraser at this widget point."""
        page = self._page()
        point = self.to_page(x, y)
        tol = ERASE_TOLERANCE / self.zoom
        for annot in page.annots():
            kind = annot.type[0]
            if kind in NOT_ERASABLE or annot.xref in self._erase:
                continue
            if point not in annot.rect + (-tol, -tol, tol, tol):
                continue
            if kind == pymupdf.PDF_ANNOT_INK:
                # A stroke is only touched near its line, not anywhere in its box.
                reach = tol + (annot.border.get("width") or 1)
                if not any(_near(point, stroke, reach) for stroke in annot.vertices or []):
                    continue
            elif kind in MARKUP and annot.vertices:
                v = annot.vertices
                rects = [pymupdf.Quad(*v[i:i + 4]).rect for i in range(0, len(v) - 3, 4)]
                if not any(point in r + (-tol, -tol, tol, tol) for r in rects):
                    continue
            self._erase.append(annot.xref)

    def _hit_link(self, x, y):
        point = self.to_page(x, y)
        for link in self._page().get_links():
            if point in link["from"]:
                return link
        return None

    def _hit_field(self, x, y):
        point = self.to_page(x, y)
        for xref, kind, rect in self._fields:
            if point in rect:
                return xref, kind
        return None

    # Tool results

    def _edit(self, change):
        return self.viewer.document.edit(change, self.index)

    def _finish_select(self, x0, y0, x1, y1, click, words=None, **_):
        viewer = self.viewer
        if self._moving and not click:
            self._move_annot(viewer.selected_annot[1], (x1 - x0) / self.zoom, (y1 - y0) / self.zoom)
            return
        if click:
            field = self._hit_field(x0, y0)
            if field:
                self._toggle_field(*field)
                return
            hit = self._hit_annot(x0, y0)
            viewer.clear_selection(emit=False)
            if hit:
                viewer.selected_annot = hit
                viewer.emit("selection-changed")
                self._annot_popover(hit[1], x0, y0)
                return
            link = self._hit_link(x0, y0)
            if link:
                self._follow(link)
            viewer.emit("selection-changed")
            return
        viewer.clear_selection(emit=False)
        if words:
            viewer.selected_text = (self.index, words)
        viewer.emit("selection-changed")

    def _move_annot(self, xref, dx, dy):
        page = self._page()
        # The drag is in displayed space; turn the offset into unrotated space.
        offset = pymupdf.Point(dx, dy) * page.derotation_matrix - pymupdf.Point(0, 0) * page.derotation_matrix

        def change(doc):
            p = doc[self.index]
            annot = p.load_annot(xref)
            if annot.type[0] == pymupdf.PDF_ANNOT_INK:
                strokes = [[(x + offset.x, y + offset.y) for x, y in s] for s in annot.vertices]
                colours, border, info = annot.colors, annot.border, annot.info
                p.delete_annot(annot)
                annot = p.add_ink_annot(strokes)
                annot.set_colors(stroke=colours.get("stroke"))
                annot.set_border(width=border.get("width", 1))
                annot.set_info(info)
                annot.update()
                return annot.xref
            annot.set_rect(annot.rect + (offset.x, offset.y, offset.x, offset.y))
            annot.update()
            return xref
        new_xref = self._edit(change)
        self.viewer.selected_annot = (self.index, new_xref)
        self.viewer.emit("selection-changed")

    def _follow(self, link):
        if link.get("kind") == pymupdf.LINK_GOTO:
            self.viewer.scroll_to_page(link["page"])
        elif link.get("uri"):
            Gtk.UriLauncher.new(link["uri"]).launch(self.get_root(), None, None)

    def _finish_markup(self, kind, x0, y0, x1, y1, words):
        viewer = self.viewer
        if words:
            quads = [r.quad for r in textsel.line_rects(words)]
        elif not self.viewer.words(self.index):
            # A scan has no text: mark the dragged box itself.
            quads = [pymupdf.Rect(self.to_page(x0, y0), self.to_page(x1, y1)).normalize().quad]
        else:
            return
        colour = viewer.colours[kind]
        adders = {"highlight": "add_highlight_annot", "underline": "add_underline_annot",
                  "strike": "add_strikeout_annot"}

        def change(doc):
            page = doc[self.index]
            annot = getattr(page, adders[kind])(quads)
            annot.set_colors(stroke=colour)
            annot.set_info(title=_author())
            annot.update()
        self._edit(change)

    def _finish_highlight(self, x0, y0, x1, y1, click, words=None, **_):
        if not click:
            self._finish_markup("highlight", x0, y0, x1, y1, words)

    def _finish_underline(self, x0, y0, x1, y1, click, words=None, **_):
        if not click:
            self._finish_markup("underline", x0, y0, x1, y1, words)

    def _finish_strike(self, x0, y0, x1, y1, click, words=None, **_):
        if not click:
            self._finish_markup("strike", x0, y0, x1, y1, words)

    def _finish_draw(self, x0, y0, x1, y1, click, stroke=(), **_):
        if len(stroke) < 2:
            return
        points = [tuple(self.to_page(x, y)) for x, y in stroke]
        colour = self.viewer.colours["draw"]

        def change(doc):
            page = doc[self.index]
            annot = page.add_ink_annot([points])
            annot.set_colors(stroke=colour)
            annot.set_border(width=2)
            annot.set_info(title=_author())
            annot.update()
        self._edit(change)

    def _finish_rect(self, x0, y0, x1, y1, click, **_):
        if click:
            return
        rect = pymupdf.Rect(self.to_page(x0, y0), self.to_page(x1, y1)).normalize()
        colour = self.viewer.colours["rect"]

        def change(doc):
            page = doc[self.index]
            annot = page.add_rect_annot(rect)
            annot.set_colors(stroke=colour)
            annot.set_border(width=1.5)
            annot.set_info(title=_author())
            annot.update()
        self._edit(change)

    def _finish_zone(self, x0, y0, x1, y1, click, **_):
        if click:
            return
        rect = pymupdf.Rect(self.to_page(x0, y0), self.to_page(x1, y1)).normalize()
        self.viewer.emit("zone-drawn", self.index, rect)

    def _finish_signature(self, x0, y0, x1, y1, click, **_):
        signature = self.viewer.signature
        if not signature:
            return
        if click:
            box = self._signature_box(x0, y0)
        else:
            box = _fit_box(_box(x0, y0, x1, y1), signature.aspect)
        page = self._page()
        placement = signature.placement(box, self.zoom, page)
        self._edit(lambda doc: placement(doc[self.index]))
        self.viewer.emit("notify-user", "Signature ajoutée")

    def _finish_erase(self, x0, y0, x1, y1, click, **_):
        xrefs, self._erase = self._erase, []
        if not xrefs:
            return

        def change(doc):
            page = doc[self.index]
            for xref in xrefs:
                annot = page.load_annot(xref)
                if annot:
                    page.delete_annot(annot)
        self._edit(change)

    def _finish_text(self, x0, y0, x1, y1, click, **_):
        hit = self._hit_annot(x0, y0) if click else None
        if hit:
            annot = self._page().load_annot(hit[1])
            if annot and annot.type[0] == pymupdf.PDF_ANNOT_FREE_TEXT:
                self.edit_free_text(hit[1])
                return
        size = self.viewer.text_size
        page_w, page_h = self.viewer.sizes[self.index]
        # The box is laid out in displayed space so text reads upright.
        if click or abs(x1 - x0) < 24:
            left, top = x0 / self.zoom, y0 / self.zoom - size * 0.8
            width = None
        else:
            left, top = min(x0, x1) / self.zoom, min(y0, y1) / self.zoom
            width = abs(x1 - x0) / self.zoom
        self.open_text(left, top, width, size, self.viewer.colours["text"])

    def open_text(self, left, top, width, size, colour, text="", xref=None):
        """Type free text straight on the page; width None runs to the page edge."""
        page_w, page_h = self.viewer.sizes[self.index]
        least = min(160, page_w - 2 * TEXT_MARGIN)
        if width is None:
            if page_w - TEXT_MARGIN - left < least:
                left = page_w - TEXT_MARGIN - least
            width = page_w - TEXT_MARGIN - left
        left = max(2, left)
        width = max(24, min(width, page_w - 2 - left))
        editor = TextEditor(self, left, max(0, top), width, size, colour, text, xref)
        editor.set_parent(self)
        self._text = editor
        self.viewer.text_editor = editor
        self.queue_allocate()
        self.queue_draw()
        GLib.idle_add(lambda: editor.view.grab_focus() and False)

    def edit_free_text(self, xref):
        page = self._page()
        annot = page.load_annot(xref)
        if not annot:
            return
        shown = (annot.rect * page.rotation_matrix).normalize()
        size, colour = _free_text_style(page.parent, xref, self.viewer)
        self.open_text(shown.x0, shown.y0, None, size, colour, annot.info.get("content", ""), xref)

    def close_text(self, editor, text):
        """Write what was typed, then remove the editor from the page."""
        if self._text is editor:
            self._text = None
        if self.viewer.text_editor is editor:
            self.viewer.text_editor = None
        editor.unparent()
        self.queue_allocate()
        self.queue_draw()
        self.grab_focus()
        if not text.strip():
            if editor.xref:
                self._edit(lambda doc: doc[self.index].delete_annot(doc[self.index].load_annot(editor.xref)))
            return
        size, colour = editor.size, editor.colour
        lines = wrap_text(text, size, editor.width)
        width = max(pymupdf.get_text_length(line, TEXT_FONT, size) for line in lines) + 3
        height = size * TEXT_LEADING * len(lines) + size * 0.45
        page_w, page_h = self.viewer.sizes[self.index]
        top = max(0, min(editor.shown_top, page_h - height - 1))
        shown = pymupdf.Rect(editor.left, top, editor.left + width, top + height)
        if editor.xref:
            old = self._page().load_annot(editor.xref)
            if old and old.info.get("content", "") == text and \
                    (size, colour) == _free_text_style(self._page().parent, editor.xref, self.viewer):
                return

        def change(doc):
            page = doc[self.index]
            if editor.xref:
                old = page.load_annot(editor.xref)
                if old:
                    page.delete_annot(old)
            rect = (shown * page.derotation_matrix).normalize()
            annot = page.add_freetext_annot(
                rect, text, fontsize=size, fontname=TEXT_FONT, text_color=colour,
                rotate=page.rotation)
            annot.set_info(title=_author())
            annot.update()
        self._edit(change)

    def _finish_note(self, x0, y0, x1, y1, click, **_):
        point = self.to_page(x0, y0)
        colour = self.viewer.colours["note"]

        def add(text):
            def change(doc):
                page = doc[self.index]
                annot = page.add_text_annot(point, text, icon="Comment")
                annot.set_colors(stroke=colour)
                annot.set_info(title=_author())
                annot.update()
            self._edit(change)
        self._text_popover(x0, y0, "Ajouter une note", "", add, multiline=True)

    # Popovers

    def _popover(self, x, y):
        popover = Gtk.Popover()
        popover.set_parent(self)
        popover.set_pointing_to(_gdk_rect(x, y, 1, 1))
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        return popover

    def _text_popover(self, x, y, title, text, done, multiline=False):
        popover = self._popover(x, y)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(6)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("h4")
        box.append(label)
        view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False)
        view.get_buffer().set_text(text)
        view.add_css_class("paraphe-note-entry")
        scroller = Gtk.ScrolledWindow(child=view, min_content_width=260, min_content_height=90)
        scroller.add_css_class("frame")
        box.append(scroller)
        button = Gtk.Button(label="Valider", halign=Gtk.Align.END)
        button.add_css_class("suggested-action")
        box.append(button)
        popover.set_child(box)

        def validate(*args):
            buffer = view.get_buffer()
            value = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
            popover.popdown()
            if value:
                done(value)
        button.connect("clicked", validate)
        keys = Gtk.EventControllerKey()

        def on_key(controller, keyval, code, state):
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.CONTROL_MASK:
                validate()
                return True
            return False
        keys.connect("key-pressed", on_key)
        view.add_controller(keys)
        popover.popup()
        view.grab_focus()

    def _annot_popover(self, xref, x, y):
        page = self._page()
        annot = page.load_annot(xref)
        if not annot:
            return
        popover = self._popover(x, y)
        box = Gtk.Box(spacing=6)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(4)
        kind = annot.type[0]
        if kind == pymupdf.PDF_ANNOT_FREE_TEXT:
            edit = Gtk.Button(label="Modifier")
            edit.connect("clicked", lambda b: (popover.popdown(), self.viewer.clear_selection(),
                                               self.edit_free_text(xref)))
            box.append(edit)
        elif kind == pymupdf.PDF_ANNOT_TEXT:
            edit = Gtk.Button(label="Modifier")
            edit.connect("clicked", lambda b: (popover.popdown(), self._edit_annot_text(xref, x, y)))
            box.append(edit)
        delete = Gtk.Button(label="Supprimer")
        delete.add_css_class("destructive-action")
        delete.connect("clicked", lambda b: (popover.popdown(), self.viewer.delete_selected_annot()))
        box.append(delete)
        popover.set_child(box)
        popover.popup()

    def _edit_annot_text(self, xref, x, y):
        page = self._page()
        annot = page.load_annot(xref)
        if not annot:
            return

        def done(text):
            def change(doc):
                page = doc[self.index]
                a = page.load_annot(xref)
                a.set_info(content=text)
                a.update()
            self._edit(change)
        self._text_popover(x, y, "Modifier le texte", annot.info.get("content", ""), done, multiline=True)

    # Form fields

    def _build_fields(self):
        page = self._page()
        for widget in page.widgets():
            kind = widget.field_type
            rect = pymupdf.Rect(widget.rect)
            if widget.field_flags & 1:  # read-only
                continue
            if kind in (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON):
                self._fields.append((widget.xref, kind, rect))
            elif kind in (pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                          pymupdf.PDF_WIDGET_TYPE_LISTBOX):
                editor = FieldEditor(self, widget)
                editor.set_parent(self)
                self._editors.append((editor, rect))

    def _toggle_field(self, xref, kind):
        def change(doc):
            page = doc[self.index]
            for widget in page.widgets():
                if widget.xref == xref:
                    on = widget.on_state()
                    if kind == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                        widget.field_value = on
                    else:
                        widget.field_value = False if widget.field_value not in (False, "Off", "") else on
                    widget.update()
        self._edit(change)

    def write_field(self, xref, value):
        def change(doc):
            page = doc[self.index]
            for widget in page.widgets():
                if widget.xref == xref:
                    widget.field_value = value
                    widget.update()
        self._edit(change)

    def commit_fields(self):
        for editor, _ in self._editors:
            editor.commit()

    def do_dispose(self):
        for editor, _ in self._editors:
            editor.unparent()
        self._editors = []
        if self._text:
            if self.viewer.text_editor is self._text:
                self.viewer.text_editor = None
            self._text.unparent()
            self._text = None
        Gtk.Widget.do_dispose(self)


class FieldEditor(Gtk.Box):
    """An entry, text view or drop-down laid over a form field."""

    __gtype_name__ = "ParapheFieldEditor"

    def __init__(self, page_view, widget):
        super().__init__()
        self.page_view = page_view
        self.xref = widget.xref
        self.kind = widget.field_type
        self.font = widget.text_fontsize or 0
        self._pending = None
        self.add_css_class("pdf-field")
        value = widget.field_value or ""
        if self.kind == pymupdf.PDF_WIDGET_TYPE_TEXT:
            if widget.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE:
                self.input = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True)
                self.input.get_buffer().set_text(str(value))
                self.input.get_buffer().connect("changed", self._on_changed)
            else:
                self.input = Gtk.Entry(text=str(value), hexpand=True, has_frame=False)
                self.input.set_width_chars(1)
                if widget.text_maxlen:
                    self.input.set_max_length(widget.text_maxlen)
                self.input.connect("changed", self._on_changed)
                self.input.connect("activate", lambda e: self.commit())
            focus = Gtk.EventControllerFocus()
            focus.connect("leave", lambda c: self.commit())
            self.input.add_controller(focus)
        else:
            choices = [c if isinstance(c, str) else c[1] for c in (widget.choice_values or [])]
            self.choices = choices
            self.input = Gtk.DropDown.new_from_strings(choices)
            self.input.set_hexpand(True)
            if value in choices:
                self.input.set_selected(choices.index(value))
            else:
                self.input.set_selected(Gtk.INVALID_LIST_POSITION)
            self.input.connect("notify::selected", self._on_selected)
        self.append(self.input)

    def set_zoom(self, zoom, height):
        size = self.font * zoom if self.font else min(height * 0.62, 14 * zoom)
        size = round(max(size, 6), 1)
        if size == getattr(self, "_size", None):
            return
        self._size = size
        # The font follows the zoom; a provider per field is the only way to
        # size a text view, and entries take it the same way.
        if not hasattr(self, "_css"):
            self._css = Gtk.CssProvider()
            self.input.get_style_context().add_provider(self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._css.load_from_string(f"* {{ font-size: {size}px; }}")

    def _on_changed(self, *args):
        if isinstance(self.input, Gtk.TextView):
            buffer = self.input.get_buffer()
            self._pending = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        else:
            self._pending = self.input.get_text()

    def _on_selected(self, dropdown, pspec):
        index = dropdown.get_selected()
        if index != Gtk.INVALID_LIST_POSITION:
            self.page_view.write_field(self.xref, self.choices[index])

    def commit(self):
        if self._pending is None:
            return
        value, self._pending = self._pending, None
        self.page_view.write_field(self.xref, value)


class TextEditor(Gtk.Box):
    """Free text typed on the page in the font, size and colour it will have,
    wrapped at the width of its box. Escape, Ctrl+Enter or a click elsewhere
    ends it."""

    __gtype_name__ = "ParapheTextEditor"

    def __init__(self, page_view, left, top, width, size, colour, text="", xref=None):
        super().__init__()
        self.page_view = page_view
        # Displayed page points; shown_top is top once kept inside the page.
        self.left, self.top, self.shown_top, self.width = left, top, top, width
        self.size, self.colour, self.xref = size, colour, xref
        self._done = False
        self._style = None
        self.add_css_class("text-editor")
        if xref:
            self.add_css_class("replacing")
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False, hexpand=True,
                                 left_margin=0, right_margin=0, top_margin=0, bottom_margin=0)
        self.view.get_buffer().set_text(text)
        self.view.get_buffer().connect("changed", lambda b: page_view.queue_allocate())
        self._css = Gtk.CssProvider()
        self.view.get_style_context().add_provider(self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.view.add_controller(keys)
        self.append(self.view)

    def set_zoom(self, zoom):
        r, g, b = (round(c * 255) for c in self.colour)
        style = (round(self.size * zoom, 2), r, g, b)
        if style == self._style:
            return
        self._style = style
        # Liberation Sans and Arimo share Helvetica's widths: lines break as in the PDF.
        self._css.load_from_string(
            f"* {{ font-family: Helvetica, 'Liberation Sans', Arimo, sans-serif; font-size: {style[0]}px; "
            f"line-height: {TEXT_LEADING}; color: rgb({r}, {g}, {b}); caret-color: rgb({r}, {g}, {b}); }}")

    def contains_point(self, x, y):
        zoom = self.page_view.zoom
        return (self.left * zoom - 6 <= x <= (self.left + self.width) * zoom + 6
                and self.shown_top * zoom - 6 <= y <= self.shown_top * zoom + self.get_height() + 6)

    def _on_key(self, controller, keyval, code, state):
        if keyval == Gdk.KEY_Escape or (
                keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.CONTROL_MASK):
            self.finish()
            return True
        return False

    def finish(self):
        if self._done:
            return
        self._done = True
        buffer = self.view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).rstrip()
        self.page_view.close_text(self, text)


def wrap_text(text, size, width):
    """Lines of text no wider than width points in the free text font,
    broken between words like the PDF viewer does, inside words if needed."""
    def length(s):
        return pymupdf.get_text_length(s, TEXT_FONT, size)
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in re.split(r"(?<= )", paragraph):
            if length(line + word.rstrip()) <= width or not line:
                line += word
            else:
                lines.append(line.rstrip())
                line = word
            while length(line.rstrip()) > width and len(line) > 1:
                cut = len(line) - 1
                while cut > 1 and length(line[:cut]) > width:
                    cut -= 1
                lines.append(line[:cut])
                line = line[cut:]
        lines.append(line.rstrip())
    return lines or [""]


def _free_text_style(doc, xref, viewer):
    """Font size and colour of a free text, read from its default appearance."""
    size, colour = viewer.text_size, viewer.colours["text"]
    kind, da = doc.xref_get_key(xref, "DA")
    if kind == "string":
        found = re.search(r"([\d.]+)\s+Tf", da)
        if found:
            size = float(found.group(1))
        found = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da)
        if found:
            colour = tuple(float(v) for v in found.groups())
        else:
            found = re.search(r"([\d.]+)\s+g\b", da)
            if found:
                colour = (float(found.group(1)),) * 3
    return size, colour


def _near(point, stroke, reach):
    """Whether point lies within reach of the polyline stroke."""
    if len(stroke) == 1:
        return math.hypot(point.x - stroke[0][0], point.y - stroke[0][1]) <= reach
    for (ax, ay), (bx, by) in zip(stroke, stroke[1:]):
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        t = 0 if span == 0 else max(0, min(1, ((point.x - ax) * dx + (point.y - ay) * dy) / span))
        if math.hypot(point.x - ax - t * dx, point.y - ay - t * dy) <= reach:
            return True
    return False


def Gsk_translate(x, y):
    from gi.repository import Gsk
    point = Graphene.Point()
    point.x, point.y = x, y
    return Gsk.Transform.new().translate(point)


def _box(x0, y0, x1, y1):
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)


def _fit_box(box, aspect):
    """The largest box of the given aspect centred in box."""
    x, y, w, h = box
    if w / max(h, 1) > aspect:
        nw = h * aspect
        return x + (w - nw) / 2, y, nw, h
    nh = w / aspect
    return x, y + (h - nh) / 2, w, nh


def _gdk_rect(x, y, w, h):
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), int(w), int(h)
    return rect


def _author():
    return GLib.get_real_name() or GLib.get_user_name()
