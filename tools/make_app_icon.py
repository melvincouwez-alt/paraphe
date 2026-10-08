#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Paraphe contributors
"""Draw Paraphe's icon (proposal F4) for each size, in the
theme's construction and without SVG filters, which GTK's icon renderer
ignores: square tile per size, silver gradient, 1 px darker outline, 1 px
white inner highlight, no shadow. The glyph is elementary's PDF
swoosh (from the theme's application-pdf icon, GPL-3.0) in red, with the
word PDF under it from 48 px up."""

import os

import cairo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
SWOOSH = open(os.path.join(HERE, "pdf_swoosh.txt")).read()
SW_X0, SW_X1, SW_Y0, SW_Y1 = 21.5, 109.5, 29.0, 88.5  # swoosh bounding box

TILES = {
    16: (2, 2, 12, 1.5),
    24: (3, 3, 18, 1.5),
    32: (3, 3, 26, 2.5),
    48: (5, 6, 38, 3.5),
    64: (5, 5, 54, 5.5),
    128: (13, 16, 102, 9.5),
}


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


def rect(x, y, w, h, r):
    return (f"M{x + r:g},{y:g} H{x + w - r:g} A{r:g},{r:g} 0 0 1 {x + w:g},{y + r:g} "
            f"V{y + h - r:g} A{r:g},{r:g} 0 0 1 {x + w - r:g},{y + h:g} H{x + r:g} "
            f"A{r:g},{r:g} 0 0 1 {x:g},{y + h - r:g} V{y + r:g} A{r:g},{r:g} 0 0 1 {x + r:g},{y:g} Z")


def icon(size):
    x, y, side, radius = TILES[size]
    one = 1 / side
    with_label = size >= 48
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}"><defs>'
         '<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fafafa"/><stop offset="1" stop-color="#d4d4d4"/></linearGradient>'
         '<linearGradient id="hl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.8"/>'
         f'<stop offset="{one:.4f}" stop-color="#fff" stop-opacity="0.24"/><stop offset="{1 - one:.4f}" stop-color="#fff" stop-opacity="0.12"/>'
         '<stop offset="1" stop-color="#fff" stop-opacity="0.3"/></linearGradient>'
         '<linearGradient id="red" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff6b63"/><stop offset="0.5" stop-color="#e33d3d"/><stop offset="1" stop-color="#a10705"/></linearGradient>'
         '</defs>']
    outer = rect(x + 0.5, y + 0.5, side - 1, side - 1, radius)
    p.append(f'<path d="{outer}" fill="url(#bg)"/>')
    inner = rect(x + 1.5, y + 1.5, side - 3, side - 3, max(radius - 1, 0.5))
    p.append(f'<path d="{inner}" fill="none" stroke="url(#hl)" stroke-width="1"/>')
    p.append(f'<path d="{outer}" fill="none" stroke="#000" stroke-opacity="0.3" stroke-width="1"/>')

    # Swoosh: 78 % of the tile wide, higher up when the label sits under it.
    width = side * (0.74 if with_label else 0.84)
    scale = width / (SW_X1 - SW_X0)
    height = (SW_Y1 - SW_Y0) * scale
    left = x + (side - width) / 2
    top = y + side * 0.16 if with_label else y + (side - height) / 2
    tx, ty = left - SW_X0 * scale, top - SW_Y0 * scale
    # userSpaceOnUse is avoided: a bounding-box gradient survives any scale.
    p.append(f'<path d="{SWOOSH}" transform="translate({tx:.3f} {ty:.3f}) scale({scale:.5f})" fill="url(#red)"/>')

    if with_label:
        font = side * 0.2
        base = y + side * 0.87
        d = text_path("PDF", font, x + side / 2, base, anchor="middle")
        p.append(f'<path d="{d}" fill="#c6262e"/>')
    p.append("</svg>")
    return "".join(p) + "\n"


if __name__ == "__main__":
    os.makedirs(os.path.join(DATA, "icons", "app"), exist_ok=True)
    for size in TILES:
        with open(os.path.join(DATA, "icons", "app", f"{size}.svg"), "w") as f:
            f.write(icon(size))
    with open(os.path.join(DATA, "io.github.melvincouwez.Paraphe.svg"), "w") as f:
        f.write(icon(128))
    print("icons drawn")
