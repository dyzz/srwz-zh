"""Fill native two-byte character grids without variable-width controls."""
from .chinese_layout import (
    FORBIDDEN_LINE_END_CHARACTERS,
    FORBIDDEN_LINE_START_CHARACTERS,
)
from .text import CONTROL_NOTATION, normalize_original_fullwidth_ascii


def _is_latin(character: str) -> bool:
    return character.isascii() and character.isalnum()


def _latin_run_start(text: str, end: int) -> int:
    """Return where the Latin/digit run crossing ``end`` starts, else ``end``."""
    if end >= len(text) or not (_is_latin(text[end - 1]) and _is_latin(text[end])):
        return end
    start = end - 1
    while start and _is_latin(text[start - 1]):
        start -= 1
    return start


def fill_fixed_grid_paragraphs(text: str, *, columns: int = 28) -> list[str]:
    """Preserve authored paragraphs; take the latest safe break.

    Punctuation rules apply, and a Latin/digit run stays on one row. Chinese
    words may still split: these pages fill every cell by design.

    VT1 cells store exactly one two-byte glyph each. Latin letters and digits
    also occupy a cell, so renderer advance estimates cannot set this budget.
    Controls cannot be embedded in this format.
    """
    if columns < 2:
        raise ValueError("fixed grid requires at least two columns")
    if CONTROL_NOTATION.search(text):
        raise ValueError("metric controls cannot occupy fixed-grid cells")
    result = []
    for paragraph in normalize_original_fullwidth_ascii(text).split("\n"):
        if not paragraph.strip():
            result.append(paragraph.replace(" ", "　"))
            continue
        indent = "　" if paragraph.startswith(("　", " ")) else ""
        remaining = indent + paragraph.strip().replace(" ", "　")
        while len(remaining) > columns:
            end = columns
            while end:
                if (
                    remaining[end - 1] in FORBIDDEN_LINE_END_CHARACTERS
                    or remaining[end] in FORBIDDEN_LINE_START_CHARACTERS
                ):
                    end -= 1
                    continue
                start = _latin_run_start(remaining, end)
                # A run that already fills its row has to break somewhere.
                if start == end or not remaining[:start].strip("　"):
                    break
                end = start
            if not end:
                raise ValueError("no legal fixed-grid line break")
            result.append(remaining[:end])
            remaining = remaining[end:]
        result.append(remaining)
    return result
