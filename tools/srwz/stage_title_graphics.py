"""Deterministic raster helpers for the 512x64 VT1 stage-title textures.

The title pictures use linear, low-nibble-first 4-bpp storage.  They are not
PSMT4-swizzled: the game stores each 24x24 source glyph at double horizontal
width to compensate for the title sprite's display geometry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


TITLE_WIDTH = 512
TITLE_HEIGHT = 64
TITLE_IMAGE_SIZE = TITLE_WIDTH * TITLE_HEIGHT // 2
GLYPH_WIDTH = 24
GLYPH_HEIGHT = 24
GLYPH_SIZE = GLYPH_WIDTH * GLYPH_HEIGHT


class StageTitleGraphicError(ValueError):
    """The stage-title bitmap or raster policy violates its fixed contract."""


@dataclass(frozen=True)
class LatinLayout:
    """Proportional layout policy for ASCII-range cells of one title.

    Latin letters, digits and punctuation keep their stock 24x24 glyph
    bitmaps but advance by their own ink width plus ``letter_gap`` instead of
    one full CJK cell; an ASCII space advances by ``space_width``.  All values
    are in the 24px source domain and are doubled like every other column.
    """

    mode: str = "proportional_stock_glyphs"
    letter_gap: int = 2
    space_width: int = 8

    def validate(self) -> None:
        if self.mode != "proportional_stock_glyphs":
            raise StageTitleGraphicError("unknown stage-title Latin layout mode")
        for label, value, low, high in (
            ("letter_gap", self.letter_gap, 0, 8),
            ("space_width", self.space_width, 2, GLYPH_WIDTH),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not low <= value <= high
            ):
                raise StageTitleGraphicError(
                    f"stage-title Latin layout {label} must be within {low}..{high}"
                )

    def to_metadata(self) -> dict:
        return {
            "mode": self.mode,
            "letter_gap": self.letter_gap,
            "space_width": self.space_width,
        }


@dataclass(frozen=True)
class StageTitleRaster:
    indexes: bytes
    x: int
    y: int
    width: int
    height: int
    natural_width: int
    quantization_levels: int
    cell_count: int = 0
    latin_cell_count: int = 0
    layout_mode: str = "fixed_cells"


def is_latin_title_character(character: str) -> bool:
    """Return whether one title character uses the stock ASCII-range glyphs."""

    return len(character) == 1 and " " <= character <= "~"


def glyph_ink_columns(glyph: bytes) -> tuple[int, int] | None:
    """Return the inclusive first/last nonzero column of one unpacked glyph."""

    if len(glyph) != GLYPH_SIZE:
        raise StageTitleGraphicError("glyph ink measurement needs one 24x24 glyph")
    columns = [
        x
        for x in range(GLYPH_WIDTH)
        if any(glyph[y * GLYPH_WIDTH + x] for y in range(GLYPH_HEIGHT))
    ]
    if not columns:
        return None
    return columns[0], columns[-1]


def unpack_linear_4bpp(data: bytes) -> bytes:
    """Expand low-nibble-first linear 4-bpp bytes to one index per pixel."""

    source = bytes(data)
    if len(source) != TITLE_IMAGE_SIZE:
        raise StageTitleGraphicError(
            f"stage-title image has {len(source)} bytes, "
            f"expected {TITLE_IMAGE_SIZE}"
        )
    indexes = bytearray(TITLE_WIDTH * TITLE_HEIGHT)
    for offset, value in enumerate(source):
        indexes[offset * 2] = value & 0x0F
        indexes[offset * 2 + 1] = value >> 4
    return bytes(indexes)


def pack_linear_4bpp(indexes: bytes) -> bytes:
    """Pack one index per pixel into low-nibble-first linear 4-bpp bytes."""

    logical = bytes(indexes)
    if len(logical) != TITLE_WIDTH * TITLE_HEIGHT:
        raise StageTitleGraphicError(
            f"stage-title raster has {len(logical)} pixels, "
            f"expected {TITLE_WIDTH * TITLE_HEIGHT}"
        )
    if any(value > 0x0F for value in logical):
        raise StageTitleGraphicError("stage-title raster exceeds 4-bpp")
    return bytes(
        logical[offset] | (logical[offset + 1] << 4)
        for offset in range(0, len(logical), 2)
    )


def _quantize(value: int, levels: int) -> int:
    if not 2 <= levels <= 16:
        raise StageTitleGraphicError(
            "stage-title quantization levels must be within 2..16"
        )
    if not 0 <= value <= 0x0F:
        raise StageTitleGraphicError("stage-title glyph exceeds 4-bpp")
    if levels == 16:
        return value
    level = (value * (levels - 1) + 7) // 15
    return level * 15 // (levels - 1)


@dataclass(frozen=True)
class _TitleCell:
    glyph: bytes | None
    source_x0: int
    source_width: int
    doubled_width: int
    trailing_gap: int
    latin: bool


def layout_title_cells(
    text: str,
    glyphs: Mapping[str, bytes],
    *,
    doubled_glyph_width: int = 48,
    advance: int = 50,
    latin_layout: LatinLayout | None = None,
) -> tuple[list, int]:
    """Return the horizontal cells of one title and its natural width.

    Without a Latin layout every character occupies one doubled CJK cell,
    reproducing the stock geometry byte for byte.  With a Latin layout,
    ASCII-range characters advance proportionally by their stock glyph ink.
    """

    if not isinstance(text, str) or not text:
        raise StageTitleGraphicError("stage-title text must be non-empty")
    if (
        doubled_glyph_width != GLYPH_WIDTH * 2
        or advance < doubled_glyph_width
    ):
        raise StageTitleGraphicError("stage-title raster geometry drift")
    if latin_layout is not None:
        latin_layout.validate()
    cjk_gap = advance - doubled_glyph_width
    cells = []
    for character in text:
        glyph = glyphs.get(character)
        if glyph is None:
            raise StageTitleGraphicError(
                f"stage-title glyph is missing: {character!r}"
            )
        glyph = bytes(glyph)
        if len(glyph) != GLYPH_SIZE:
            raise StageTitleGraphicError(
                f"stage-title glyph has wrong size: {character!r}"
            )
        if any(value > 0x0F for value in glyph):
            raise StageTitleGraphicError(
                f"stage-title glyph exceeds 4-bpp: {character!r}"
            )
        if latin_layout is not None and is_latin_title_character(character):
            if character == " ":
                cells.append(
                    _TitleCell(None, 0, 0, latin_layout.space_width * 2, 0, True)
                )
                continue
            ink = glyph_ink_columns(glyph)
            if ink is None:
                raise StageTitleGraphicError(
                    f"stage-title Latin glyph is blank: {character!r}"
                )
            x0, x1 = ink
            cells.append(
                _TitleCell(
                    glyph,
                    x0,
                    x1 - x0 + 1,
                    (x1 - x0 + 1) * 2,
                    latin_layout.letter_gap * 2,
                    True,
                )
            )
            continue
        cells.append(
            _TitleCell(glyph, 0, GLYPH_WIDTH, doubled_glyph_width, cjk_gap, False)
        )
    natural_width = sum(cell.doubled_width for cell in cells) + sum(
        cell.trailing_gap for cell in cells[:-1]
    )
    return cells, natural_width


def render_stage_title(
    text: str,
    glyphs: Mapping[str, bytes],
    *,
    doubled_glyph_width: int = 48,
    advance: int = 50,
    y: int = 4,
    quantization_levels: int = 16,
    latin_layout: LatinLayout | None = None,
) -> StageTitleRaster:
    """Render one centered title with the stock VT1 title geometry."""

    if not 0 <= y <= TITLE_HEIGHT - GLYPH_HEIGHT:
        raise StageTitleGraphicError("stage-title raster geometry drift")
    cells, natural_width = layout_title_cells(
        text,
        glyphs,
        doubled_glyph_width=doubled_glyph_width,
        advance=advance,
        latin_layout=latin_layout,
    )

    lookup: list = [None] * natural_width
    cursor = 0
    for index, cell in enumerate(cells):
        if cell.glyph is not None:
            for within in range(cell.doubled_width):
                source_x = cell.source_x0 + within * cell.source_width // cell.doubled_width
                lookup[cursor + within] = (cell.glyph, source_x)
        cursor += cell.doubled_width
        if index < len(cells) - 1:
            cursor += cell.trailing_gap
    if cursor != natural_width:
        raise StageTitleGraphicError("stage-title cell layout drift")

    width = min(natural_width, TITLE_WIDTH)
    x = (TITLE_WIDTH - width) // 2
    output = bytearray(TITLE_WIDTH * TITLE_HEIGHT)
    for target_x in range(width):
        natural_x = target_x * natural_width // width
        sample = lookup[natural_x]
        if sample is None:
            continue
        glyph, source_x = sample
        for source_y in range(GLYPH_HEIGHT):
            value = glyph[source_y * GLYPH_WIDTH + source_x]
            output[(y + source_y) * TITLE_WIDTH + x + target_x] = _quantize(
                value,
                quantization_levels,
            )

    return StageTitleRaster(
        indexes=bytes(output),
        x=x,
        y=y,
        width=width,
        height=GLYPH_HEIGHT,
        natural_width=natural_width,
        quantization_levels=quantization_levels,
        cell_count=len(cells),
        latin_cell_count=sum(cell.latin for cell in cells),
        layout_mode=(
            "fixed_cells" if latin_layout is None else latin_layout.mode
        ),
    )


__all__ = [
    "GLYPH_HEIGHT",
    "GLYPH_SIZE",
    "GLYPH_WIDTH",
    "LatinLayout",
    "StageTitleGraphicError",
    "StageTitleRaster",
    "TITLE_HEIGHT",
    "TITLE_IMAGE_SIZE",
    "TITLE_WIDTH",
    "glyph_ink_columns",
    "is_latin_title_character",
    "layout_title_cells",
    "pack_linear_4bpp",
    "render_stage_title",
    "unpack_linear_4bpp",
]
