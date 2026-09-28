"""Two-byte text layout metrics; encoding and visible advancement stay separate."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import CONTROL_NOTATION, normalize_original_fullwidth_ascii

_DIMENSION = re.compile(r"<(width|space):([0-9A-Fa-f]{2})>\Z")
# Only expression/identifier punctuation belongs to compact scopes. Chinese
# sentence punctuation remains outside; in particular U+FF0C is not a digit
# grouping separator. Keep this alphabet shared with the layout tokenizer.
COMPACT_SCOPE_CHARACTERS = r"A-Za-z0-9Ａ-Ｚａ-ｚ０-９ .,:：．_'/／＋+％%~～〜×÷±＝=　－−·《》-"
_COMPACT_ALNUM = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[A-Za-z0-9]+)"
COMPACT_VISIBLE_RUN = re.compile(
    rf"[+＋－±-]?{_COMPACT_ALNUM}"
    rf"(?:[ .:：．_'/／＋+~～〜×÷±＝=　－-]{_COMPACT_ALNUM})*[%％]?"
)


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


def compact_visible_runs(text: str, *, default_advance_px: int,
                       minimum_characters: int = 3,
                       glyph_width_px: int = 14,
                       advance_px: int = 12,
                       breakable_phrases: tuple[str, ...] = ()) -> str:
    """Author closed width scopes for Latin, numbers and expression symbols.

    Runs longer than two visible characters are compacted by default, including
    pure numbers, times, decimals, percentages and fractions. Logical values
    and sentence punctuation are retained. Controlled text must be authored
    separately. This helper is not a production-wide rewrite.

    Explicitly selected English full names may have independently closed word
    scopes. This offers word boundaries to the layout solver while preserving
    every letter and space. Other identifiers remain indivisible.
    """
    if CONTROL_NOTATION.search(text):
        raise ValueError('compact authoring requires plain text without controls')
    if minimum_characters < 2 or not 1 <= advance_px <= glyph_width_px <= default_advance_px <= 63:
        raise ValueError('invalid compact visible-text metrics')
    folded = normalize_original_fullwidth_ascii(text)
    def replace(match):
        run = match.group().replace('　', ' ')
        # The division bar loses legibility in the tested 14px rendering.
        # Preserve its whole expression until a readable surface metric is set.
        if len(run) < minimum_characters or '÷' in run:
            return run
        # "%<width:XX>" is an existing lossless runtime-format notation.
        # Restore advance first after a literal percent so its visible glyph
        # cannot be mistaken for that token. Both orders restore the same state.
        restore = (f'<space:{default_advance_px:02X}><width:{default_advance_px:02X}>'
                   if run.endswith('%') else
                   f'<width:{default_advance_px:02X}><space:{default_advance_px:02X}>')
        pieces = re.findall(r'\S+[ ]*', run) if run in breakable_phrases else [run]
        return ''.join(f'<width:{glyph_width_px:02X}><space:{advance_px:02X}>' + piece +
                       restore for piece in pieces)
    return COMPACT_VISIBLE_RUN.sub(replace, folded)


# Existing callers use the historical name; both entry points share one rule.
compact_latin_runs = compact_visible_runs
