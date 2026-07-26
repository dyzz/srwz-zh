"""Strict, read-only metadata parser for PlayStation 2 TIM2 textures.

The parser intentionally stops at format structure and metadata.  It does not
decode pixels, quantize palettes, or write TIM2 files.  This keeps asset
inventory independent from ImageMagick while avoiding an unsupported encoder.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


TIM2_MAGIC = b"TIM2"
TIM2_FILE_HEADER_SIZE = 16
TIM2_ALIGNED_FILE_HEADER_SIZE = 128
TIM2_PICTURE_HEADER_SIZE = 48

BITS_PER_PIXEL = {
    1: 16,
    2: 24,
    3: 32,
    4: 4,
    5: 8,
}

CLUT_BITS_PER_COLOR = {
    1: 16,
    2: 24,
    3: 32,
}


class Tim2Error(ValueError):
    """The candidate bytes do not satisfy the supported TIM2 contract."""


@dataclass(frozen=True)
class Tim2Picture:
    """One picture and its storage metadata within a TIM2 file."""

    offset: int
    total_size: int
    clut_size: int
    image_size: int
    header_size: int
    clut_color_count: int
    picture_format: int
    mipmap_count: int
    clut_type: int
    image_type: int
    width: int
    height: int
    gs_tex0: int
    gs_tex1: int
    gs_regs: int
    gs_tex_clut: int
    uses_shared_clut: bool

    @property
    def bits_per_pixel(self) -> int:
        return BITS_PER_PIXEL[self.image_type]

    @property
    def clut_bits_per_color(self) -> int | None:
        return CLUT_BITS_PER_COLOR.get(self.clut_type & 0x0F)


@dataclass(frozen=True)
class Tim2File:
    """A validated TIM2 record embedded at ``offset`` in a larger byte stream."""

    offset: int
    version: int
    format_type: int
    pictures: tuple[Tim2Picture, ...]
    size: int

    @property
    def end(self) -> int:
        return self.offset + self.size


def _unpack_from(
    format_string: str,
    data: memoryview,
    offset: int,
    limit: int,
    context: str,
) -> tuple:
    size = struct.calcsize(format_string)
    if offset < 0 or offset + size > limit:
        raise Tim2Error(f"truncated {context} at 0x{offset:X}")
    return struct.unpack_from(format_string, data, offset)


def parse_tim2(
    data: bytes | bytearray | memoryview,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> Tim2File:
    """Parse one TIM2 record without consuming unrelated trailing bytes.

    Only the version 4 layout observed in the SRWZ assets is accepted.  The
    returned ``size`` is derived from the validated picture records, so callers
    can safely continue scanning a containing archive after the TIM2 payload.
    """

    source = memoryview(data).cast("B")
    end = len(source) if limit is None else limit
    if offset < 0 or end < offset or end > len(source):
        raise Tim2Error("TIM2 offset/limit is outside the input")
    if offset + TIM2_FILE_HEADER_SIZE > end:
        raise Tim2Error(f"truncated TIM2 file header at 0x{offset:X}")
    if source[offset : offset + 4].tobytes() != TIM2_MAGIC:
        raise Tim2Error(f"missing TIM2 magic at 0x{offset:X}")

    version, format_type, picture_count = _unpack_from(
        "<BBH",
        source,
        offset + 4,
        end,
        "TIM2 file header",
    )
    if version != 4:
        raise Tim2Error(f"unsupported TIM2 version {version} at 0x{offset:X}")
    if format_type not in (0, 1):
        raise Tim2Error(
            f"unsupported TIM2 format type {format_type} at 0x{offset:X}"
        )
    if picture_count <= 0:
        raise Tim2Error(f"TIM2 picture count must be positive at 0x{offset:X}")

    file_header_size = (
        TIM2_FILE_HEADER_SIZE
        if format_type == 0
        else TIM2_ALIGNED_FILE_HEADER_SIZE
    )
    picture_offset = offset + file_header_size
    pictures = []

    for picture_index in range(picture_count):
        (
            total_size,
            clut_size,
            image_size,
            header_size,
            clut_color_count,
            picture_format,
            mipmap_count,
            clut_type,
            image_type,
            width,
            height,
            gs_tex0,
            gs_tex1,
            gs_regs,
            gs_tex_clut,
        ) = _unpack_from(
            "<IIIHHBBBBHHQQII",
            source,
            picture_offset,
            end,
            f"TIM2 picture {picture_index} header",
        )

        if header_size < TIM2_PICTURE_HEADER_SIZE:
            raise Tim2Error(
                f"TIM2 picture {picture_index} header is only "
                f"{header_size} bytes"
            )
        if total_size != header_size + image_size + clut_size:
            raise Tim2Error(
                f"TIM2 picture {picture_index} size fields disagree: "
                f"{total_size} != {header_size}+{image_size}+{clut_size}"
            )
        if total_size <= header_size:
            raise Tim2Error(f"TIM2 picture {picture_index} has no image data")
        if picture_offset + total_size > end:
            raise Tim2Error(
                f"TIM2 picture {picture_index} exceeds input at "
                f"0x{picture_offset:X}"
            )
        if width <= 0 or height <= 0:
            raise Tim2Error(
                f"TIM2 picture {picture_index} has invalid "
                f"{width}x{height} dimensions"
            )
        if mipmap_count <= 0:
            raise Tim2Error(
                f"TIM2 picture {picture_index} has zero mipmap count"
            )
        if image_type not in BITS_PER_PIXEL:
            raise Tim2Error(
                f"TIM2 picture {picture_index} has unsupported "
                f"image type {image_type}"
            )

        indexed = image_type in (4, 5)
        clut_depth = clut_type & 0x0F
        uses_shared_clut = False
        if indexed:
            if clut_size == 0 and clut_color_count == 0:
                uses_shared_clut = any(
                    prior.image_type == image_type
                    and prior.clut_size > 0
                    and (prior.clut_type & 0x0F) == clut_depth
                    for prior in pictures
                )
                if not uses_shared_clut:
                    raise Tim2Error(
                        f"TIM2 picture {picture_index} has no indexed palette"
                    )
            elif (
                clut_size <= 0
                or clut_color_count <= 0
                or clut_depth not in CLUT_BITS_PER_COLOR
            ):
                raise Tim2Error(
                    f"TIM2 picture {picture_index} has invalid indexed palette"
                )
        if not indexed and clut_size == 0 and clut_color_count != 0:
            raise Tim2Error(
                f"TIM2 picture {picture_index} has colors but no palette"
            )

        pictures.append(
            Tim2Picture(
                offset=picture_offset,
                total_size=total_size,
                clut_size=clut_size,
                image_size=image_size,
                header_size=header_size,
                clut_color_count=clut_color_count,
                picture_format=picture_format,
                mipmap_count=mipmap_count,
                clut_type=clut_type,
                image_type=image_type,
                width=width,
                height=height,
                gs_tex0=gs_tex0,
                gs_tex1=gs_tex1,
                gs_regs=gs_regs,
                gs_tex_clut=gs_tex_clut,
                uses_shared_clut=uses_shared_clut,
            )
        )
        picture_offset += total_size

    return Tim2File(
        offset=offset,
        version=version,
        format_type=format_type,
        pictures=tuple(pictures),
        size=picture_offset - offset,
    )


def scan_tim2(
    data: bytes | bytearray | memoryview,
    *,
    start: int = 0,
    limit: int | None = None,
) -> tuple[Tim2File, ...]:
    """Return structurally valid, non-overlapping TIM2 records in a byte stream."""

    source = memoryview(data).cast("B")
    end = len(source) if limit is None else limit
    if start < 0 or end < start or end > len(source):
        raise Tim2Error("TIM2 scan range is outside the input")

    raw = source.tobytes()
    records = []
    position = start
    while position + len(TIM2_MAGIC) <= end:
        candidate = raw.find(TIM2_MAGIC, position, end)
        if candidate < 0:
            break
        try:
            record = parse_tim2(source, offset=candidate, limit=end)
        except Tim2Error:
            position = candidate + 1
            continue
        records.append(record)
        position = record.end
    return tuple(records)


def extract_tim2_record(
    data: bytes | bytearray | memoryview,
    record_index: int,
) -> tuple[Tim2File, bytes]:
    """Return one validated embedded TIM2 record and its exact stored bytes."""

    records = scan_tim2(data)
    if not 0 <= record_index < len(records):
        raise Tim2Error(
            f"TIM2 record index {record_index} is outside 0..{len(records) - 1}"
        )
    record = records[record_index]
    source = memoryview(data).cast("B")
    return record, source[record.offset : record.end].tobytes()


__all__ = [
    "BITS_PER_PIXEL",
    "CLUT_BITS_PER_COLOR",
    "TIM2_MAGIC",
    "Tim2Error",
    "Tim2File",
    "Tim2Picture",
    "extract_tim2_record",
    "parse_tim2",
    "scan_tim2",
]
