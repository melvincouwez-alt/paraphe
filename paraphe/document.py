# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 melvincouwez-alt
"""The open PDF: a PyMuPDF document with undo, redo and saving.

Every change goes through edit(): the document is snapshotted before the
change, so undo reopens the previous bytes. Page revisions let the views
drop only the renders a change made stale.
"""

import os
import tempfile

import pymupdf
from gi.repository import GObject

UNDO_LIMIT = 30


class Document(GObject.Object):
    __gtype_name__ = "ParapheDocument"
    __gsignals__ = {
        # Pages were added, removed, moved or rotated: rebuild every view.
        "structure-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # The content of one page changed (annotation, field): -1 means all.
        "page-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, doc, path=None):
        super().__init__()
        self.doc = doc
        self.path = path
        self.modified = False
        self._undo = []
        self._redo = []
        self._revisions = {}

    # Opening

    @classmethod
    def open(cls, path, password=None):
        doc = pymupdf.open(path)
        if doc.needs_pass and not doc.authenticate(password or ""):
            doc.close()
            raise PermissionError(path)
        if not doc.is_pdf:
            # Images and other formats PyMuPDF reads become a PDF copy.
            pdf = pymupdf.open("pdf", doc.convert_to_pdf())
            doc.close()
            return cls(pdf, None)
        return cls(doc, path)

    @staticmethod
    def needs_password(path):
        with pymupdf.open(path) as doc:
            return doc.needs_pass

    @classmethod
    def merge(cls, paths):
        """A new, unsaved document made of every page of every file, in order."""
        out = pymupdf.open()
        for path in paths:
            with pymupdf.open(path) as src:
                if not src.is_pdf:
                    src = pymupdf.open("pdf", src.convert_to_pdf())
                out.insert_pdf(src)
        document = cls(out, None)
        document.modified = True
        return document

    # State

    @property
    def page_count(self):
        return self.doc.page_count

    @property
    def title(self):
        if self.path:
            return os.path.basename(self.path)
        return "Nouveau document"

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def revision(self, index):
        return self._revisions.get(index, 0)

    def has_signatures(self):
        for page in self.doc:
            for widget in page.widgets():
                if widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE and widget.is_signed:
                    return True
        return False

    # Changes

    def _snapshot(self):
        return self.doc.tobytes(garbage=0)

    def _restore(self, data):
        self.doc.close()
        self.doc = pymupdf.open("pdf", data)

    def edit(self, change, page=None):
        """Run change(doc) with an undo point. page is the one page touched,
        or None when the structure changes. Returns what change returns."""
        snapshot = self._snapshot()
        result = change(self.doc)
        self._undo.append(snapshot)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._touched(page)
        return result

    def _touched(self, page):
        self.modified = True
        if page is None:
            self._revisions = {i: self.revision(i) + 1 for i in range(self.page_count)}
            self.emit("structure-changed")
        else:
            self._revisions[page] = self.revision(page) + 1
            self.emit("page-changed", page)
        self.emit("state-changed")

    def undo(self):
        if self._undo:
            self._redo.append(self._snapshot())
            self._restore(self._undo.pop())
            self._touched(None)

    def redo(self):
        if self._redo:
            self._undo.append(self._snapshot())
            self._restore(self._redo.pop())
            self._touched(None)

    # Saving

    def save(self, path=None):
        path = path or self.path
        same_file = path == self.path and self.doc.name == path
        if same_file and self.doc.can_save_incrementally():
            # Incremental saving keeps existing digital signatures valid.
            self.doc.save(path, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        else:
            directory = os.path.dirname(os.path.abspath(path))
            fd, tmp = tempfile.mkstemp(prefix=".paraphe-", suffix=".pdf", dir=directory)
            os.close(fd)
            try:
                self.doc.save(tmp, garbage=3, deflate=True)
                os.replace(tmp, path)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
            self.doc.close()
            self.doc = pymupdf.open(path)
        self.path = path
        self.modified = False
        self.emit("state-changed")

    def save_copy(self, path, flatten=False, pages=None):
        """Write a copy without touching the open document. flatten burns
        annotations and fields into the pages; pages keeps only those."""
        copy = pymupdf.open("pdf", self._snapshot())
        try:
            if pages is not None:
                copy.select(sorted(pages))
            if flatten:
                copy.bake()
            copy.save(path, garbage=3, deflate=True)
        finally:
            copy.close()

    def split(self, ranges, directory, stem):
        """Write one file per range of 0-based page indexes. Returns the paths."""
        paths = []
        for number, indexes in enumerate(ranges, 1):
            path = os.path.join(directory, f"{stem}-{number}.pdf")
            self.save_copy(path, pages=indexes)
            paths.append(path)
        return paths

    def close(self):
        self.doc.close()
