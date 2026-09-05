"""Fail-closed PSMT4 swizzle helpers for power-of-two SRWZ textures.

The mapping matches the PlayStation 2 GS 4-bpp indexed layout used by the
scenario-selection and VEFF TIM2 records.  Non-power-of-two GS layouts may
need padded buffer-width metadata that is not represented by image dimensions,
so this module rejects them instead of guessing.
"""

from __future__ import annotations

from functools import lru_cache


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
    *,
    row_major_pages: bool,
) -> tuple[int, int]:
    pages_horz = (width + 127) // 128
    pages_vert = (height + 127) // 128
    page_x = x & ~0x7F
    page_y = y & ~0x7F
    page_number = (page_y // 128) * pages_horz + (page_x // 128)
    page_divisor = pages_horz if row_major_pages else pages_vert
    storage_stride = width if row_major_pages else height
    page32_y = (page_number // page_divisor) * 32
    page32_x = (page_number % page_divisor) * 64
    page_location = page32_y * storage_stride * 2 + page32_x * 4
    local_x = x & 0x7F
    local_y = y & 0x7F
    block_location = (
        ((local_x & ~0x1F) >> 1) * storage_stride
        + (local_y & ~0x0F) * 2
    )
    swap_selector = (((y + 2) >> 2) & 1) * 4
    position_y = (((y & ~3) >> 1) + (y & 1)) & 7
    column_location = (
        position_y * storage_stride * 2
        + ((x + swap_selector) & 7) * 4
    )
    byte_number = (x >> 3) & 3
    nibble = (y >> 1) & 1
    return page_location + block_location + column_location + byte_number, nibble


@lru_cache(maxsize=8)
def _validated_layout(
    width: int, height: int, row_major_pages: bool
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Prove each geometry's permutation once, then reuse it for every texture."""

    pixel_count = width * height
    forward = []
    inverse = [-1] * pixel_count
    for y in range(height):
        for x in range(width):
            offset, nibble = _stored_location(
                x, y, width, height, row_major_pages=row_major_pages
            )
            target = offset * 2 + nibble
            if not 0 <= target < pixel_count:
                raise Psmt4Error("PSMT4 stored nibble is outside the image")
            if inverse[target] != -1:
                raise Psmt4Error("PSMT4 stored nibble is not unique")
            inverse[target] = len(forward)
            forward.append(target)
    if -1 in inverse:
        raise Psmt4Error("PSMT4 mapping does not cover the image")
    return tuple(forward), tuple(inverse)


def unswizzle_psmt4(
    data: bytes,
    width: int = WIDTH,
    height: int = HEIGHT,
    *,
    row_major_pages: bool = False,
) -> bytes:
    """Return one byte per logical pixel, with values in ``0..15``.

    ``row_major_pages`` is explicit because the 512x256 TRICMN record uses
    width-stride page storage, while older verified SRWZ consumers retain the
    module's historical height-stride layout.
    """

    validate_psmt4_geometry(width, height)
    if not isinstance(row_major_pages, bool):
        raise Psmt4Error("PSMT4 row-major page selector must be a boolean")
    source = bytes(data)
    pixel_count = width * height
    packed_size = pixel_count // 2
    if len(source) != packed_size:
        raise Psmt4Error(
            f"PSMT4 source has {len(source)} bytes, expected {packed_size}"
        )
    forward, _inverse = _validated_layout(width, height, row_major_pages)
    return bytes(
        (source[target >> 1] >> ((target & 1) * 4)) & 0x0F for target in forward
    )


def swizzle_psmt4(
    data: bytes,
    width: int = WIDTH,
    height: int = HEIGHT,
    *,
    row_major_pages: bool = False,
) -> bytes:
    """Pack logical 4-bpp pixels into the fixed GS storage permutation."""

    validate_psmt4_geometry(width, height)
    if not isinstance(row_major_pages, bool):
        raise Psmt4Error("PSMT4 row-major page selector must be a boolean")
    logical = bytes(data)
    pixel_count = width * height
    packed_size = pixel_count // 2
    if len(logical) != pixel_count:
        raise Psmt4Error(
            f"PSMT4 logical image has {len(logical)} pixels, "
            f"expected {pixel_count}"
        )
    if max(logical, default=0) > 0x0F:
        raise Psmt4Error("PSMT4 logical pixel exceeds 4-bpp range")
    _forward, inverse = _validated_layout(width, height, row_major_pages)
    return bytes(
        logical[inverse[index]] | (logical[inverse[index + 1]] << 4)
        for index in range(0, pixel_count, 2)
    )


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
