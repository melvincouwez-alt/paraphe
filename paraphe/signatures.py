# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Paraphe contributors
"""Handwritten signatures: drawn once, kept, placed on any page.

A drawn signature is a list of strokes normalised to its bounding box and
goes on the page as an ink annotation, so it stays vector and can be moved
or deleted. An imported image goes in as page content.
Signatures live in ~/.local/share/paraphe/signatures/.
"""

import json
import math
import os
import uuid

import cairo
import pymupdf
from gi.repository import Gdk, GLib, GObject, Graphene, Gtk

INK = (0.07, 0.16, 0.42)
PAD_WIDTH, PAD_HEIGHT = 560, 220


def store_dir():
    path = os.path.join(GLib.get_user_data_dir(), "paraphe", "signatures")
    os.makedirs(path, exist_ok=True)
    return path


class Signature:
    def __init__(self, ident, kind, aspect, strokes=None, width=0.03, image=None):
        self.id = ident
        self.kind = kind          # "ink" or "image"
        self.aspect = aspect      # width / height
        self.strokes = strokes or []  # points in 0..1 of the box
        self.width = width        # pen width, fraction of the box height
        self.image = image        # path of the PNG for an image signature

    # Storage

    @classmethod
    def load_all(cls):
        signatures = []
        directory = store_dir()
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(directory, name)) as f:
                    data = json.load(f)
                image = data.get("image")
                if image:
                    image = os.path.join(directory, image)
                signatures.append(cls(data["id"], data["kind"], data["aspect"],
                                      data.get("strokes"), data.get("width", 0.03), image))
            except (OSError, ValueError, KeyError):
                continue
        return signatures

    def save(self):
        data = {"id": self.id, "kind": self.kind, "aspect": self.aspect,
                "strokes": self.strokes, "width": self.width,
                "image": os.path.basename(self.image) if self.image else None}
        with open(os.path.join(store_dir(), f"{self.id}.json"), "w") as f:
            json.dump(data, f)

    def delete(self):
        directory = store_dir()
        for path in (os.path.join(directory, f"{self.id}.json"), self.image):
            if path and os.path.exists(path):
                os.unlink(path)

    @classmethod
    def from_strokes(cls, strokes, pen):
        """strokes in pad pixels; pen is the pen width in pixels."""
        points = [p for s in strokes for p in s]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        margin = pen
        x0, y0 = min(xs) - margin, min(ys) - margin
        w = max(max(xs) - min(xs) + 2 * margin, 1)
        h = max(max(ys) - min(ys) + 2 * margin, 1)
        normalised = [[((x - x0) / w, (y - y0) / h) for x, y in s] for s in strokes]
        signature = cls(uuid.uuid4().hex, "ink", w / h, normalised, pen / h)
        signature.save()
        return signature

    @classmethod
    def from_image(cls, path):
        """A scan or photo: the paper turns transparent, the ink stays."""
        pix = pymupdf.Pixmap(path)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        if pix.colorspace.n != 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        rgb = pix.samples
        out = bytearray(len(rgb) // 3 * 4)
        for i in range(len(rgb) // 3):
            r, g, b = rgb[3 * i:3 * i + 3]
            darkness = 255 - (r * 299 + g * 587 + b * 114) // 1000
            # Light paper (darkness under 40) goes fully transparent.
            alpha = 0 if darkness < 40 else min(255, (darkness - 40) * 2)
            out[4 * i:4 * i + 4] = bytes((r, g, b, alpha))
        clean = pymupdf.Pixmap(pymupdf.csRGB, pix.width, pix.height, bytes(out), 1)
        ident = uuid.uuid4().hex
        target = os.path.join(store_dir(), f"{ident}.png")
        clean.save(target)
        signature = cls(ident, "image", pix.width / max(pix.height, 1), image=target)
        signature.save()
        return signature

    # Drawing on screen

    def draw(self, cr, box, alpha=1.0):
        x, y, w, h = box
        if self.kind == "image":
            surface = self._surface()
            if surface:
                cr.save()
                cr.translate(x, y)
                cr.scale(w / surface.get_width(), h / surface.get_height())
                cr.set_source_surface(surface, 0, 0)
                cr.paint_with_alpha(alpha)
                cr.restore()
            return
        cr.set_source_rgba(*INK, alpha)
        cr.set_line_width(max(self.width * h, 0.8))
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for stroke in self.strokes:
            if not stroke:
                continue
            cr.move_to(x + stroke[0][0] * w, y + stroke[0][1] * h)
            if len(stroke) == 1:
                cr.line_to(x + stroke[0][0] * w + 0.1, y + stroke[0][1] * h)
            for px, py in stroke[1:]:
                cr.line_to(x + px * w, y + py * h)
            cr.stroke()

    def _surface(self):
        if not getattr(self, "_cached", None) and self.image and os.path.exists(self.image):
            self._cached = _surface_from_file(self.image)
        return getattr(self, "_cached", None)

    def preview(self, height=48):
        width = int(height * self.aspect)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(width, 1), height)
        cr = cairo.Context(surface)
        self.draw(cr, (0, 0, width, height))
        surface.flush()
        return Gdk.MemoryTexture.new(
            width, height, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
            GLib.Bytes.new(bytes(surface.get_data())), surface.get_stride())

    # Placing on a page

    def placement(self, box, zoom, page):
        """A function that puts the signature on the page. box is in widget
        pixels at the given zoom, in displayed (rotated) space."""
        x, y, w, h = (v / zoom for v in box)
        derotate = page.derotation_matrix
        if self.kind == "image":
            shown = pymupdf.Rect(x, y, x + w, y + h)
            rect = (shown * derotate).normalize()
            image, rotation = self.image, page.rotation

            def place(p):
                p.insert_image(rect, filename=image, rotate=-rotation % 360)
            return place
        strokes = [[tuple(pymupdf.Point(x + px * w, y + py * h) * derotate) for px, py in s]
                   for s in self.strokes if s]
        # A dot needs two points to draw.
        strokes = [s if len(s) > 1 else [s[0], (s[0][0] + 0.2, s[0][1])] for s in strokes]
        width = max(self.width * h, 0.6)

        def place(p):
            annot = p.add_ink_annot(strokes)
            annot.set_colors(stroke=INK)
            annot.set_border(width=width)
            annot.set_info(title=GLib.get_real_name() or GLib.get_user_name(), subject="Signature")
            annot.update()
        return place


def _surface_from_file(path):
    pix = pymupdf.Pixmap(path)
    if pix.colorspace and pix.colorspace.n != 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if not pix.alpha:
        pix = pymupdf.Pixmap(pix, 1)
    data = bytearray(pix.samples)
    # RGBA to cairo's premultiplied BGRA.
    for i in range(0, len(data), 4):
        r, g, b, a = data[i:i + 4]
        data[i:i + 4] = bytes((b * a // 255, g * a // 255, r * a // 255, a))
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, pix.width, pix.height, pix.width * 4)


class SignaturePad(Gtk.Window):
    """Draw a signature with the mouse, a touchpad or a pen."""

    __gtype_name__ = "ParapheSignaturePad"
    __gsignals__ = {"created": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    PEN = 3.0

    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True, title="Nouvelle signature",
                         default_width=PAD_WIDTH + 48, resizable=False)
        self.strokes = []
        header = Gtk.HeaderBar()
        header.add_css_class("flat")
        self.set_titlebar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(18)
        hint = Gtk.Label(label="Signez dans le cadre avec la souris, le pavé tactile ou un stylet.", xalign=0)
        hint.add_css_class("dim-label")
        box.append(hint)

        self.area = Gtk.DrawingArea(content_width=PAD_WIDTH, content_height=PAD_HEIGHT)
        self.area.add_css_class("signature-pad")
        self.area.set_draw_func(self._draw)
        self.area.set_cursor_from_name("crosshair")
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", lambda *a: self._changed())
        self.area.add_controller(drag)
        frame = Gtk.Frame(child=self.area)
        box.append(frame)

        actions = Gtk.Box(spacing=6)
        clear = Gtk.Button(label="Effacer")
        clear.connect("clicked", self._clear)
        actions.append(clear)
        undo = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Annuler le dernier trait")
        undo.connect("clicked", self._undo)
        actions.append(undo)
        spacer = Gtk.Box(hexpand=True)
        actions.append(spacer)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda b: self.close())
        actions.append(cancel)
        self.save = Gtk.Button(label="Enregistrer", sensitive=False)
        self.save.add_css_class("suggested-action")
        self.save.connect("clicked", self._save)
        actions.append(self.save)
        box.append(actions)
        self.set_child(box)

    def _begin(self, gesture, x, y):
        self._origin = (x, y)
        self.strokes.append([(x, y)])
        self.area.queue_draw()

    def _update(self, gesture, dx, dy):
        x, y = self._origin[0] + dx, self._origin[1] + dy
        last = self.strokes[-1][-1]
        if math.hypot(x - last[0], y - last[1]) >= 1.5:
            self.strokes[-1].append((x, y))
            self.area.queue_draw()

    def _changed(self):
        self.save.set_sensitive(bool(self.strokes))
        self.area.queue_draw()

    def _clear(self, button):
        self.strokes = []
        self._changed()

    def _undo(self, button):
        if self.strokes:
            self.strokes.pop()
        self._changed()

    def _draw(self, area, cr, width, height):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        # Baseline, as on paper.
        cr.set_source_rgba(0, 0, 0, 0.18)
        cr.set_line_width(1)
        cr.move_to(24, height * 0.72 + 0.5)
        cr.line_to(width - 24, height * 0.72 + 0.5)
        cr.stroke()
        cr.set_source_rgb(*INK)
        cr.set_line_width(self.PEN)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for stroke in self.strokes:
            cr.move_to(*stroke[0])
            if len(stroke) == 1:
                cr.line_to(stroke[0][0] + 0.1, stroke[0][1])
            for point in stroke[1:]:
                cr.line_to(*point)
            cr.stroke()

    def _save(self, button):
        if self.strokes:
            self.emit("created", Signature.from_strokes(self.strokes, self.PEN))
        self.close()


class SignatureMenu(Gtk.MenuButton):
    """Palette button: saved signatures as cards, new ones, certificate signing."""

    __gtype_name__ = "ParapheSignatureMenu"
    __gsignals__ = {
        "chosen": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "certificate": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(icon_name="paraphe-signature-symbolic", tooltip_text="Signer",
                         direction=Gtk.ArrowType.UP)
        self.popover = Gtk.Popover()
        self.popover.add_css_class("signature-panel")
        self.set_popover(self.popover)
        # Built now and after each change, never while the popover opens:
        # a popover whose child changes as it is shown can come up empty.
        self.refresh()

    def set_active_look(self, active):
        if active:
            self.add_css_class("active-tool")
        else:
            self.remove_css_class("active-tool")

    def refresh(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12,
                      margin_bottom=10, margin_start=12, margin_end=12)
        title = Gtk.Label(label="Signatures", xalign=0)
        title.add_css_class("section-title")
        box.append(title)

        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2,
                           min_children_per_line=2, column_spacing=8, row_spacing=8,
                           homogeneous=True)
        for signature in Signature.load_all():
            grid.append(self._card(signature))
        new = Gtk.Button(tooltip_text="Dessiner une signature")
        new.add_css_class("signature-card")
        new.add_css_class("new-card")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        inner.append(Gtk.Image(icon_name="list-add-symbolic", pixel_size=16))
        inner.append(Gtk.Label(label="Dessiner"))
        new.set_child(inner)
        new.connect("clicked", self._draw_new)
        grid.append(new)
        box.append(grid)

        for icon, label, handler in (
                ("insert-image-symbolic", "Importer une image de signature…", self._import),
                ("channel-secure-symbolic", "Signer avec un certificat…", self._certificate)):
            button = Gtk.Button()
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Image(icon_name=icon))
            row.append(Gtk.Label(label=label, xalign=0))
            button.set_child(row)
            button.add_css_class("flat")
            button.connect("clicked", handler)
            box.append(button)
        self.popover.set_child(box)

    def _card(self, signature):
        overlay = Gtk.Overlay()
        pick = Gtk.Button(tooltip_text="Placer cette signature")
        pick.add_css_class("signature-card")
        picture = Gtk.Picture.new_for_paintable(signature.preview(44))
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        pick.set_child(picture)
        pick.connect("clicked", self._choose, signature)
        overlay.set_child(pick)
        delete = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Supprimer cette signature",
                            halign=Gtk.Align.END, valign=Gtk.Align.START)
        delete.add_css_class("card-delete")
        delete.add_css_class("circular")
        delete.connect("clicked", self._delete, signature)
        overlay.add_overlay(delete)
        return overlay

    def _choose(self, button, signature):
        self.popover.popdown()
        self.emit("chosen", signature)

    def _delete(self, button, signature):
        signature.delete()
        self.refresh()

    def _draw_new(self, button):
        self.popover.popdown()
        pad = SignaturePad(self.get_root())

        def created(pad, signature):
            self.refresh()
            self.emit("chosen", signature)
        pad.connect("created", created)
        pad.present()

    def _import(self, button):
        self.popover.popdown()
        dialog = Gtk.FileDialog(title="Image de signature")
        images = Gtk.FileFilter(name="Images")
        for mime in ("image/png", "image/jpeg"):
            images.add_mime_type(mime)
        dialog.set_filters(Gio_list_store(images))

        def done(dialog, result):
            try:
                file = dialog.open_finish(result)
            except GLib.Error:
                return
            signature = Signature.from_image(file.get_path())
            self.refresh()
            self.emit("chosen", signature)
        dialog.open(self.get_root(), None, done)

    def _certificate(self, button):
        self.popover.popdown()
        self.emit("certificate")


def Gio_list_store(*filters):
    from gi.repository import Gio
    store = Gio.ListStore.new(Gtk.FileFilter)
    for f in filters:
        store.append(f)
    return store
