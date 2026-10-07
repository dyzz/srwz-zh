"""One source-bound storage ligature for Land's fixed-size squad name.

The corpus keeps THE HEAT. Only the original-game squad-name writers use the
private character, whose stock-derived bitmap draws E followed by blank space.
SP and ordinary dialogue retain their existing encodings.
"""
from __future__ import annotations

from .font import decode_glyph, encode_glyph, sha256_bytes, standard_glyph_index
from .text import normalize_original_fullwidth_ascii, two_byte_visible_spaces

CHARACTER = "\ue000"
CODE = 0x97F0
GLYPH_INDEX = 4400
SOURCE = "ザ・ヒート"
LOGICAL_NAME = "THE HEAT"
RASTER_MODE = "stock_e_space_squad_ligature"


def stored_squad_name(source: str, translation: str) -> str:
    normalized = normalize_original_fullwidth_ascii(translation)
    if source == SOURCE and normalized.replace("\u3000", " ") == LOGICAL_NAME:
        return "TH" + CHARACTER + "HEAT"
    return two_byte_visible_spaces(normalized)


def logical_squad_name(stored: str) -> str:
    return stored.replace(CHARACTER, "E\u3000")


def ligature_raster(original_font: bytes) -> tuple[bytes, bytes, bytes]:
    """Derive the reviewed 24x24 glyph from the stock E, without font fallback.

    Its default-width cell replaces two narrower Latin/blank cells. Resampling
    the 15-pixel stock E ink into 10 pixels matches ordinary Latin on that path.
    All vertical coordinates stay intact; the remaining canvas is blank.
    """
    stock = decode_glyph(original_font, standard_glyph_index(0x8264))
    ink_x = [i % 24 for i, value in enumerate(stock) if value]
    if not ink_x or (min(ink_x), max(ink_x)) != (5, 19):
        raise ValueError("squad ligature stock E geometry drift")
    pixels = bytearray(24 * 24)
    for y in range(24):
        for dx in range(10):
            # Integer area sampling: source interval [3*dx, 3*dx+3)
            # intersects two-unit-wide source pixels; denominator is three.
            left, right = 3 * dx, 3 * dx + 3
            total = sum(
                stock[y * 24 + 5 + sx]
                * max(0, min(right, 2 * sx + 2) - max(left, 2 * sx))
                for sx in range(15)
            )
            pixels[y * 24 + 3 + dx] = (total + 1) // 3
    pixels = bytes(pixels)
    return bytes(value * 17 for value in pixels), pixels, encode_glyph(pixels)


def ligature_metadata(original_font: bytes) -> dict:
    gray, pixels, packed = ligature_raster(original_font)
    return dict(mode=RASTER_MODE, source_code="8264", logical_text="E ",
                raw_gray_sha256=sha256_bytes(gray),
                pixels_4bpp_sha256=sha256_bytes(pixels),
                packed_glyph_sha256=sha256_bytes(packed))


def validate_ligature_assignment(row: dict) -> None:
    if (row.get("character"), row.get("code"), row.get("glyph_index"),
            row.get("mapping")) != (CHARACTER, "97F0", GLYPH_INDEX,
                                   "source_bound_squad_name_ligature"):
        raise ValueError("squad ligature allocation drift")
