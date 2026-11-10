"""Two-byte text layout metrics; encoding and visible advancement stay separate."""
from __future__ import annotations

import re
from functools import lru_cache
from dataclasses import dataclass

from .text import CONTROL_NOTATION, normalize_original_fullwidth_ascii
from .control_layout import control_cells, require_static_layout
from .compact_scopes import expand as expand_compact_scopes, metrics_for_advance

_DIMENSION = re.compile(r"<(width|space):([0-9A-Fa-f]{2})>\Z")
# Only expression/identifier punctuation belongs to compact scopes. Chinese
# sentence punctuation remains outside; in particular U+FF0C is not a digit
# grouping separator. Keep this alphabet shared with the layout tokenizer.
COMPACT_SCOPE_CHARACTERS = r"A-Za-z0-9Ａ-Ｚａ-ｚ０-９Σσ∀αβγδΩⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ()（）\[\]［］ .,:：．_'/／＋+％%~～〜×÷±＝=　－−·《》-"
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


_CANDIDATE_SCENES = {16:'main_flow',21:'story',22:'battle',24:'main_scroll',25:'sp_scroll'}
_PRIMED_MEASUREMENTS: dict = {}


def _candidate_request(text, default_advance_px, state, stage_keyword_links):
    prefix=f'<width:{state.glyph_width_px:02X}><space:{state.advance_px:02X}>'
    return dict(text=prefix+text,scene=_CANDIDATE_SCENES[default_advance_px],action='measure',
                options=dict(typography='proportional',chinesePunctuation='compact',keywordLinks=stage_keyword_links))


def prime_text_extents(lines, *, default_advance_px: int, stage_keyword_links: bool = False) -> None:
    """Measure rows in shared Node batches so ``text_extent`` needs no process per row.

    Only an optimization: a row that is invalid or skipped here is measured,
    and reports its error, through ``text_extent`` as usual.
    """
    from .js_layout import layout_batch
    from .typography_policy import candidate_enabled
    if not candidate_enabled() or default_advance_px not in _CANDIDATE_SCENES:
        return
    state = RendererState(default_advance_px, default_advance_px)
    keys = {}
    for line in lines:
        text = expand_compact_scopes(line, metrics_for_advance(default_advance_px))
        if '\n' in text or '\r' in text:
            continue
        try:
            require_static_layout(text)
        except ValueError:
            continue
        key = (text, default_advance_px, state, stage_keyword_links)
        if key not in _PRIMED_MEASUREMENTS:
            keys[key] = None
    pending = list(keys)
    for start in range(0, len(pending), 256):
        group = pending[start:start + 256]
        for key, response in zip(group, layout_batch([_candidate_request(*key) for key in group])):
            if response['ok']:
                _PRIMED_MEASUREMENTS[key] = response['result']


@lru_cache(maxsize=16384)
def _candidate_extent(text, default_advance_px, state, stage_keyword_links):
    from .js_layout import request_layout
    result=_PRIMED_MEASUREMENTS.get((text,default_advance_px,state,stage_keyword_links))
    if result is None:
        request=_candidate_request(text,default_advance_px,state,stage_keyword_links)
        result=request_layout(request['text'],request['scene'],action='measure',options=request['options'])
    for token in CONTROL_NOTATION.finditer(text):
        dimension=_DIMENSION.fullmatch(token.group())
        if dimension:
            value=int(dimension[2],16)
            state=RendererState(value if dimension[1]=='space' else state.advance_px,value if dimension[1]=='width' else state.glyph_width_px)
    row=result['rows'][0]
    return TextExtent(row['advancePx'],row['occupiedPx'],state)


def text_extent(text: str, *, default_advance_px: int,
                state: RendererState | None = None,
                placeholder_cells: int = 6,
                stage_keyword_links: bool = False) -> TextExtent:
    """Measure advancement and rightmost glyph edge, including inline state.

    Widths are conservative glyph rectangles, not font-ink bounding boxes.
    The caller supplies the renderer's default; no Unicode-width heuristic is
    used. Newlines must be measured by the caller as separate physical rows.
    """
    text = expand_compact_scopes(text, metrics_for_advance(default_advance_px))
    require_static_layout(text)
    if not 1 <= default_advance_px <= 63:
        raise ValueError('default advance must be between 1 and 63 pixels')
    current = state or RendererState(default_advance_px, default_advance_px)
    from .typography_policy import candidate_enabled
    if candidate_enabled() and default_advance_px in {16,21,22,24,25}:
        if '\n' in text or '\r' in text:raise ValueError('text_extent accepts one physical row')
        return _candidate_extent(text,default_advance_px,current,stage_keyword_links)
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
            else:
                cells = control_cells(token, placeholder_cells)
                if cells:
                    occupied = max(occupied, advance + (cells-1)*current.advance_px + current.glyph_width_px)
                    advance += cells * current.advance_px
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
    from .typography_policy import candidate_enabled
    if candidate_enabled():return folded
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
