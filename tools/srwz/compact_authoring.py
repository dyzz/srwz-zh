"""Closed compact scopes around visible text; native controls remain boundaries."""
from __future__ import annotations

import re

from .renderer_metrics import COMPACT_VISIBLE_RUN
from .text import CONTROL_NOTATION, normalize_original_fullwidth_ascii

DIMENSION = re.compile(r'<(width|space):([0-9A-Fa-f]{2})>\Z')
SCOPE = re.compile(
    r'<width:0E><space:0C>'
    r'(?P<visible>[A-Za-z0-9Ａ-Ｚａ-ｚ０-９ .,:：．_\'/／＋+％%~～〜×÷±＝=　－−·《》-]+)'
    r'(?P<restore><width:(?P<w>[0-9A-Fa-f]{2})><space:(?P<s>[0-9A-Fa-f]{2})>'
    r'|<space:(?P<rs>[0-9A-Fa-f]{2})><width:(?P<rw>[0-9A-Fa-f]{2})>)'
)
BOUNDARY = re.compile(
    SCOPE.pattern + r'|＜ｔｍ＞.*?＜／ｔｍ＞|<tm>.*?</tm>|<<[^>]+>>|'
    + CONTROL_NOTATION.pattern + r'|\\[nrt]|\\u[0-9A-Fa-f]{4}', re.S
)


def unscoped_text(text: str) -> str:
    """Remove only well-formed author scopes, retaining their visible contents."""
    def remove(match):
        width = int(match['w'] or match['rw'], 16)
        space = int(match['s'] or match['rs'], 16)
        if not 14 <= width <= 63 or not 12 <= space <= 63:
            return match.group()
        if len(match['visible'].replace('《', '').replace('》', '')) < 3:
            return match.group()
        return match['visible']
    return SCOPE.sub(remove, text)


def compact_controlled_text(text: str, *, default_width: int, default_space: int | None = None,
                            spans: list[list[int]] | None = None,
                            keyword_links: bool = False) -> str:
    """Preserve existing controls and wrap plain runs or exact confirmed spans.

    Existing compact scopes are idempotent. Restoration follows the state at
    each insertion, including a preceding native dimension tag. tm templates,
    icons, literal escape sequences and native control tokens are never edited.
    """
    space = default_width if default_space is None else default_space
    if not 14 <= default_width <= 63 or not 12 <= space <= 63:
        raise ValueError('unsupported renderer baseline')
    width = default_width
    tokens = list(BOUNDARY.finditer(text))
    if spans is not None:
        for start, end in spans:
            if not 0 <= start < end <= len(text):
                raise ValueError('confirmed span outside text')
            if any(start < t.end() and t.start() < end for t in tokens):
                raise ValueError('confirmed span intersects native control')
    output = []
    cursor = 0

    def plain(start, end):
        chunk = text[start:end]
        selected = [(a-start, b-start) for a, b in spans if start <= a < b <= end] if spans is not None else [
            (m.start(), m.end()) for m in COMPACT_VISIBLE_RUN.finditer(normalize_original_fullwidth_ascii(chunk))
            if len(m.group()) >= 3 and '÷' not in m.group()]
        for a, b in reversed(selected):
            # Keep cataloged keyword text byte-for-byte between its delimiters.
            if keyword_links:
                link = next((m for m in re.finditer(r'《[^《》]*》', chunk)
                             if m.start() < a < b < m.end()), None)
                if link:
                    if (a, b) != (link.start()+1, link.end()-1):
                        continue
                    a -= 1
                    b += 1
            run = chunk[a:b]
            restore = (f'<space:{space:02X}><width:{width:02X}>' if run.endswith(('%', '％'))
                       else f'<width:{width:02X}><space:{space:02X}>')
            chunk = chunk[:a] + '<width:0E><space:0C>' + run + restore + chunk[b:]
        return chunk

    for token in tokens:
        output.append(plain(cursor, token.start()))
        output.append(token.group())
        dimension = DIMENSION.fullmatch(token.group())
        if dimension:
            if dimension[1] == 'width':
                width = int(dimension[2], 16)
            else:
                space = int(dimension[2], 16)
        cursor = token.end()
    output.append(plain(cursor, len(text)))
    result = ''.join(output)
    if unscoped_text(result) != unscoped_text(text):
        raise ValueError('compact authoring changed native text or controls')
    return result
