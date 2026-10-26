"""Fill native two-byte character grids without variable-width controls."""
from .chinese_layout import (
    FORBIDDEN_LINE_END_CHARACTERS,
    FORBIDDEN_LINE_START_CHARACTERS,
)
from .text import CONTROL_NOTATION, normalize_original_fullwidth_ascii


def fill_fixed_grid_paragraphs(text: str, *, columns: int = 28) -> list[str]:
    """Preserve authored paragraphs; take the latest punctuation-safe break.

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
            while end and (
                remaining[end - 1] in FORBIDDEN_LINE_END_CHARACTERS
                or remaining[end] in FORBIDDEN_LINE_START_CHARACTERS
            ):
                end -= 1
            if not end:
                raise ValueError("no legal fixed-grid line break")
            result.append(remaining[:end])
            remaining = remaining[end:]
        result.append(remaining)
    return result
