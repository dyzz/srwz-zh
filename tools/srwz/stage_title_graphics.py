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
class StageTitleRaster:
    indexes: bytes
    x: int
    y: int
    width: int
    height: int
    natural_width: int
    quantization_levels: int


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


def render_stage_title(
    text: str,
    glyphs: Mapping[str, bytes],
    *,
    doubled_glyph_width: int = 48,
    advance: int = 50,
    y: int = 4,
    quantization_levels: int = 16,
) -> StageTitleRaster:
    """Render one centered title with the stock VT1 title geometry."""

    if not isinstance(text, str) or not text:
        raise StageTitleGraphicError("stage-title text must be non-empty")
    if (
        doubled_glyph_width != GLYPH_WIDTH * 2
        or advance < doubled_glyph_width
        or not 0 <= y <= TITLE_HEIGHT - GLYPH_HEIGHT
    ):
        raise StageTitleGraphicError("stage-title raster geometry drift")

    resolved = []
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
        resolved.append(glyph)

    natural_width = (len(resolved) - 1) * advance + doubled_glyph_width
    width = min(natural_width, TITLE_WIDTH)
    x = (TITLE_WIDTH - width) // 2
    output = bytearray(TITLE_WIDTH * TITLE_HEIGHT)

    for target_x in range(width):
        natural_x = target_x * natural_width // width
        glyph_index, within = divmod(natural_x, advance)
        if glyph_index >= len(resolved) or within >= doubled_glyph_width:
            continue
        source_x = within * GLYPH_WIDTH // doubled_glyph_width
        glyph = resolved[glyph_index]
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
    )


__all__ = [
    "GLYPH_HEIGHT",
    "GLYPH_SIZE",
    "GLYPH_WIDTH",
    "StageTitleGraphicError",
    "StageTitleRaster",
    "TITLE_HEIGHT",
    "TITLE_IMAGE_SIZE",
    "TITLE_WIDTH",
    "pack_linear_4bpp",
    "render_stage_title",
    "unpack_linear_4bpp",
]
