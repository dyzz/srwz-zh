"""Two-byte text layout metrics; encoding and visible advancement stay separate."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import CONTROL_NOTATION, normalize_original_fullwidth_ascii

_DIMENSION = re.compile(r"<(width|space):([0-9A-Fa-f]{2})>\Z")
_LATIN_RUN = re.compile(r"[A-Za-z0-9]+(?:[ ._'/　-][A-Za-z0-9]+)*")


@dataclass(frozen=True)
class RendererState:
    advance_px: int
    glyph_width_px: int


@dataclass(frozen=True)
class TextExtent:
    advance_px: int
    occupied_px: int
    state: RendererState


def text_extent(text: str, *, default_advance_px: int,
                state: RendererState | None = None,
                placeholder_cells: int = 6,
                stage_keyword_links: bool = False) -> TextExtent:
    """Measure advancement and rightmost glyph edge, including inline state.

    Widths are conservative glyph rectangles, not font-ink bounding boxes.
    The caller supplies the renderer's default; no Unicode-width heuristic is
    used. Newlines must be measured by the caller as separate physical rows.
    """
    if not 1 <= default_advance_px <= 63:
        raise ValueError('default advance must be between 1 and 63 pixels')
    current = state or RendererState(default_advance_px, default_advance_px)
    advance = occupied = index = 0
    while index < len(text):
        match = CONTROL_NOTATION.match(text, index)
        if match:
            token = match.group()
            dimension = _DIMENSION.fullmatch(token)
            if dimension:
                value = int(dimension[2], 16)
                if not 1 <= value <= 63:
                    raise ValueError(f'invalid renderer dimension: {token}')
                current = RendererState(
                    value if dimension[1] == 'space' else current.advance_px,
                    value if dimension[1] == 'width' else current.glyph_width_px,
                )
            elif token.startswith(('$', '%')):
                # String placeholders keep the existing conservative six-cell
                # contract; callers with numeric templates need their own bound.
                occupied = max(occupied, advance + (placeholder_cells-1)*current.advance_px + current.glyph_width_px)
                advance += placeholder_cells * current.advance_px
            index = match.end()
            continue
        ch = text[index]
        if ch in '\n\r':
            raise ValueError('text_extent accepts one physical row')
        if not (stage_keyword_links and ch in '《》'):
            if ch not in '　 ':
                occupied = max(occupied, advance + current.glyph_width_px)
            advance += current.advance_px
        index += 1
    return TextExtent(advance, max(advance, occupied), current)


def compact_latin_runs(text: str, *, default_advance_px: int,
                       minimum_characters: int = 3,
                       glyph_width_px: int = 14,
                       advance_px: int = 12) -> str:
    """Author explicit width scopes for long Latin identifiers/phrases.

    Latin runs longer than two visible characters are compacted by default.
    Short IDs and digits alone retain their logical values. Controlled text
    must be authored separately. This helper is not a production-wide rewrite.
    """
    if CONTROL_NOTATION.search(text):
        raise ValueError('compact authoring requires plain text without controls')
    if minimum_characters < 2 or not 1 <= advance_px <= glyph_width_px <= default_advance_px <= 63:
        raise ValueError('invalid compact Latin metrics')
    folded = normalize_original_fullwidth_ascii(text)
    def replace(match):
        run = match.group().replace('　', ' ')
        if len(run) < minimum_characters or not any(c.isalpha() for c in run):
            return run
        return (f'<width:{glyph_width_px:02X}><space:{advance_px:02X}>' + run +
                f'<width:{default_advance_px:02X}><space:{default_advance_px:02X}>')
    return _LATIN_RUN.sub(replace, folded)
