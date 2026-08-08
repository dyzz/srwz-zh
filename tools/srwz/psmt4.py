"""Fail-closed PSMT4 swizzle helpers for power-of-two SRWZ textures.

The mapping matches the PlayStation 2 GS 4-bpp indexed layout used by the
scenario-selection and VEFF TIM2 records.  Non-power-of-two GS layouts may
need padded buffer-width metadata that is not represented by image dimensions,
so this module rejects them instead of guessing.
"""

from __future__ import annotations


WIDTH = 256
HEIGHT = 256
PIXEL_COUNT = WIDTH * HEIGHT
PACKED_SIZE = PIXEL_COUNT // 2


class Psmt4Error(ValueError):
    """The source data or fixed texture geometry violates the contract."""


def validate_psmt4_geometry(width: int, height: int) -> None:
    """Accept only dimensions whose stored mapping is self-contained."""

    for label, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise Psmt4Error(f"PSMT4 {label} must be an integer")
        if value < 32 or value & (value - 1):
            raise Psmt4Error(
                f"PSMT4 {label} must be a power of two of at least 32"
            )


def supports_psmt4_geometry(width: int, height: int) -> bool:
    """Return whether the fail-closed swizzle contract accepts the geometry."""

    try:
        validate_psmt4_geometry(width, height)
    except Psmt4Error:
        return False
    return True


def _stored_location(
    x: int,
    y: int,
    width: int,
    height: int,
) -> tuple[int, int]:
    pages_horz = (width + 127) // 128
    pages_vert = (height + 127) // 128
    page_x = x & ~0x7F
    page_y = y & ~0x7F
    page_number = (page_y // 128) * pages_horz + (page_x // 128)
    page32_y = (page_number // pages_vert) * 32
    page32_x = (page_number % pages_vert) * 64
    page_location = page32_y * height * 2 + page32_x * 4
    local_x = x & 0x7F
    local_y = y & 0x7F
    block_location = (
        ((local_x & ~0x1F) >> 1) * height
        + (local_y & ~0x0F) * 2
    )
    swap_selector = (((y + 2) >> 2) & 1) * 4
    position_y = (((y & ~3) >> 1) + (y & 1)) & 7
    column_location = (
        position_y * height * 2
        + ((x + swap_selector) & 7) * 4
    )
    byte_number = (x >> 3) & 3
    nibble = (y >> 1) & 1
    return page_location + block_location + column_location + byte_number, nibble


def unswizzle_psmt4(
    data: bytes,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> bytes:
    """Return one byte per logical pixel, with values in ``0..15``."""

    validate_psmt4_geometry(width, height)
    source = bytes(data)
    pixel_count = width * height
    packed_size = pixel_count // 2
    if len(source) != packed_size:
        raise Psmt4Error(
            f"PSMT4 source has {len(source)} bytes, expected {packed_size}"
        )
    logical = bytearray(pixel_count)
    seen = bytearray(pixel_count)
    for y in range(height):
        for x in range(width):
            stored_offset, nibble = _stored_location(x, y, width, height)
            nibble_offset = stored_offset * 2 + nibble
            if not 0 <= nibble_offset < pixel_count:
                raise Psmt4Error("PSMT4 stored nibble is outside the image")
            if seen[nibble_offset]:
                raise Psmt4Error("PSMT4 stored nibble is not unique")
            seen[nibble_offset] = 1
            logical[y * width + x] = (
                source[stored_offset] >> (nibble * 4)
            ) & 0x0F
    if not all(seen):
        raise Psmt4Error("PSMT4 mapping does not cover the image")
    return bytes(logical)


def swizzle_psmt4(
    data: bytes,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> bytes:
    """Pack logical 4-bpp pixels into the fixed GS storage permutation."""

    validate_psmt4_geometry(width, height)
    logical = bytes(data)
    pixel_count = width * height
    packed_size = pixel_count // 2
    if len(logical) != pixel_count:
        raise Psmt4Error(
            f"PSMT4 logical image has {len(logical)} pixels, "
            f"expected {pixel_count}"
        )
    if any(pixel > 0x0F for pixel in logical):
        raise Psmt4Error("PSMT4 logical pixel exceeds 4-bpp range")
    stored = bytearray(packed_size)
    seen = bytearray(pixel_count)
    for y in range(height):
        for x in range(width):
            stored_offset, nibble = _stored_location(x, y, width, height)
            nibble_offset = stored_offset * 2 + nibble
            if not 0 <= nibble_offset < pixel_count:
                raise Psmt4Error("PSMT4 stored nibble is outside the image")
            if seen[nibble_offset]:
                raise Psmt4Error("PSMT4 stored nibble is not unique")
            seen[nibble_offset] = 1
            shift = nibble * 4
            stored[stored_offset] = (
                stored[stored_offset] & (0x0F if nibble else 0xF0)
            ) | (logical[y * width + x] << shift)
    if not all(seen):
        raise Psmt4Error("PSMT4 mapping does not cover the image")
    return bytes(stored)


__all__ = [
    "HEIGHT",
    "PACKED_SIZE",
    "PIXEL_COUNT",
    "Psmt4Error",
    "WIDTH",
    "swizzle_psmt4",
    "supports_psmt4_geometry",
    "unswizzle_psmt4",
    "validate_psmt4_geometry",
]
