# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Paraphe contributors
"""Text selection between two points, on the words PyMuPDF extracts.

A word is (x0, y0, x1, y1, text, block, line, number), in unrotated page
space and in reading order. The selection runs from the word nearest the
start point to the word nearest the end point, like a text editor.
"""

import pymupdf

# How far from a word a drag may start and still select text, in points.
REACH = 24


def _distance(word, point):
    dx = max(word[0] - point.x, 0, point.x - word[2])
    dy = max(word[1] - point.y, 0, point.y - word[3])
    return (dx * dx + dy * dy) ** 0.5


def _nearest(words, point):
    best, index = None, None
    for i, word in enumerate(words):
        d = _distance(word, point)
        if best is None or d < best:
            best, index = d, i
    return index, best


def select(words, start, stop):
    """The words between start and stop, or [] when the drag is not on text."""
    if not words:
        return []
    first, d1 = _nearest(words, start)
    last, d2 = _nearest(words, stop)
    if min(d1, d2) > REACH:
        return []
    if first > last:
        first, last = last, first
    return list(words[first:last + 1])


def _lines(words):
    lines = []
    key = None
    for word in words:
        k = (word[5], word[6])
        if k != key:
            lines.append([])
            key = k
        lines[-1].append(word)
    return lines


def line_rects(words):
    """One rectangle per line of the selection."""
    rects = []
    for line in _lines(words):
        rect = pymupdf.Rect(line[0][:4])
        for word in line[1:]:
            rect |= pymupdf.Rect(word[:4])
        rects.append(rect)
    return rects


def as_text(words):
    return "\n".join(" ".join(w[4] for w in line) for line in _lines(words))
