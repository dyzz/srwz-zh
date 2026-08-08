"""Minimal, fail-closed TIM2 pixel injection for fixed SRWZ canaries.

This is deliberately not a general TIM2 encoder.  It accepts only the exact
single-picture 256x256 4-bpp KVMDATA layout or the exact six-picture 512x256
8-bpp VT1 title-menu layout.  Both paths keep the existing CLUT and all
container metadata byte-identical and replace only indexed image bytes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .tim2 import (
    TIM2_FILE_HEADER_SIZE,
    TIM2_PICTURE_HEADER_SIZE,
    Tim2Error,
    parse_tim2,
)


CANARY_WIDTH = 256
CANARY_HEIGHT = 256
CANARY_IMAGE_SIZE = CANARY_WIDTH * CANARY_HEIGHT // 2
CANARY_CLUT_COLOR_COUNT = 256
CANARY_CLUT_SIZE = 512
RGBA_PIXEL_SIZE = 4

VT1_TITLE_WIDTH = 512
VT1_TITLE_HEIGHT = 256
VT1_TITLE_IMAGE_SIZE = VT1_TITLE_WIDTH * VT1_TITLE_HEIGHT
VT1_TITLE_PICTURE_COUNT = 6
VT1_TITLE_CLUT_COLOR_COUNT = 1536
VT1_TITLE_CLUT_SIZE = 6144


class Tim2WritebackError(ValueError):
    """The source or edited pixels exceed the minimal writer contract."""


@dataclass(frozen=True)
class Tim2InjectionResult:
    data: bytes
    image_offset: int
    image_size: int
    changed_pixel_count: int
    changed_image_byte_count: int
    changed_image_byte_ranges: tuple[tuple[int, int], ...]
    available_color_count: int

    def to_metadata(self) -> dict:
        return {
            "image_offset": self.image_offset,
            "image_size": self.image_size,
            "changed_pixel_count": self.changed_pixel_count,
            "changed_image_byte_count": self.changed_image_byte_count,
            "changed_image_byte_ranges": [
                {"start": start, "end": end}
                for start, end in self.changed_image_byte_ranges
            ],
            "available_color_count": self.available_color_count,
        }


@dataclass(frozen=True)
class Tim2IndexReplacementResult:
    data: bytes
    picture_index: int
    image_offset: int
    image_size: int
    source_index: int
    replacement_index: int
    source_index_occurrence_count: int
    changed_pixel_count: int
    changed_image_byte_count: int
    changed_image_byte_ranges: tuple[tuple[int, int], ...]
    available_index_count: int

    def to_metadata(self) -> dict:
        return {
            "picture_index": self.picture_index,
            "image_offset": self.image_offset,
            "image_size": self.image_size,
            "source_index": self.source_index,
            "replacement_index": self.replacement_index,
            "source_index_occurrence_count": (
                self.source_index_occurrence_count
            ),
            "changed_pixel_count": self.changed_pixel_count,
            "changed_image_byte_count": self.changed_image_byte_count,
            "changed_image_byte_ranges": [
                {"start": start, "end": end}
                for start, end in self.changed_image_byte_ranges
            ],
            "available_index_count": self.available_index_count,
        }


@dataclass(frozen=True)
class Tim2Indexed8InjectionResult:
    data: bytes
    picture_index: int
    image_offset: int
    image_size: int
    changed_pixel_count: int
    changed_image_byte_count: int
    changed_image_byte_ranges: tuple[tuple[int, int], ...]
    available_index_count: int

    def to_metadata(self) -> dict:
        return {
            "picture_index": self.picture_index,
            "image_offset": self.image_offset,
            "image_size": self.image_size,
            "changed_pixel_count": self.changed_pixel_count,
            "changed_image_byte_count": self.changed_image_byte_count,
            "changed_image_byte_ranges": [
                {"start": start, "end": end}
                for start, end in self.changed_image_byte_ranges
            ],
            "available_index_count": self.available_index_count,
        }


def _changed_ranges(before: bytes, after: bytes) -> tuple[tuple[int, int], ...]:
    if len(before) != len(after):
        raise Tim2WritebackError("cannot compare differently sized image data")
    ranges = []
    start = None
    for index, (old, new) in enumerate(zip(before, after)):
        if old != new and start is None:
            start = index
        elif old == new and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(before)))
    return tuple(ranges)


def _unpack_4bpp(image: bytes) -> bytes:
    indexes = bytearray(len(image) * 2)
    for byte_index, value in enumerate(image):
        pixel_index = byte_index * 2
        indexes[pixel_index] = value & 0x0F
        indexes[pixel_index + 1] = value >> 4
    return bytes(indexes)


def _rgba_at(pixels: bytes, pixel_index: int) -> bytes:
    start = pixel_index * RGBA_PIXEL_SIZE
    return pixels[start : start + RGBA_PIXEL_SIZE]


def _validate_canary_layout(data: bytes):
    try:
        record = parse_tim2(data)
    except Tim2Error as error:
        raise Tim2WritebackError(str(error)) from error
    if record.size != len(data):
        raise Tim2WritebackError(
            f"TIM2 has {len(data) - record.size} trailing bytes"
        )
    if record.format_type != 0:
        raise Tim2WritebackError("canary TIM2 must use 16-byte file alignment")
    if len(record.pictures) != 1:
        raise Tim2WritebackError("canary TIM2 must contain exactly one picture")

    picture = record.pictures[0]
    expected = {
        "picture offset": (picture.offset, TIM2_FILE_HEADER_SIZE),
        "picture header size": (
            picture.header_size,
            TIM2_PICTURE_HEADER_SIZE,
        ),
        "picture format": (picture.picture_format, 0),
        "mipmap count": (picture.mipmap_count, 1),
        "image type": (picture.image_type, 4),
        "width": (picture.width, CANARY_WIDTH),
        "height": (picture.height, CANARY_HEIGHT),
        "image size": (picture.image_size, CANARY_IMAGE_SIZE),
        "CLUT type": (picture.clut_type, 1),
        "CLUT color count": (
            picture.clut_color_count,
            CANARY_CLUT_COLOR_COUNT,
        ),
        "CLUT size": (picture.clut_size, CANARY_CLUT_SIZE),
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise Tim2WritebackError(
                f"unsupported canary {field}: {actual}, expected {wanted}"
            )
    if picture.uses_shared_clut:
        raise Tim2WritebackError("canary TIM2 cannot use a shared CLUT")
    return picture


def _validate_vt1_title_layout(data: bytes):
    try:
        record = parse_tim2(data)
    except Tim2Error as error:
        raise Tim2WritebackError(str(error)) from error
    if record.size != len(data):
        raise Tim2WritebackError(
            f"VT1 title TIM2 has {len(data) - record.size} trailing bytes"
        )
    if record.format_type != 0:
        raise Tim2WritebackError(
            "VT1 title TIM2 must use 16-byte file alignment"
        )
    if len(record.pictures) != VT1_TITLE_PICTURE_COUNT:
        raise Tim2WritebackError(
            "VT1 title TIM2 must contain exactly "
            f"{VT1_TITLE_PICTURE_COUNT} pictures"
        )

    for picture_index, picture in enumerate(record.pictures):
        expected = {
            "picture header size": (
                picture.header_size,
                TIM2_PICTURE_HEADER_SIZE,
            ),
            "picture format": (picture.picture_format, 0),
            "mipmap count": (picture.mipmap_count, 1),
            "image type": (picture.image_type, 5),
            "width": (picture.width, VT1_TITLE_WIDTH),
            "height": (picture.height, VT1_TITLE_HEIGHT),
            "image size": (
                picture.image_size,
                VT1_TITLE_IMAGE_SIZE,
            ),
            "CLUT type": (picture.clut_type, 3),
        }
        if picture_index == 0:
            expected.update(
                {
                    "CLUT color count": (
                        picture.clut_color_count,
                        VT1_TITLE_CLUT_COLOR_COUNT,
                    ),
                    "CLUT size": (
                        picture.clut_size,
                        VT1_TITLE_CLUT_SIZE,
                    ),
                }
            )
            if picture.uses_shared_clut:
                raise Tim2WritebackError(
                    "VT1 title picture 0 cannot use a shared CLUT"
                )
        else:
            expected.update(
                {
                    "CLUT color count": (
                        picture.clut_color_count,
                        0,
                    ),
                    "CLUT size": (picture.clut_size, 0),
                }
            )
            if not picture.uses_shared_clut:
                raise Tim2WritebackError(
                    f"VT1 title picture {picture_index} must use "
                    "picture 0's shared CLUT"
                )
        for field, (actual, wanted) in expected.items():
            if actual != wanted:
                raise Tim2WritebackError(
                    f"unsupported VT1 title picture {picture_index} "
                    f"{field}: {actual}, expected {wanted}"
                )
    return record


def _validate_psmt8_geometry(width: int, height: int) -> None:
    for label, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise Tim2WritebackError(f"PSMT8 {label} must be an integer")
        if value <= 0 or value % 16:
            raise Tim2WritebackError(
                f"PSMT8 {label} must be a positive multiple of 16"
            )


def _psmt8_stored_offset(x: int, y: int, width: int) -> int:
    """Return the stored byte for one logical PSMT8 pixel.

    The mapping is the GS 8-bit indexed 16x16 storage permutation used by the
    fixed SRWZ title texture.  ``width`` is the logical texture width in pixels.
    """

    block_location = (y & ~0x0F) * width + (x & ~0x0F) * 2
    swap_selector = (((y + 2) >> 2) & 1) * 4
    position_y = (((y & ~3) >> 1) + (y & 1)) & 7
    column_location = (
        position_y * width * 2
        + ((x + swap_selector) & 7) * 4
    )
    byte_number = ((y >> 1) & 1) + ((x >> 2) & 2)
    return block_location + column_location + byte_number


def unswizzle_psmt8(data: bytes, width: int, height: int) -> bytes:
    """Convert fixed-width GS PSMT8 bytes to logical row-major indexes."""

    _validate_psmt8_geometry(width, height)
    source = bytes(data)
    expected_size = width * height
    if len(source) != expected_size:
        raise Tim2WritebackError(
            f"PSMT8 image has {len(source)} bytes, expected {expected_size}"
        )
    logical = bytearray(expected_size)
    seen = bytearray(expected_size)
    for y in range(height):
        for x in range(width):
            logical_offset = y * width + x
            stored_offset = _psmt8_stored_offset(x, y, width)
            if not 0 <= stored_offset < expected_size:
                raise Tim2WritebackError(
                    f"PSMT8 stored offset {stored_offset} is outside image"
                )
            if seen[stored_offset]:
                raise Tim2WritebackError(
                    f"PSMT8 stored offset {stored_offset} is not unique"
                )
            seen[stored_offset] = 1
            logical[logical_offset] = source[stored_offset]
    if not all(seen):
        raise Tim2WritebackError("PSMT8 mapping does not cover the image")
    return bytes(logical)


def swizzle_psmt8(data: bytes, width: int, height: int) -> bytes:
    """Convert logical row-major indexes to fixed-width GS PSMT8 bytes."""

    _validate_psmt8_geometry(width, height)
    logical = bytes(data)
    expected_size = width * height
    if len(logical) != expected_size:
        raise Tim2WritebackError(
            f"PSMT8 image has {len(logical)} bytes, expected {expected_size}"
        )
    stored = bytearray(expected_size)
    seen = bytearray(expected_size)
    for y in range(height):
        for x in range(width):
            logical_offset = y * width + x
            stored_offset = _psmt8_stored_offset(x, y, width)
            if not 0 <= stored_offset < expected_size:
                raise Tim2WritebackError(
                    f"PSMT8 stored offset {stored_offset} is outside image"
                )
            if seen[stored_offset]:
                raise Tim2WritebackError(
                    f"PSMT8 stored offset {stored_offset} is not unique"
                )
            seen[stored_offset] = 1
            stored[stored_offset] = logical[logical_offset]
    if not all(seen):
        raise Tim2WritebackError("PSMT8 mapping does not cover the image")
    return bytes(stored)


def _csm1_palette_offset(index: int) -> int:
    return (
        (index & 0xE7)
        | ((index & 0x08) << 1)
        | ((index & 0x10) >> 1)
    )


def extract_vt1_title_indexes(data: bytes) -> bytes:
    """Return picture 0 as logical row-major PSMT8 indexes."""

    source = bytes(data)
    record = _validate_vt1_title_layout(source)
    picture = record.pictures[0]
    image_offset = picture.offset + picture.header_size
    image_end = image_offset + picture.image_size
    return unswizzle_psmt8(
        source[image_offset:image_end],
        picture.width,
        picture.height,
    )


def render_vt1_title_rgba(data: bytes) -> bytes:
    """Render picture 0 as the RGBA bytes uploaded by the game.

    This is intentionally limited to the verified title-menu layout.  It
    unswizzles PSMT8 indexes and applies the first 256-color CSM1 palette bank;
    it does not attempt to be a general TIM2 renderer.
    """

    source = bytes(data)
    record = _validate_vt1_title_layout(source)
    picture = record.pictures[0]
    image_offset = picture.offset + picture.header_size
    image_end = image_offset + picture.image_size
    logical = extract_vt1_title_indexes(source)
    palette_offset = image_end
    palette = source[
        palette_offset : palette_offset + picture.clut_size
    ]
    if len(palette) < 256 * RGBA_PIXEL_SIZE:
        raise Tim2WritebackError(
            "VT1 title palette does not contain its first 256-color bank"
        )
    rendered = bytearray(len(logical) * RGBA_PIXEL_SIZE)
    for pixel_offset, index in enumerate(logical):
        palette_index = _csm1_palette_offset(index)
        source_start = palette_index * RGBA_PIXEL_SIZE
        target_start = pixel_offset * RGBA_PIXEL_SIZE
        rendered[target_start : target_start + RGBA_PIXEL_SIZE] = palette[
            source_start : source_start + RGBA_PIXEL_SIZE
        ]
    return bytes(rendered)


def inject_vt1_title_indexes(
    data: bytes,
    edited_indexes: bytes,
) -> Tim2Indexed8InjectionResult:
    """Replace logical indexes in VT1 title picture 0 without changing CLUT."""

    source = bytes(data)
    record = _validate_vt1_title_layout(source)
    picture_index = 0
    picture = record.pictures[picture_index]
    expected_size = picture.width * picture.height
    edited = bytes(edited_indexes)
    if len(edited) != expected_size:
        raise Tim2WritebackError(
            f"edited VT1 title has {len(edited)} indexes, "
            f"expected {expected_size}"
        )

    image_offset = picture.offset + picture.header_size
    image_end = image_offset + picture.image_size
    image_before = source[image_offset:image_end]
    logical_before = unswizzle_psmt8(
        image_before,
        picture.width,
        picture.height,
    )
    available_indexes = set(logical_before)
    unknown_indexes = sorted(set(edited) - available_indexes)
    if unknown_indexes:
        raise Tim2WritebackError(
            "edited VT1 title uses indexes absent from the source: "
            f"{unknown_indexes}"
        )
    image_after = swizzle_psmt8(
        edited,
        picture.width,
        picture.height,
    )
    output = source[:image_offset] + image_after + source[image_end:]
    if len(output) != len(source):
        raise Tim2WritebackError(
            "VT1 title indexed injection changed the container size"
        )
    reparsed = _validate_vt1_title_layout(output)
    if reparsed != record:
        raise Tim2WritebackError(
            "VT1 title TIM2 metadata changed after indexed injection"
        )
    if unswizzle_psmt8(
        image_after,
        picture.width,
        picture.height,
    ) != edited:
        raise Tim2WritebackError(
            "VT1 title PSMT8 writeback did not round-trip"
        )

    ranges = _changed_ranges(image_before, image_after)
    changed_pixel_count = sum(
        before != after
        for before, after in zip(logical_before, edited)
    )
    return Tim2Indexed8InjectionResult(
        data=output,
        picture_index=picture_index,
        image_offset=image_offset,
        image_size=picture.image_size,
        changed_pixel_count=changed_pixel_count,
        changed_image_byte_count=sum(end - start for start, end in ranges),
        changed_image_byte_ranges=ranges,
        available_index_count=len(available_indexes),
    )


def inject_indexed4_rgba(
    data: bytes,
    original_rgba: bytes,
    edited_rgba: bytes,
    *,
    force_reindex_pixel_indexes: Iterable[int] = (),
    forced_color_indexes: Mapping[bytes, int] | None = None,
    forced_palette_indexes_by_pixel: Mapping[int, int] | None = None,
) -> Tim2InjectionResult:
    """Inject edited pixels while preserving the original TIM2 container.

    ``original_rgba`` must be an independently rendered view of ``data``.
    It establishes the mapping from existing 4-bit indexes to visible RGBA
    colors without implementing a second TIM2/CLUT decoder.  Edited pixels may
    use only colors already observed in that rendered source.
    """

    source = bytes(data)
    forced_pixels = frozenset(force_reindex_pixel_indexes)
    if any(
        not isinstance(pixel_index, int)
        or isinstance(pixel_index, bool)
        or not 0 <= pixel_index < CANARY_WIDTH * CANARY_HEIGHT
        for pixel_index in forced_pixels
    ):
        raise Tim2WritebackError(
            "forced 4-bpp pixel index is outside the image"
        )
    exact_indexes = dict(forced_color_indexes or {})
    for color, palette_index in exact_indexes.items():
        if not isinstance(color, bytes) or len(color) != RGBA_PIXEL_SIZE:
            raise Tim2WritebackError(
                "forced 4-bpp color must be four RGBA bytes"
            )
        if (
            not isinstance(palette_index, int)
            or isinstance(palette_index, bool)
            or not 0 <= palette_index <= 0x0F
        ):
            raise Tim2WritebackError(
                "forced 4-bpp palette index must fit one nibble"
            )
    exact_pixel_indexes = dict(forced_palette_indexes_by_pixel or {})
    for pixel_index, palette_index in exact_pixel_indexes.items():
        if (
            not isinstance(pixel_index, int)
            or isinstance(pixel_index, bool)
            or not 0 <= pixel_index < CANARY_WIDTH * CANARY_HEIGHT
        ):
            raise Tim2WritebackError(
                "forced 4-bpp pixel index is outside the image"
            )
        if (
            not isinstance(palette_index, int)
            or isinstance(palette_index, bool)
            or not 0 <= palette_index <= 0x0F
        ):
            raise Tim2WritebackError(
                "forced per-pixel palette index must fit one nibble"
            )
    picture = _validate_canary_layout(source)
    expected_rgba_size = CANARY_WIDTH * CANARY_HEIGHT * RGBA_PIXEL_SIZE
    for label, pixels in (
        ("original RGBA", original_rgba),
        ("edited RGBA", edited_rgba),
    ):
        if len(pixels) != expected_rgba_size:
            raise Tim2WritebackError(
                f"{label} has {len(pixels)} bytes, "
                f"expected {expected_rgba_size}"
            )

    image_offset = picture.offset + picture.header_size
    image_end = image_offset + picture.image_size
    packed_before = source[image_offset:image_end]
    indexes = _unpack_4bpp(packed_before)

    color_by_index = {}
    indexes_by_color = {}
    for pixel_index, palette_index in enumerate(indexes):
        color = _rgba_at(original_rgba, pixel_index)
        prior = color_by_index.setdefault(palette_index, color)
        if prior != color:
            x = pixel_index % CANARY_WIDTH
            y = pixel_index // CANARY_WIDTH
            raise Tim2WritebackError(
                f"rendered color for index {palette_index} is inconsistent "
                f"at ({x},{y})"
            )
        indexes_by_color.setdefault(color, set()).add(palette_index)

    for color, palette_index in exact_indexes.items():
        if color_by_index.get(palette_index) != color:
            raise Tim2WritebackError(
                f"forced palette index {palette_index} does not render as "
                f"{color.hex()}"
            )
    for pixel_index, palette_index in exact_pixel_indexes.items():
        edited_color = _rgba_at(edited_rgba, pixel_index)
        if color_by_index.get(palette_index) != edited_color:
            raise Tim2WritebackError(
                f"forced palette index {palette_index} at pixel "
                f"{pixel_index} does not render as {edited_color.hex()}"
            )

    packed_after = bytearray(packed_before)
    changed_pixel_count = 0
    for pixel_index, original_index in enumerate(indexes):
        original_color = _rgba_at(original_rgba, pixel_index)
        edited_color = _rgba_at(edited_rgba, pixel_index)
        force_reindex = pixel_index in forced_pixels
        if pixel_index in exact_pixel_indexes:
            replacement_index = exact_pixel_indexes[pixel_index]
        elif not force_reindex and edited_color == original_color:
            replacement_index = original_index
        else:
            if force_reindex and edited_color in exact_indexes:
                replacement_index = exact_indexes[edited_color]
            else:
                candidates = indexes_by_color.get(edited_color)
                if not candidates:
                    x = pixel_index % CANARY_WIDTH
                    y = pixel_index // CANARY_WIDTH
                    raise Tim2WritebackError(
                        f"edited color {edited_color.hex()} at ({x},{y}) "
                        "is not present in the source picture"
                    )
                replacement_index = min(candidates)
        if replacement_index != original_index:
            changed_pixel_count += 1

        byte_index = pixel_index // 2
        if pixel_index % 2 == 0:
            packed_after[byte_index] = (
                packed_after[byte_index] & 0xF0
            ) | replacement_index
        else:
            packed_after[byte_index] = (
                packed_after[byte_index] & 0x0F
            ) | (replacement_index << 4)

    packed_after_bytes = bytes(packed_after)
    output = source[:image_offset] + packed_after_bytes + source[image_end:]
    if len(output) != len(source):
        raise Tim2WritebackError("TIM2 injection changed the container size")
    reparsed = _validate_canary_layout(output)
    if reparsed != picture:
        raise Tim2WritebackError("TIM2 metadata changed after pixel injection")

    ranges = _changed_ranges(packed_before, packed_after_bytes)
    return Tim2InjectionResult(
        data=output,
        image_offset=image_offset,
        image_size=picture.image_size,
        changed_pixel_count=changed_pixel_count,
        changed_image_byte_count=sum(end - start for start, end in ranges),
        changed_image_byte_ranges=ranges,
        available_color_count=len(indexes_by_color),
    )


def replace_vt1_title_index(
    data: bytes,
    *,
    source_index: int,
    replacement_index: int,
    expected_occurrence_count: int,
) -> Tim2IndexReplacementResult:
    """Replace one existing index throughout VT1 title picture 0.

    The source image is stored in the PS2's indexed layout, so a global index
    substitution is intentionally coordinate-independent.  It is sufficient
    for a visible runtime canary and avoids pretending to implement a general
    PS2 swizzle-aware texture encoder.
    """

    for label, value in (
        ("source index", source_index),
        ("replacement index", replacement_index),
    ):
        if not isinstance(value, int) or isinstance(value, bool):
            raise Tim2WritebackError(f"{label} must be an integer")
        if not 0 <= value <= 0xFF:
            raise Tim2WritebackError(f"{label} must fit one byte")
    if (
        not isinstance(expected_occurrence_count, int)
        or isinstance(expected_occurrence_count, bool)
        or expected_occurrence_count < 0
    ):
        raise Tim2WritebackError(
            "expected occurrence count must be a non-negative integer"
        )

    source = bytes(data)
    record = _validate_vt1_title_layout(source)
    picture_index = 0
    picture = record.pictures[picture_index]
    image_offset = picture.offset + picture.header_size
    image_end = image_offset + picture.image_size
    image_before = source[image_offset:image_end]
    occurrence_count = image_before.count(source_index)
    if occurrence_count != expected_occurrence_count:
        raise Tim2WritebackError(
            f"VT1 title source index {source_index} occurs "
            f"{occurrence_count} times, expected "
            f"{expected_occurrence_count}"
        )
    if replacement_index not in image_before:
        raise Tim2WritebackError(
            f"VT1 title replacement index {replacement_index} "
            "is not present in picture 0"
        )

    image_after = image_before.replace(
        bytes([source_index]),
        bytes([replacement_index]),
    )
    output = source[:image_offset] + image_after + source[image_end:]
    if len(output) != len(source):
        raise Tim2WritebackError(
            "VT1 title index replacement changed the container size"
        )
    reparsed = _validate_vt1_title_layout(output)
    if reparsed != record:
        raise Tim2WritebackError(
            "VT1 title TIM2 metadata changed after index replacement"
        )

    ranges = _changed_ranges(image_before, image_after)
    changed_pixel_count = (
        0 if source_index == replacement_index else occurrence_count
    )
    return Tim2IndexReplacementResult(
        data=output,
        picture_index=picture_index,
        image_offset=image_offset,
        image_size=picture.image_size,
        source_index=source_index,
        replacement_index=replacement_index,
        source_index_occurrence_count=occurrence_count,
        changed_pixel_count=changed_pixel_count,
        changed_image_byte_count=sum(end - start for start, end in ranges),
        changed_image_byte_ranges=ranges,
        available_index_count=len(set(image_before)),
    )


__all__ = [
    "CANARY_CLUT_COLOR_COUNT",
    "CANARY_CLUT_SIZE",
    "CANARY_HEIGHT",
    "CANARY_IMAGE_SIZE",
    "CANARY_WIDTH",
    "Tim2Indexed8InjectionResult",
    "Tim2IndexReplacementResult",
    "Tim2InjectionResult",
    "Tim2WritebackError",
    "VT1_TITLE_CLUT_COLOR_COUNT",
    "VT1_TITLE_CLUT_SIZE",
    "VT1_TITLE_HEIGHT",
    "VT1_TITLE_IMAGE_SIZE",
    "VT1_TITLE_PICTURE_COUNT",
    "VT1_TITLE_WIDTH",
    "extract_vt1_title_indexes",
    "inject_indexed4_rgba",
    "inject_vt1_title_indexes",
    "render_vt1_title_rgba",
    "replace_vt1_title_index",
    "swizzle_psmt8",
    "unswizzle_psmt8",
]
