"""Continuation indent that is as wide as the compact opening quote.

Proportional typography draws ``“`` and ``（`` at 75% of the native advance, while a
continuation row still starts with one full-width space, so in story dialogue row 2
sat 5px to the right of row 1. The stored text keeps that space; only its code changes
at the storage boundary: ``0x8140`` becomes ``CODE``, a blank glyph whose advance the
runtime metric table sets to the opener's advance. Two bytes either way.

``CODE`` is a raw-trail gap of the standard glyph formula. Its glyph is blank in the
stock font, the release-font policy never allocates raw-trail gaps, and neighbouring
gaps such as ``0x92FD`` and ``0x94FD`` already carry glyphs through every text
surface. It is the one such gap that no codebook, current or retired, has ever used.
"""

from __future__ import annotations

import re

from .text import control_notation_positions

# Pipeline-only marker for ``CODE``. Corpus text never contains it.
CHARACTER = "\ue001"
CODE = 0x93FD
GLYPH_INDEX = 3645
# Compact opening punctuation; each has the same advance as the indent.
OPENERS = "“‘（《【"

_ROW_START = re.compile("\n\u3000(?=[^\u3000 \n])")


def applies(text: str) -> bool:
    """Whether the line opens with compact punctuation and has indented rows."""

    if not isinstance(text, str):
        raise TypeError("dialogue text must be a string")
    if CHARACTER in text:
        raise ValueError("dialogue text already contains the continuation-indent marker")
    skipped = control_notation_positions(text)
    first = next((ch for i, ch in enumerate(text) if i not in skipped), "")
    return first in OPENERS and _ROW_START.search(text) is not None


def store(text: str) -> str:
    """Corpus text to stored text: mark the indent of each continuation row."""

    return _ROW_START.sub("\n" + CHARACTER, text) if applies(text) else text


def restore(text: str) -> str:
    """Stored text back to corpus text."""

    if not isinstance(text, str):
        raise TypeError("dialogue text must be a string")
    return text.replace(CHARACTER, "\u3000")
