# Paraphe

[Français](README.fr.md)

A PDF editor for elementary OS, written in Python with GTK 4 and Granite. The interface is in French.

- Annotate: highlight, underline, strike out, add text (8 to 24 pt), notes, freehand drawing and rectangles. Each tool keeps its own colour. With the selection tool you can move, edit or delete an annotation (Delete key).
- Fill in forms: single and multi-line text fields, check boxes, radio buttons, lists.
- Sign by hand: draw a signature, or import a scan whose background turns transparent. Signatures are kept in `~/.local/share/paraphe/signatures/` and placed with a click or by dragging their size.
- Sign with a certificate: PKCS#12 file (.p12, .pfx), visible signature (Noto Sans stamp) or invisible one, through pyHanko. As long as you save to the same file, saving is incremental and keeps existing signatures valid.
- "Pages" mode (Ctrl+Shift+P, button in the header bar): every page at a large size, reordered by drag and drop, with an action bar for the selection (insert a PDF, split, including after the chosen pages, extract, duplicate, rotate, delete). A file can also be dropped between two pages. The thumbnail column of the "Annotate" mode offers the same actions in its menu.
- Merge several PDF files, split a document (one page per file, every N pages, or by ranges), save a flattened copy where annotations and fields are fixed.
- Print (Ctrl+P, printer button) the document as shown, with annotations, filled-in fields and signatures.
- Undo and redo every change (Ctrl+Z, Ctrl+Shift+Z).

## Install

Download the `.deb` from the [latest release](https://github.com/melvincouwez-alt/paraphe/releases/latest), then:

```
sudo apt install ./paraphe_<version>_amd64.deb
```

## Run from source

```
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pymupdf "pyhanko[opentype]"
./run.sh file.pdf
```

You need `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0` and `gir1.2-granite-7.0`.

## Package

`packaging/build-deb.sh` builds `dist/paraphe_<version>_amd64.deb`. PyMuPDF and pyHanko are bundled in `/usr/lib/paraphe/vendor`.

## Tests

`tests/samples.py <folder>` creates sample PDF files (text, form, rotated page). To run the app without a visible window, start it in a headless gala on a private D-Bus session (`tests/nested.sh`). `PARAPHE_DEV_SCRIPT` then runs a Python script that receives the window, and `PARAPHE_DEV_CAPTURE` saves a PNG capture before quitting.

## License and credits

AGPL-3.0 or later, the license of PyMuPDF (Artifex), which Paraphe is built on.

- [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (Artifex): AGPL-3.0
- [pyHanko](https://github.com/MatthiasValvekens/pyHanko) (Matthias Valvekens): MIT
- [uharfbuzz](https://github.com/harfbuzz/uharfbuzz): Apache-2.0, and [fontTools](https://github.com/fonttools/fonttools): MIT, for the signature stamp
- GTK and [Granite](https://github.com/elementary/granite) (elementary)
- The icon reuses the PDF swoosh of the [elementary icons](https://github.com/elementary/icons) (GPL-3.0)
