"""Pure helpers for provenance-preserving SRWZ TIM2 image export.

The bulk exporter keeps exact TIM2 records as the archival source and renders
one PNG per picture.  Multi-picture records need a temporary single-picture
view because ImageMagick's TIM2 reader only accepts one picture per file.
Shared palettes are copied into that temporary view; the exact source record is
never modified.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import PurePosixPath

from .tim2 import Tim2Error, Tim2File, parse_tim2


class ImageExportError(ValueError):
    """An archive index or temporary TIM2 view is not safe to export."""


@dataclass(frozen=True)
class StandalonePictureView:
    """One render-only TIM2 view and the palette bank used by that view."""

    data: bytes
    palette_source_picture_index: int | None
    palette_bank_index: int | None
    palette_bank_count: int
    palette_colors_per_bank: int | None


def parse_seg_offsets(data: bytes, archive_size: int) -> tuple[int, ...]:
    """Parse a BTL ``.SEG`` little-endian offset table.

    Observed SRWZ tables start at zero and include the paired ``.BIN`` size as
    their final meaningful offset.  A few small OP tables pad the remaining
    entries with zeroes, which are accepted only after that exact terminal
    offset.
    """

    if archive_size <= 0:
        raise ImageExportError("SEG archive size must be positive")
    if len(data) < 8 or len(data) % 4:
        raise ImageExportError(
            "SEG data must contain at least two little-endian uint32 values"
        )

    values = struct.unpack(f"<{len(data) // 4}I", data)
    try:
        terminal_index = values.index(archive_size)
    except ValueError as error:
        raise ImageExportError(
            f"SEG table does not contain archive size {archive_size}"
        ) from error

    offsets = values[: terminal_index + 1]
    padding = values[terminal_index + 1 :]
    if any(padding):
        raise ImageExportError("SEG table has nonzero values after archive end")
    if offsets[0] != 0:
        raise ImageExportError("SEG table must start at offset zero")
    if len(offsets) < 2:
        raise ImageExportError("SEG table does not describe any chunks")
    if any(left >= right for left, right in zip(offsets, offsets[1:])):
        raise ImageExportError(
            "SEG offsets must be strictly increasing through archive end"
        )
    if offsets[-1] != archive_size:
        raise ImageExportError("SEG terminal offset does not match archive size")
    return tuple(offsets)


def safe_member_parts(member: str) -> tuple[str, ...]:
    """Return safe POSIX path parts for an ISO member."""

    if "\\" in member:
        raise ImageExportError("ISO member paths must use forward slashes")
    path = PurePosixPath(member)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise ImageExportError(f"unsafe ISO member path: {member!r}")
    return path.parts


def _compatible_palette_index(record: Tim2File, picture_index: int) -> int:
    picture = record.pictures[picture_index]
    for prior_index in range(picture_index - 1, -1, -1):
        prior = record.pictures[prior_index]
        if (
            prior.image_type == picture.image_type
            and prior.clut_size > 0
            and (prior.clut_type & 0x0F) == (picture.clut_type & 0x0F)
        ):
            return prior_index
    raise ImageExportError(
        f"picture {picture_index} declares a shared CLUT without "
        "a compatible earlier palette"
    )


def standalone_picture_tim2(
    source: bytes,
    record: Tim2File,
    picture_index: int,
    *,
    palette_bank_index: int = 0,
) -> StandalonePictureView:
    """Build a render-only single-picture TIM2 view.

    Indexed pictures are reduced to one logical palette bank: 16 colors for
    4-bpp and 256 colors for 8-bpp.  This avoids ImageMagick applying its
    32-color CSM1 page shuffle across unrelated 4-bpp banks.  Other banks remain
    byte-exact in the retained source record and can be requested explicitly.

    ``source`` is not mutated, and callers should preserve the exact
    ``source[record.offset:record.end]`` bytes as the archival record.
    """

    if not 0 <= picture_index < len(record.pictures):
        raise ImageExportError(
            f"picture index {picture_index} is outside "
            f"0..{len(record.pictures) - 1}"
        )
    if record.offset < 0 or record.end > len(source):
        raise ImageExportError("TIM2 record is outside the source payload")

    first_picture_offset = record.pictures[0].offset
    file_header_size = first_picture_offset - record.offset
    if file_header_size not in (16, 128):
        raise ImageExportError(
            f"unexpected TIM2 file header size {file_header_size}"
        )

    file_header = bytearray(
        source[record.offset : record.offset + file_header_size]
    )
    struct.pack_into("<H", file_header, 6, 1)

    picture = record.pictures[picture_index]
    palette_source_index = None
    palette_bank_count = 0
    palette_colors_per_bank = None
    if picture.image_type in (4, 5):
        palette_source_index = (
            _compatible_palette_index(record, picture_index)
            if picture.uses_shared_clut
            else picture_index
        )
        palette_source = record.pictures[palette_source_index]
        palette_colors_per_bank = 16 if picture.image_type == 4 else 256
        if (
            palette_source.clut_color_count <= 0
            or palette_source.clut_color_count % palette_colors_per_bank
        ):
            raise ImageExportError(
                f"picture {picture_index} palette has "
                f"{palette_source.clut_color_count} colors, which is not "
                f"a multiple of {palette_colors_per_bank}"
            )
        palette_bank_count = (
            palette_source.clut_color_count // palette_colors_per_bank
        )
        if not 0 <= palette_bank_index < palette_bank_count:
            raise ImageExportError(
                f"palette bank {palette_bank_index} is outside "
                f"0..{palette_bank_count - 1}"
            )
        color_bytes = palette_source.clut_bits_per_color
        if color_bytes is None or color_bytes % 8:
            raise ImageExportError("indexed palette color depth is invalid")
        color_bytes //= 8
        palette_start = (
            palette_source.offset
            + palette_source.header_size
            + palette_source.image_size
        )
        palette_end = palette_source.offset + palette_source.total_size
        all_palettes = source[palette_start:palette_end]
        if (
            len(all_palettes) != palette_source.clut_size
            or len(all_palettes)
            != palette_source.clut_color_count * color_bytes
        ):
            raise ImageExportError("shared CLUT source bytes are inconsistent")
        palette_bank_size = palette_colors_per_bank * color_bytes
        bank_start = palette_bank_index * palette_bank_size
        palette = all_palettes[bank_start : bank_start + palette_bank_size]

        picture_prefix_end = (
            picture.offset + picture.header_size + picture.image_size
        )
        picture_data = bytearray(source[picture.offset:picture_prefix_end])
        struct.pack_into(
            "<I",
            picture_data,
            0,
            picture.header_size + picture.image_size + len(palette),
        )
        struct.pack_into("<I", picture_data, 4, len(palette))
        struct.pack_into(
            "<H",
            picture_data,
            14,
            palette_colors_per_bank,
        )
        picture_data.extend(palette)
    else:
        if palette_bank_index != 0:
            raise ImageExportError(
                "direct-color pictures do not have palette banks"
            )
        picture_data = bytearray(
            source[picture.offset : picture.offset + picture.total_size]
        )

    standalone = bytes(file_header) + bytes(picture_data)
    try:
        parsed = parse_tim2(standalone)
    except Tim2Error as error:
        raise ImageExportError(
            f"temporary picture {picture_index} is not a valid TIM2: {error}"
        ) from error
    if parsed.size != len(standalone) or len(parsed.pictures) != 1:
        raise ImageExportError(
            "temporary single-picture TIM2 has inconsistent boundaries"
        )
    parsed_picture = parsed.pictures[0]
    if (
        parsed_picture.width,
        parsed_picture.height,
        parsed_picture.image_type,
    ) != (picture.width, picture.height, picture.image_type):
        raise ImageExportError(
            "temporary single-picture TIM2 changed picture geometry"
        )
    if parsed_picture.uses_shared_clut:
        raise ImageExportError(
            "temporary single-picture TIM2 still depends on a shared CLUT"
        )
    return StandalonePictureView(
        data=standalone,
        palette_source_picture_index=palette_source_index,
        palette_bank_index=(
            palette_bank_index if palette_source_index is not None else None
        ),
        palette_bank_count=palette_bank_count,
        palette_colors_per_bank=palette_colors_per_bank,
    )


__all__ = [
    "ImageExportError",
    "StandalonePictureView",
    "parse_seg_offsets",
    "safe_member_parts",
    "standalone_picture_tim2",
]
