"""Reuse the Japanese period raster without changing localized text codes.

Both ASCII and fullwidth periods retain their allocated slots and therefore
their existing renderer width classes. Chinese stops and ellipses are excluded.
"""
from .font import GLYPH_SIZE, decode_glyph, encode_glyph, sha256_bytes, standard_glyph_index

PERIOD_CHARACTERS = frozenset({".", "．"})
SOURCE_CODE = 0x8144


def native_period_raster(original_font: bytes) -> tuple[bytes, bytes, bytes]:
    pixels = decode_glyph(original_font, standard_glyph_index(SOURCE_CODE))
    if not any(pixels):
        raise ValueError("original Japanese period glyph is blank")
    return bytes(value * 17 for value in pixels), pixels, encode_glyph(pixels)


def native_period_metadata(original_font: bytes) -> dict:
    _, pixels, packed = native_period_raster(original_font)
    return {
        "mode": "copy_original_japanese_period",
        "source_code": f"{SOURCE_CODE:04X}",
        "pixels_4bpp_sha256": sha256_bytes(pixels),
        "packed_glyph_sha256": sha256_bytes(packed),
    }


def replace_period_slots(font: bytes, original_font: bytes, assignments: list[dict]):
    """Apply the same policy to an existing reviewed font, preserving all else."""
    if len(font) != len(original_font):
        raise ValueError("period font geometry mismatch")
    _, _, packed = native_period_raster(original_font)
    targets = {r["glyph_index"] for r in assignments
               if r["character"] in PERIOD_CHARACTERS}
    if not targets or {r["character"] for r in assignments
                       if r["glyph_index"] in targets} != PERIOD_CHARACTERS:
        raise ValueError("missing period assignments or shared non-period slot")
    result = bytearray(font)
    changed = []
    for index in sorted(targets):
        start = index * GLYPH_SIZE
        if not 0 <= start <= len(font) - GLYPH_SIZE:
            raise ValueError("period slot outside font")
        if result[start:start + GLYPH_SIZE] != packed:
            changed.append(index)
            result[start:start + GLYPH_SIZE] = packed
    return bytes(result), changed
