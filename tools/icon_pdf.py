"""Pistes d'icônes « plus PDF » (série Q) : data/icon-proposals/q*.svg et planche."""
import re
import sys

import cairo

import icon_proposals as base
from icon_proposals import SIGN, lines, page, pen, svg

RED = """<linearGradient id="red" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d6474e"/><stop offset="1" stop-color="#ad2b33"/></linearGradient>
<linearGradient id="redsoft" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e0666b"/><stop offset="1" stop-color="#c0383f"/></linearGradient>"""
base.DEFS += RED


def text_path(text, size, x, y, family="Inter Display", weight=cairo.FONT_WEIGHT_BOLD, anchor="start"):
    """Text as an SVG path (no font needed at display time)."""
    surface = cairo.RecordingSurface(cairo.CONTENT_ALPHA, None)
    cr = cairo.Context(surface)
    cr.select_font_face(family, cairo.FONT_SLANT_NORMAL, weight)
    cr.set_font_size(size)
    ext = cr.text_extents(text)
    if anchor == "middle":
        x -= ext.x_bearing + ext.width / 2
    cr.move_to(x, y)
    cr.text_path(text)
    d = []
    for kind, pts in cr.copy_path():
        if kind == cairo.PATH_MOVE_TO:
            d.append("M%.2f %.2f" % pts)
        elif kind == cairo.PATH_LINE_TO:
            d.append("L%.2f %.2f" % pts)
        elif kind == cairo.PATH_CURVE_TO:
            d.append("C%.2f %.2f %.2f %.2f %.2f %.2f" % pts)
        else:
            d.append("Z")
    return "".join(d)


def label(text, x, y, size, fill="#fff", anchor="middle"):
    return f'<path d="{text_path(text, size, x, y, anchor=anchor)}" fill="{fill}"/>'


def sig(x, y, colour="#2b4a8a", width=3.4):
    return f'<path d="{SIGN.format(x=x, y=y)}" fill="none" stroke="{colour}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>'


def system_pdf(x=0, y=0, size=128):
    raw = open("/usr/share/icons/elementary/mimes/128/application-pdf.svg").read()
    raw = re.sub(r"<\?xml[^>]*>", "", raw)
    raw = re.sub(r'<svg ', f'<svg x="{x}" y="{y}" viewBox="0 0 128 128" ', raw, count=1)
    raw = re.sub(r'width="128" height="128"', f'width="{size}" height="{size}"', raw, count=1)
    return raw


Q = {}

# Q1 : fichier PDF classique, bandeau rouge « PDF » qui déborde à gauche, signature.
Q["Q1"] = ("Bandeau PDF", svg(page(24, 8, 84, 112, 20) + lines(34, 28, (30, 52, 52)) +
    '<g filter="url(#sh)"><rect x="14" y="60" width="62" height="28" rx="4" fill="url(#red)" stroke="#6e1419" stroke-opacity=".5"/></g>'
    + label("PDF", 45, 81, 21) + sig(40, 110, width=3)))

# Q2 : tuile rouge, « PDF » blanc et paraphe dessous.
Q["Q2"] = ("Tuile rouge", svg(
    '<g filter="url(#sh)"><rect x="13" y="12" width="102" height="102" rx="11" fill="url(#red)" stroke="#000" stroke-opacity=".3"/>'
    '<rect x="14" y="13" width="100" height="100" rx="10" fill="none" stroke="#fff" stroke-opacity=".2"/></g>'
    + label("PDF", 64, 60, 34) +
    '<path d="M34 90c6-9 10-20 14-20s-3 17 3 17 7-9 11-9-1 8 5 8 6-4 10-5" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>'))

# Q3 : page, coin plié rouge, « PDF » rouge en grand, plume.
Q["Q3"] = ("Coin rouge", svg(
    '<g filter="url(#sh)"><path d="M23 8h57l24 24v85a3 3 0 0 1-3 3H23a3 3 0 0 1-3-3V11a3 3 0 0 1 3-3z" fill="url(#paper)" stroke="#000" stroke-opacity=".2"/>'
    '<path d="M80 8v21a3 3 0 0 0 3 3h21z" fill="url(#red)" stroke="#6e1419" stroke-opacity=".4"/></g>'
    + label("PDF", 30, 66, 28, fill="#c0383f", anchor="start") + lines(31, 80, (46, 38)) + sig(30, 110, width=3)
    + pen(100, 92, 40, 0.8)))

# Q4 : page et tampon « PDF » incliné.
Q["Q4"] = ("Tampon PDF", svg(page() + lines(30, 28, (36, 58, 58, 42)) +
    '<g transform="rotate(-12 64 80)"><rect x="34" y="66" width="60" height="30" rx="5" fill="none" stroke="#c0383f" stroke-width="4"/>'
    + label("PDF", 64, 89, 22, fill="#c0383f") + '</g>' + sig(34, 112, width=3)))

# Q5 : tuile encre, page blanche avec pastille « PDF » rouge.
Q["Q5"] = ("Tuile encre + PDF", svg(
    '<g filter="url(#sh)"><rect x="13" y="12" width="102" height="102" rx="11" fill="url(#ink)" stroke="#000" stroke-opacity=".3"/></g>'
    '<path d="M38 26h36l16 16v58a3 3 0 0 1-3 3H38a3 3 0 0 1-3-3V29a3 3 0 0 1 3-3z" fill="#fff"/>'
    '<path d="M74 26v13a3 3 0 0 0 3 3h13z" fill="#d7deea"/>'
    + lines(43, 50, (30, 38), gap=9, colour="#c9d0db", h=3.5) +
    '<path d="M43 88c4-6 7-14 10-14s-2 12 2 12 5-6 8-6-1 6 3 6 4-3 7-4" fill="none" stroke="#2b4a8a" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
    '<g filter="url(#sh)"><rect x="62" y="68" width="42" height="24" rx="12" fill="url(#red)" stroke="#6e1419" stroke-opacity=".4"/></g>'
    + label("PDF", 83, 85, 15)))

# Q6 : grand « PDF » rouge seul sur page, souligné d'un trait de surligneur.
Q["Q6"] = ("PDF surligné", svg(page() +
    '<rect x="28" y="62" width="64" height="16" rx="3" fill="#f3cf55" opacity=".8"/>'
    + label("PDF", 60, 74, 34, fill="#b8323a") + lines(30, 28, (36, 52)) + sig(32, 106, width=3)))

# Q7 : pastille ronde rouge « PDF » et badge plume.
Q["Q7"] = ("Pastille PDF", svg(
    '<g filter="url(#sh)"><circle cx="64" cy="62" r="55" fill="url(#red)" stroke="#000" stroke-opacity=".3"/>'
    '<circle cx="64" cy="62" r="54" fill="none" stroke="#fff" stroke-opacity=".2"/></g>'
    + label("PDF", 64, 72, 36) +
    '<g filter="url(#sh)"><circle cx="100" cy="98" r="20" fill="url(#ink)" stroke="#000" stroke-opacity=".3"/></g>'
    '<g transform="translate(100 97) rotate(45) scale(.42)"><path d="M0 -40c14 12 18 30 14 44L4 34H-4L-14 4c-4-14 0-32 14-44z" fill="url(#gold)"/><path d="M0 -8v42" stroke="#6b4e14" stroke-width="3"/></g>'))

# Q8 : icône PDF du thème elementary et plume.
Q["Q8"] = ("PDF du thème + plume", svg(system_pdf() + pen(100, 90, 40, 0.8)))


if __name__ == "__main__":
    import os
    base.P = Q
    for code, (_, text) in Q.items():
        with open(os.path.join(base.OUT, f"{code.lower()}.svg"), "w") as f:
            f.write(text)
    base.sheet(sys.argv[1])
