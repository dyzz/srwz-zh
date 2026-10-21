"""Shared authoring budgets for complete native control tokens.

These are layout reservations, not a claim about every native consumer's ink.
Unknown dynamic templates and the separate repeat renderer need an owner-
specific contract instead of being split or counted as ordinary characters.
"""
from __future__ import annotations

from functools import lru_cache
import re

from .text import (RUNTIME_REPEAT_TOKEN, RUNTIME_SQUARE_PARAMETER_TOKEN, control_notation_tokens,
                   unrecognized_control_notation_offsets)


def require_static_layout(text: str) -> None:
    if re.search(r"＜/?ｔｍ＞|</?tm>", text):
        raise ValueError('dynamic tm template requires an owner-specific layout contract')
    if RUNTIME_REPEAT_TOKEN.match(text):
        raise ValueError('native @ repeat stream requires an owner-specific layout contract')
    if RUNTIME_SQUARE_PARAMETER_TOKEN.search(text):
        raise ValueError('native square parameter requires an owner-specific layout contract')
    unknown = unrecognized_control_notation_offsets(text)
    if unknown:
        raise ValueError(f'unrecognized control syntax at character {unknown[0]}')


@lru_cache(maxsize=1024)
def control_cells(token: str, placeholder_cells: int = 6) -> int:
    """Keep cell and pixel paths on the same explicit reservation policy.

    String/format substitutions reserve six cells by default; numeric angle
    selectors reserve one icon cell. Brace style parameters, raw-byte notation
    and dimension/palette tags consume no ordinary visible cells. Resource
    owners still have to validate actual dynamic output and unknown raw bytes.
    """
    require_static_layout(token)
    parsed = control_notation_tokens(token)
    if len(parsed) != 1 or parsed[0].start != 0 or parsed[0].end != len(token):
        raise ValueError(f'not one complete control token: {token!r}')
    kind = parsed[0].kind
    if kind in ('raw_byte', 'text_tag'):
        return 0
    if token.startswith(('$', '%')):
        return placeholder_cells
    if token.startswith('<'):
        return 1
    return 0
