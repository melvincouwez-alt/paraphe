# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 melvincouwez-alt
"""Small windows: password, splitting, certificate signing."""

import io
import os

from gi.repository import Gio, GLib, GObject, Gtk


def parse_ranges(text, page_count):
    """'1-3, 5, 8-' to [[0, 1, 2], [4], [7, ..., last]]. Raises ValueError."""
    ranges = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, _, end = part.partition("-")
            first = int(start) if start.strip() else 1
            last = int(end) if end.strip() else page_count
        else:
            first = last = int(part)
        if not 1 <= first <= last <= page_count:
            raise ValueError(part)
        ranges.append(list(range(first - 1, last)))
    if not ranges:
        raise ValueError(text)
    return ranges


def chunks(page_count, size):
    return [list(range(i, min(i + size, page_count))) for i in range(0, page_count, size)]


def _margins(widget, value=18):
    for side in ("top", "bottom", "start", "end"):
        getattr(widget, f"set_margin_{side}")(value)
    return widget


class _Dialog(Gtk.Window):
    def __init__(self, parent, title, action):
        super().__init__(transient_for=parent, modal=True, title=title, resizable=False,
                         default_width=420)
        header = Gtk.HeaderBar()
        header.add_css_class("flat")
        self.set_titlebar(header)
        self.body = _margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12))
        self.buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=6)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda b: self.close())
        self.buttons.append(cancel)
        self.ok = Gtk.Button(label=action)
        self.ok.add_css_class("suggested-action")
        self.buttons.append(self.ok)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self.body)
        outer.append(_margins(self.buttons, 0))
        self.buttons.set_margin_bottom(18)
        self.buttons.set_margin_end(18)
        self.set_child(outer)
        self.set_default_widget(self.ok)

    def error(self, text):
        if not hasattr(self, "_error"):
            self._error = Gtk.Label(wrap=True, xalign=0)
            self._error.add_css_class("error")
            self.body.append(self._error)
        self._error.set_label(text)


class PasswordDialog(_Dialog):
    __gtype_name__ = "ParaphePasswordDialog"
    __gsignals__ = {"password": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, parent, name):
        super().__init__(parent, "Document protégé", "Ouvrir")
        label = Gtk.Label(label=f"« {name} » est protégé par un mot de passe.", wrap=True, xalign=0)
        self.body.append(label)
        self.entry = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
        self.body.append(self.entry)
        self.ok.connect("clicked", self._done)

    def _done(self, button):
        self.emit("password", self.entry.get_text())
        self.close()


class SplitDialog(_Dialog):
    __gtype_name__ = "ParapheSplitDialog"
    __gsignals__ = {"split": (GObject.SignalFlags.RUN_FIRST, None, (object, str, str))}

    def __init__(self, parent, document, selected=()):
        super().__init__(parent, "Découper le document", "Découper")
        self.document = document
        self.selected = [i for i in selected if i < document.page_count - 1]
        count = document.page_count
        intro = Gtk.Label(label=f"Le document a {count} page{'s' if count > 1 else ''}.", xalign=0)
        intro.add_css_class("dim-label")
        self.body.append(intro)

        self.each = Gtk.CheckButton(label="Une page par fichier", active=not self.selected)
        self.body.append(self.each)
        self.after = Gtk.CheckButton(group=self.each, active=bool(self.selected),
                                     sensitive=bool(self.selected))
        if self.selected:
            pages = ", ".join(str(i + 1) for i in self.selected)
            self.after.set_label(f"Couper après la page {pages}" if len(self.selected) == 1
                                 else f"Couper après les pages {pages}")
        else:
            self.after.set_label("Couper après les pages sélectionnées (aucune)")
        self.body.append(self.after)
        every = Gtk.Box(spacing=6)
        self.every = Gtk.CheckButton(label="Toutes les", group=self.each)
        self.size = Gtk.SpinButton.new_with_range(1, max(count, 1), 1)
        self.size.set_value(min(2, count))
        every.append(self.every)
        every.append(self.size)
        every.append(Gtk.Label(label="pages"))
        self.body.append(every)
        ranges = Gtk.Box(spacing=6)
        self.by_ranges = Gtk.CheckButton(label="Selon ces plages :", group=self.each)
        self.ranges = Gtk.Entry(placeholder_text="1-3, 4, 5-", hexpand=True)
        self.ranges.connect("changed", lambda e: self.by_ranges.set_active(True))
        ranges.append(self.by_ranges)
        ranges.append(self.ranges)
        self.body.append(ranges)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6, margin_top=6)
        grid.attach(Gtk.Label(label="Nom", xalign=1), 0, 0, 1, 1)
        stem = os.path.splitext(document.title)[0]
        self.stem = Gtk.Entry(text=stem, hexpand=True)
        grid.attach(self.stem, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Dossier", xalign=1), 0, 1, 1, 1)
        self.folder = os.path.dirname(document.path) if document.path else GLib.get_user_special_dir(
            GLib.UserDirectory.DIRECTORY_DOCUMENTS) or GLib.get_home_dir()
        self.folder_button = Gtk.Button(label=os.path.basename(self.folder) or self.folder)
        self.folder_button.connect("clicked", self._pick_folder)
        grid.attach(self.folder_button, 1, 1, 1, 1)
        self.body.append(grid)
        hint = Gtk.Label(label=f"Fichiers créés : {stem}-1.pdf, {stem}-2.pdf…", xalign=0)
        hint.add_css_class("dim-label")
        hint.add_css_class("small-label")
        self.stem.connect("changed", lambda e: hint.set_label(
            f"Fichiers créés : {e.get_text()}-1.pdf, {e.get_text()}-2.pdf…"))
        self.body.append(hint)
        self.ok.connect("clicked", self._done)

    def _pick_folder(self, button):
        dialog = Gtk.FileDialog(title="Dossier des fichiers découpés",
                                initial_folder=Gio.File.new_for_path(self.folder))

        def done(dialog, result):
            try:
                self.folder = dialog.select_folder_finish(result).get_path()
            except GLib.Error:
                return
            self.folder_button.set_label(os.path.basename(self.folder) or self.folder)
        dialog.select_folder(self, None, done)

    def _done(self, button):
        count = self.document.page_count
        if self.after.get_active():
            cuts = [-1] + self.selected + [count - 1]
            ranges = [list(range(a + 1, b + 1)) for a, b in zip(cuts, cuts[1:]) if b > a]
        elif self.each.get_active():
            ranges = chunks(count, 1)
        elif self.every.get_active():
            ranges = chunks(count, int(self.size.get_value()))
        else:
            try:
                ranges = parse_ranges(self.ranges.get_text(), count)
            except ValueError:
                self.error(f"Plages non comprises. Exemple : 1-3, 4, 5-{count}")
                return
        stem = self.stem.get_text().strip() or "document"
        self.emit("split", ranges, self.folder, stem)
        self.close()


class CertificateDialog(_Dialog):
    """Sign with a PKCS#12 certificate (.p12 or .pfx) through pyHanko."""

    __gtype_name__ = "ParapheCertificateDialog"
    __gsignals__ = {"ready": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self, parent):
        super().__init__(parent, "Signature numérique", "Continuer")
        intro = Gtk.Label(
            label="Signe le document avec votre certificat. Toute modification ultérieure "
                  "du fichier rendra la signature invalide.", wrap=True, xalign=0, max_width_chars=50)
        intro.add_css_class("dim-label")
        self.body.append(intro)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.certificate = None
        self.cert_button = Gtk.Button(label="Choisir…", hexpand=True)
        self.cert_button.connect("clicked", self._pick)
        self.password = Gtk.PasswordEntry(show_peek_icon=True)
        self.reason = Gtk.Entry(placeholder_text="Facultatif")
        self.location = Gtk.Entry(placeholder_text="Facultatif")
        self.visible = Gtk.CheckButton(label="Signature visible : tracer sa place sur la page", active=True)
        for row, (label, widget) in enumerate((("Certificat", self.cert_button),
                                               ("Mot de passe", self.password),
                                               ("Motif", self.reason), ("Lieu", self.location))):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        self.body.append(grid)
        self.body.append(self.visible)
        self.ok.connect("clicked", self._done)

    def _pick(self, button):
        dialog = Gtk.FileDialog(title="Certificat PKCS#12")
        filt = Gtk.FileFilter(name="Certificats (.p12, .pfx)")
        filt.add_pattern("*.p12")
        filt.add_pattern("*.pfx")
        filt.add_pattern("*.P12")
        filt.add_pattern("*.PFX")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(filt)
        dialog.set_filters(store)

        def done(dialog, result):
            try:
                self.certificate = dialog.open_finish(result).get_path()
            except GLib.Error:
                return
            self.cert_button.set_label(os.path.basename(self.certificate))
        dialog.open(self, None, done)

    def _done(self, button):
        if not self.certificate:
            self.error("Choisissez d'abord un fichier de certificat.")
            return
        try:
            load_signer(self.certificate, self.password.get_text())
        except ValueError as error:
            self.error(str(error))
            return
        self.emit("ready", {
            "certificate": self.certificate, "password": self.password.get_text(),
            "reason": self.reason.get_text().strip(), "location": self.location.get_text().strip(),
            "visible": self.visible.get_active()})
        self.close()


def load_signer(path, password):
    from pyhanko.sign import signers
    try:
        signer = signers.SimpleSigner.load_pkcs12(path, passphrase=password.encode() or None)
    except Exception as error:  # pyHanko raises several kinds here
        raise ValueError("Impossible de lire ce certificat.") from error
    if signer is None:
        raise ValueError("Certificat illisible ou mot de passe incorrect.")
    return signer


# Font of the visible signature stamp. pyHanko lays out Inter, Open Sans and
# DejaVu with wrong advances (letters spread apart, text cut); Noto Sans comes
# out right. Without it pyHanko keeps its Courier.
STAMP_FONTS = (
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
)


def _stamp_text_style():
    """Text style of the visible signature stamp, in the first available font."""
    from pyhanko.pdf_utils.text import TextBoxStyle
    try:
        from pyhanko.pdf_utils.font.opentype import GlyphAccumulatorFactory
    except ImportError:  # pyHanko installed without its [opentype] extra
        return TextBoxStyle()
    for path in STAMP_FONTS:
        if os.path.exists(path):
            return TextBoxStyle(font=GlyphAccumulatorFactory(path), font_size=9)
    return TextBoxStyle()


def sign_pdf(data, output, options, page=None, box=None):
    """Sign the PDF bytes into output. box is (x0, y0, x1, y1) in PDF user space."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    from pyhanko.stamp import TextStampStyle

    signer = load_signer(options["certificate"], options["password"])
    writer = IncrementalPdfFileWriter(io.BytesIO(data), strict=False)
    existing = {name for name, *_ in fields.enumerate_sig_fields(writer)}
    number = 1
    while f"Signature{number}" in existing:
        number += 1
    name = f"Signature{number}"
    if box is not None:
        fields.append_signature_field(writer, fields.SigFieldSpec(name, on_page=page, box=box))
    meta = signers.PdfSignatureMetadata(
        field_name=name, reason=options.get("reason") or None,
        location=options.get("location") or None)
    style = TextStampStyle(stamp_text="Signé numériquement par\n%(signer)s\nle %(ts)s",
                           timestamp_format="%d/%m/%Y %H:%M", text_box_style=_stamp_text_style())
    pdf_signer = signers.PdfSigner(meta, signer=signer, stamp_style=style)
    with open(output, "wb") as f:
        pdf_signer.sign_pdf(writer, output=f)
