# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build sample PDFs for tests: text pages, a form, a rotated page."""
import sys

import pymupdf

LOREM = ("Paraphe est un outil pour annoter, remplir et signer des documents PDF. "
         "Ce paragraphe sert à tester la sélection de texte sur plusieurs lignes, "
         "le surlignage, le soulignement et le texte barré.")


def text_pdf(path, pages=4):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 80), f"Page {i + 1}", fontsize=22)
        page.insert_textbox(pymupdf.Rect(72, 110, 520, 400), LOREM * 2, fontsize=12)
    doc[2].set_rotation(90)
    doc.save(path)


def form_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 70), "Formulaire de test", fontsize=18)
    y = 110
    for label, kind, name, extra in (
            ("Nom", pymupdf.PDF_WIDGET_TYPE_TEXT, "nom", {}),
            ("Ville", pymupdf.PDF_WIDGET_TYPE_TEXT, "ville", {}),
            ("J'accepte", pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "accord", {}),
            ("Pays", pymupdf.PDF_WIDGET_TYPE_COMBOBOX, "pays", {"choice_values": ["France", "Belgique", "Suisse"]}),
            ("Commentaire", pymupdf.PDF_WIDGET_TYPE_TEXT, "commentaire", {"multi": True})):
        page.insert_text((72, y + 14), label, fontsize=12)
        w = pymupdf.Widget()
        w.field_type = kind
        w.field_name = name
        height = 60 if extra.get("multi") else 20
        w.rect = pymupdf.Rect(180, y, 180 + (20 if kind == pymupdf.PDF_WIDGET_TYPE_CHECKBOX else 260), y + (20 if kind == pymupdf.PDF_WIDGET_TYPE_CHECKBOX else height))
        if "choice_values" in extra:
            w.choice_values = extra["choice_values"]
        if extra.get("multi"):
            w.field_flags = pymupdf.PDF_TX_FIELD_IS_MULTILINE
        w.text_fontsize = 11
        page.add_widget(w)
        y += height + 16
    doc.save(path)


if __name__ == "__main__":
    out = sys.argv[1]
    text_pdf(f"{out}/texte.pdf")
    form_pdf(f"{out}/formulaire.pdf")
