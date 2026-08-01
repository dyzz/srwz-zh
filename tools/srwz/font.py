"""Clean-room helpers for the SRWZ VT1 font segment and code table.

Static analysis of the original renderer at ``0x13C5C0`` establishes the
decoded glyph contract used here: source glyph ``n`` begins at ``n * 288``;
the renderer copies 24 rows of 12 bytes into a 512-pixel-wide 4-bpp cache.
Within each source byte the low nibble is the left pixel.
"""

from __future__ import annotations

import binascii
import hashlib
import struct
import zlib
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .codec import decode
from .iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from .text import TextTable


FONT_SEGMENT_INDEX = 2
GLYPH_WIDTH = 24
GLYPH_HEIGHT = 24
GLYPH_BITS_PER_PIXEL = 4
GLYPH_ROW_BYTES = 12
GLYPH_SIZE = GLYPH_ROW_BYTES * GLYPH_HEIGHT
GLYPH_COUNT = 4480

ASCII_FIRST = 0x20
ASCII_LAST = 0x7E
ASCII_GLYPH_BASE = 0xBF
ASCII_GLYPH_SKIP_FROM = 0x5E

STANDARD_CODE_START = 0x8140
EXTENDED_CODE_START = 0x989F
STANDARD_LEAD_START = 0x81
STANDARD_LEAD_END = 0x98
STANDARD_TRAIL_START = 0x40
STANDARD_GLYPH_STRIDE = 192

# The original renderer at 0x13A8B0 loads virtual address 0x3F7D70.
# In the pinned ELF load segment (VMA 0x100000, file offset 0x1A80), that
# address corresponds to file offset 0x2F97F0.
EXTENDED_GLYPH_TABLE_VIRTUAL_ADDRESS = 0x3F7D70
EXTENDED_GLYPH_TABLE_FILE_OFFSET = 0x2F97F0
EXTENDED_GLYPH_ENTRY_SIZE = 4

# The current upstream candidate changes glyphs 167..286.  These are aligned
# source-glyph boundaries, unlike the earlier 108 * 320 byte hypothesis.
UPSTREAM_CHANGED_GLYPH_START = 167
UPSTREAM_CHANGED_GLYPH_COUNT = 120
UPSTREAM_CHANGED_REGION_START = UPSTREAM_CHANGED_GLYPH_START * GLYPH_SIZE
UPSTREAM_CHANGED_REGION_END = (
    UPSTREAM_CHANGED_REGION_START + UPSTREAM_CHANGED_GLYPH_COUNT * GLYPH_SIZE
)

SHIFT_JIS_TRAILS = tuple(list(range(0x40, 0x7F)) + list(range(0x80, 0xFD)))
# The original standard renderer does not validate Shift-JIS trail bytes.  It
# consumes the low byte directly and addresses a 192-glyph row.  These four
# values are therefore formula-addressable gaps rather than valid Shift-JIS
# codes.  They are kept separate from the conservative candidate pool and
# require an explicit profile opt-in.
RAW_STANDARD_TRAILS = (0x7F, 0xFD, 0xFE, 0xFF)


def is_cjk_unified_ideograph(character: str) -> bool:
    """Return whether one character belongs to a CJK ideograph block."""

    if not isinstance(character, str) or len(character) != 1:
        raise ValueError("CJK classification needs one character")
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x323AF
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def glyph_raster_metrics(pixels: bytes) -> dict:
    """Return deterministic optical metrics for one decoded 4-bpp glyph."""

    if len(pixels) != GLYPH_WIDTH * GLYPH_HEIGHT:
        raise ValueError("glyph raster must contain exactly 24x24 pixels")
    if any(pixel > 0x0F for pixel in pixels):
        raise ValueError("glyph raster pixel exceeds 4-bpp range")
    occupied = [
        (index % GLYPH_WIDTH, index // GLYPH_WIDTH, value)
        for index, value in enumerate(pixels)
        if value
    ]
    if not occupied:
        return {
            "ink_pixel_count": 0,
            "ink_value_sum": 0,
            "bbox_x": None,
            "bbox_y": None,
            "bbox_width": 0,
            "bbox_height": 0,
            "outer_edge_touch": False,
            "outer_edge_sides": [],
        }
    xs = [x for x, _, _ in occupied]
    ys = [y for _, y, _ in occupied]
    left = min(xs)
    right = max(xs)
    top = min(ys)
    bottom = max(ys)
    sides = [
        side
        for side, touched in (
            ("left", left == 0),
            ("right", right == GLYPH_WIDTH - 1),
            ("top", top == 0),
            ("bottom", bottom == GLYPH_HEIGHT - 1),
        )
        if touched
    ]
    return {
        "ink_pixel_count": len(occupied),
        "ink_value_sum": sum(value for _, _, value in occupied),
        "bbox_x": left,
        "bbox_y": top,
        "bbox_width": right - left + 1,
        "bbox_height": bottom - top + 1,
        "outer_edge_touch": bool(sides),
        "outer_edge_sides": sides,
    }


@dataclass(frozen=True)
class DecodedFontSegment:
    compressed_size: int
    compressed_sha256: str
    consumed: int
    padding: int
    padding_all_zero: bool
    decoded: bytes

    def to_metadata(self) -> dict:
        return {
            "compressed_size": self.compressed_size,
            "compressed_sha256": self.compressed_sha256,
            "consumed": self.consumed,
            "padding": self.padding,
            "padding_all_zero": self.padding_all_zero,
            "decoded_size": len(self.decoded),
            "decoded_sha256": sha256_bytes(self.decoded),
        }


@dataclass(frozen=True)
class FontPatchAnalysis:
    original_sha256: str
    candidate_sha256: str
    decoded_size: int
    changed_byte_count: int
    difference_range_count: int
    first_changed_offset: Optional[int]
    last_changed_offset: Optional[int]
    region_start: int
    region_end: int
    block_size: int
    block_count: int
    changed_block_indices: tuple
    unchanged_block_indices: tuple
    changed_bytes_outside_region: int
    glyph_size: int
    glyph_count: int
    changed_glyph_indices: tuple
    changed_ascii_glyph_indices: tuple
    unchanged_ascii_glyph_indices: tuple

    def to_mapping(self) -> dict:
        return {
            "original_sha256": self.original_sha256,
            "candidate_sha256": self.candidate_sha256,
            "decoded_size": self.decoded_size,
            "changed_byte_count": self.changed_byte_count,
            "difference_range_count": self.difference_range_count,
            "first_changed_offset": self.first_changed_offset,
            "last_changed_offset": self.last_changed_offset,
            "region_start": self.region_start,
            "region_end": self.region_end,
            "block_size": self.block_size,
            "block_count": self.block_count,
            "changed_block_count": len(self.changed_block_indices),
            "changed_block_indices": list(self.changed_block_indices),
            "unchanged_block_indices": list(self.unchanged_block_indices),
            "changed_bytes_outside_region": self.changed_bytes_outside_region,
            "glyph_size": self.glyph_size,
            "glyph_count": self.glyph_count,
            "changed_glyph_count": len(self.changed_glyph_indices),
            "changed_glyph_indices": list(self.changed_glyph_indices),
            "changed_ascii_glyph_count": len(self.changed_ascii_glyph_indices),
            "changed_ascii_glyph_indices": list(self.changed_ascii_glyph_indices),
            "unchanged_ascii_glyph_indices": list(self.unchanged_ascii_glyph_indices),
        }


@dataclass(frozen=True)
class CodebookInventory:
    mapped_code_count: int
    unique_character_count: int
    duplicate_character_count: int
    lead_bytes: tuple
    candidate_capacity: int
    candidate_unmapped_codes: tuple

    def to_mapping(self) -> dict:
        return {
            "mapped_code_count": self.mapped_code_count,
            "unique_character_count": self.unique_character_count,
            "duplicate_character_count": self.duplicate_character_count,
            "lead_byte_count": len(self.lead_bytes),
            "lead_bytes": [f"{value:02X}" for value in self.lead_bytes],
            "candidate_capacity": self.candidate_capacity,
            "candidate_unmapped_count": len(self.candidate_unmapped_codes),
            "candidate_unmapped_codes": [
                f"{value:04X}" for value in self.candidate_unmapped_codes
            ],
            "classification": (
                "Candidate two-byte codes only; glyph backing and runtime "
                "safety require font-slot verification."
            ),
        }


@dataclass(frozen=True)
class ExtendedGlyphEntry:
    """One four-byte record from the original executable's glyph table."""

    code: int
    row: int
    packed_position: int
    glyph_index: int
    table_offset: int

    def to_mapping(self) -> dict:
        return {
            "code": f"{self.code:04X}",
            "row": self.row,
            "packed_position": self.packed_position,
            "glyph_index": self.glyph_index,
            "table_offset": self.table_offset,
        }


@dataclass(frozen=True)
class GlyphCodeMappingAnalysis:
    """Coverage of the pinned text table by the original glyph resolver."""

    text_code_count: int
    standard_text_code_count: int
    extended_table_entry_count: int
    extended_table_unique_code_count: int
    reachable_extended_entry_count: int
    reachable_extended_unique_code_count: int
    reachable_extended_duplicate_count: int
    unreachable_extended_entry_count: int
    supported_extended_text_code_count: int
    extended_codes_absent_from_text_table: tuple
    supported_text_code_count: int
    unsupported_text_codes: tuple
    referenced_glyph_count: int
    glyphs_not_referenced_by_text_table_count: int
    standard_extended_glyph_overlap_count: int

    def to_mapping(self) -> dict:
        return {
            "text_code_count": self.text_code_count,
            "standard_text_code_count": self.standard_text_code_count,
            "extended_table_entry_count": self.extended_table_entry_count,
            "extended_table_unique_code_count": (self.extended_table_unique_code_count),
            "reachable_extended_entry_count": (self.reachable_extended_entry_count),
            "reachable_extended_unique_code_count": (
                self.reachable_extended_unique_code_count
            ),
            "reachable_extended_duplicate_count": (
                self.reachable_extended_duplicate_count
            ),
            "unreachable_extended_entry_count": (self.unreachable_extended_entry_count),
            "supported_extended_text_code_count": (
                self.supported_extended_text_code_count
            ),
            "extended_codes_absent_from_text_table": [
                f"{code:04X}" for code in self.extended_codes_absent_from_text_table
            ],
            "supported_text_code_count": self.supported_text_code_count,
            "unsupported_text_code_count": len(self.unsupported_text_codes),
            "referenced_glyph_count": self.referenced_glyph_count,
            "glyphs_not_referenced_by_text_table_count": (
                self.glyphs_not_referenced_by_text_table_count
            ),
            "standard_extended_glyph_overlap_count": (
                self.standard_extended_glyph_overlap_count
            ),
            "classification": (
                "Glyphs not referenced by this pinned text table are not "
                "automatically safe to overwrite; runtime use still needs "
                "corpus and emulator validation."
            ),
        }


def decode_font_stream(data: bytes) -> DecodedFontSegment:
    result = decode(data)
    padding = data[result.consumed :]
    return DecodedFontSegment(
        compressed_size=len(data),
        compressed_sha256=sha256_bytes(data),
        consumed=result.consumed,
        padding=len(padding),
        padding_all_zero=all(value == 0 for value in padding),
        decoded=result.output,
    )


def decode_vt1_font_segment(
    executable: bytes,
    vt1: bytes,
    *,
    segment_index: int = FONT_SEGMENT_INDEX,
) -> DecodedFontSegment:
    offsets = read_executable_archive_offsets(
        executable,
        CORE_ARCHIVE_SPECS["VT1.BIN"],
        len(vt1),
    )
    if not 0 <= segment_index < len(offsets) - 1:
        raise ValueError("font segment index is outside VT1")
    return decode_font_stream(vt1[offsets[segment_index] : offsets[segment_index + 1]])


def _difference_range_count(indices: Iterable[int]) -> int:
    count = 0
    previous = None
    for index in indices:
        if previous is None or index != previous + 1:
            count += 1
        previous = index
    return count


def ascii_glyph_index(code: int) -> int:
    """Map one printable ASCII byte to the glyph index used by the patch."""

    if not isinstance(code, int):
        raise TypeError("ASCII code must be an integer")
    if not ASCII_FIRST <= code <= ASCII_LAST:
        raise ValueError("ASCII code is outside 0x20..0x7E")
    return (
        code
        - ASCII_FIRST
        + ASCII_GLYPH_BASE
        + (1 if code >= ASCII_GLYPH_SKIP_FROM else 0)
    )


def standard_glyph_index(
    code: int,
    *,
    glyph_count: int = GLYPH_COUNT,
) -> int:
    """Resolve a code below 0x989F using the original renderer's formula."""

    if not isinstance(code, int):
        raise TypeError("text code must be an integer")
    if not 0 <= code <= 0xFFFF:
        raise ValueError("text code is outside two bytes")
    lead = code >> 8
    trail = code & 0xFF
    if (
        not STANDARD_LEAD_START <= lead <= STANDARD_LEAD_END
        or trail < STANDARD_TRAIL_START
        or code >= EXTENDED_CODE_START
    ):
        raise ValueError("text code is outside the standard glyph branch")
    index = (
        (lead - STANDARD_LEAD_START) * STANDARD_GLYPH_STRIDE
        + trail
        - STANDARD_TRAIL_START
    )
    if not 0 <= index < glyph_count:
        raise ValueError("standard text code resolves outside font data")
    return index


def standard_code_for_glyph_index(
    glyph_index: int,
    *,
    glyph_count: int = GLYPH_COUNT,
) -> int:
    """Return the original renderer code for one sequential glyph slot.

    The standard branch is a complete 192-column view of the fixed 4,480
    glyph store.  Its byte code is sequential by glyph slot, except that the
    low byte wraps from ``0xFF`` to ``0x40`` when the lead byte advances.
    """

    if not isinstance(glyph_index, int) or isinstance(glyph_index, bool):
        raise TypeError("glyph index must be an integer")
    if not 0 <= glyph_index < glyph_count:
        raise ValueError("glyph index is outside font data")
    lead = STANDARD_LEAD_START + glyph_index // STANDARD_GLYPH_STRIDE
    trail = STANDARD_TRAIL_START + glyph_index % STANDARD_GLYPH_STRIDE
    code = (lead << 8) | trail
    if standard_glyph_index(code, glyph_count=glyph_count) != glyph_index:
        raise ValueError("glyph index has no standard renderer code")
    return code


def extended_glyph_index(row: int, packed_position: int) -> int:
    """Decode the signed row and packed 8-bit position used by the table."""

    if not isinstance(row, int) or not -0x80 <= row <= 0x7F:
        raise ValueError("extended glyph row is outside signed byte range")
    if not isinstance(packed_position, int) or not 0 <= packed_position <= 0xFF:
        raise ValueError("extended glyph position is outside byte range")
    # The renderer spells this out as row * 7 * 32, followed by the high
    # nibble * 16 and the low nibble.  The latter two terms equal the byte.
    return row * 224 + packed_position


def read_extended_glyph_table(
    executable: bytes,
    *,
    table_offset: int = EXTENDED_GLYPH_TABLE_FILE_OFFSET,
    glyph_count: int = GLYPH_COUNT,
    max_entries: int = 4096,
) -> tuple[ExtendedGlyphEntry, ...]:
    """Read the zero-terminated original code-to-glyph extension table."""

    if not 0 <= table_offset < len(executable):
        raise ValueError("extended glyph table is outside executable")
    if max_entries <= 0:
        raise ValueError("extended glyph table limit must be positive")

    entries = []
    for ordinal in range(max_entries):
        offset = table_offset + ordinal * EXTENDED_GLYPH_ENTRY_SIZE
        if offset + EXTENDED_GLYPH_ENTRY_SIZE > len(executable):
            raise ValueError("extended glyph table is truncated")
        code, row, packed_position = struct.unpack_from(
            "<HbB",
            executable,
            offset,
        )
        if code == 0:
            return tuple(entries)
        index = extended_glyph_index(row, packed_position)
        if not 0 <= index < glyph_count:
            raise ValueError("extended glyph entry resolves outside font data")
        entries.append(
            ExtendedGlyphEntry(
                code=code,
                row=row,
                packed_position=packed_position,
                glyph_index=index,
                table_offset=offset,
            )
        )
    raise ValueError("extended glyph table has no terminator within limit")


def extended_glyph_mapping(
    entries: Iterable[ExtendedGlyphEntry],
    *,
    reachable_only: bool = True,
) -> Mapping[int, int]:
    """Return the renderer's first-match mapping for extension records."""

    mapping = {}
    for entry in entries:
        if reachable_only and entry.code < EXTENDED_CODE_START:
            continue
        mapping.setdefault(entry.code, entry.glyph_index)
    return mapping


def glyph_index_for_code(
    code: int,
    extended_entries: Iterable[ExtendedGlyphEntry],
    *,
    glyph_count: int = GLYPH_COUNT,
) -> int:
    """Resolve one two-byte text code to a verified decoded-font index."""

    if not isinstance(code, int):
        raise TypeError("text code must be an integer")
    if code < EXTENDED_CODE_START:
        return standard_glyph_index(code, glyph_count=glyph_count)
    if not 0 <= code <= 0xFFFF:
        raise ValueError("text code is outside two bytes")
    index = extended_glyph_mapping(extended_entries).get(code)
    if index is None:
        raise ValueError("text code is absent from extended glyph table")
    if not 0 <= index < glyph_count:
        raise ValueError("extended text code resolves outside font data")
    return index


def analyze_glyph_code_mapping(
    table: TextTable,
    extended_entries: Iterable[ExtendedGlyphEntry],
    *,
    glyph_count: int = GLYPH_COUNT,
) -> GlyphCodeMappingAnalysis:
    """Measure which text-table codes have a statically verified glyph."""

    entries = tuple(extended_entries)
    reachable_entries = tuple(
        entry for entry in entries if entry.code >= EXTENDED_CODE_START
    )
    reachable_mapping = extended_glyph_mapping(reachable_entries)

    standard_codes = []
    standard_slots = set()
    supported_extended_codes = []
    extended_slots = set()
    unsupported_codes = []
    for code in sorted(table.characters):
        try:
            index = glyph_index_for_code(
                code,
                entries,
                glyph_count=glyph_count,
            )
        except ValueError:
            unsupported_codes.append(code)
            continue
        if code < EXTENDED_CODE_START:
            standard_codes.append(code)
            standard_slots.add(index)
        else:
            supported_extended_codes.append(code)
            extended_slots.add(index)

    extended_codes_absent = tuple(
        sorted(code for code in reachable_mapping if code not in table.characters)
    )
    referenced_slots = standard_slots | extended_slots
    return GlyphCodeMappingAnalysis(
        text_code_count=len(table.characters),
        standard_text_code_count=len(standard_codes),
        extended_table_entry_count=len(entries),
        extended_table_unique_code_count=len({entry.code for entry in entries}),
        reachable_extended_entry_count=len(reachable_entries),
        reachable_extended_unique_code_count=len(reachable_mapping),
        reachable_extended_duplicate_count=(
            len(reachable_entries) - len(reachable_mapping)
        ),
        unreachable_extended_entry_count=(len(entries) - len(reachable_entries)),
        supported_extended_text_code_count=len(supported_extended_codes),
        extended_codes_absent_from_text_table=extended_codes_absent,
        supported_text_code_count=(len(standard_codes) + len(supported_extended_codes)),
        unsupported_text_codes=tuple(unsupported_codes),
        referenced_glyph_count=len(referenced_slots),
        glyphs_not_referenced_by_text_table_count=(glyph_count - len(referenced_slots)),
        standard_extended_glyph_overlap_count=len(standard_slots & extended_slots),
    )


def glyph_offset(index: int, *, data_size: Optional[int] = None) -> int:
    """Return the decoded VT1 byte offset for one glyph index."""

    if not isinstance(index, int):
        raise TypeError("glyph index must be an integer")
    if index < 0:
        raise ValueError("glyph index must be non-negative")
    offset = index * GLYPH_SIZE
    if data_size is not None and offset + GLYPH_SIZE > data_size:
        raise ValueError("glyph index is outside decoded font data")
    return offset


def decode_glyph(data: bytes, index: int) -> bytes:
    """Decode one 24x24 4-bpp glyph to one byte per pixel (values 0..15)."""

    offset = glyph_offset(index, data_size=len(data))
    packed = data[offset : offset + GLYPH_SIZE]
    pixels = bytearray()
    for value in packed:
        pixels.append(value & 0x0F)
        pixels.append(value >> 4)
    return bytes(pixels)


def encode_glyph(pixels: Iterable[int]) -> bytes:
    """Pack one 24x24 nibble-valued glyph using the original byte order."""

    values = tuple(pixels)
    expected = GLYPH_WIDTH * GLYPH_HEIGHT
    if len(values) != expected:
        raise ValueError(f"glyph needs {expected} pixels, got {len(values)}")
    if any(not isinstance(value, int) or not 0 <= value <= 0x0F for value in values):
        raise ValueError("glyph pixels must be integer values in 0..15")
    output = bytearray()
    for position in range(0, len(values), 2):
        output.append(values[position] | (values[position + 1] << 4))
    return bytes(output)


def replace_glyph(data: bytes, index: int, pixels: Iterable[int]) -> bytes:
    """Return decoded font data with exactly one size-preserving glyph edit."""

    offset = glyph_offset(index, data_size=len(data))
    output = bytearray(data)
    output[offset : offset + GLYPH_SIZE] = encode_glyph(pixels)
    return bytes(output)


def grayscale_png(width: int, height: int, pixels: Iterable[int]) -> bytes:
    """Encode an 8-bit grayscale PNG using only the Python standard library."""

    if width <= 0 or height <= 0:
        raise ValueError("PNG dimensions must be positive")
    values = bytes(pixels)
    if len(values) != width * height:
        raise ValueError("PNG pixel count does not match its dimensions")

    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", checksum)
        )

    rows = b"".join(
        b"\x00" + values[y * width : (y + 1) * width] for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def render_glyph_grid(
    data: bytes,
    indices: Iterable[int],
    *,
    columns: int = 16,
    scale: int = 1,
    gap: int = 1,
) -> bytes:
    """Render selected glyphs to a grayscale PNG contact sheet."""

    selected = tuple(indices)
    if not selected:
        raise ValueError("select at least one glyph")
    if columns <= 0 or scale <= 0 or gap < 0:
        raise ValueError("grid geometry is invalid")
    rows = (len(selected) + columns - 1) // columns
    cell_width = GLYPH_WIDTH * scale
    cell_height = GLYPH_HEIGHT * scale
    width = columns * cell_width + (columns - 1) * gap
    height = rows * cell_height + (rows - 1) * gap
    canvas = bytearray(width * height)

    for ordinal, index in enumerate(selected):
        glyph = decode_glyph(data, index)
        origin_x = (ordinal % columns) * (cell_width + gap)
        origin_y = (ordinal // columns) * (cell_height + gap)
        for y in range(GLYPH_HEIGHT):
            for x in range(GLYPH_WIDTH):
                value = glyph[y * GLYPH_WIDTH + x] * 17
                target_x = origin_x + x * scale
                target_y = origin_y + y * scale
                for scaled_y in range(scale):
                    start = (target_y + scaled_y) * width + target_x
                    canvas[start : start + scale] = bytes([value]) * scale
    return grayscale_png(width, height, canvas)


def analyze_font_patch(
    original: bytes,
    candidate: bytes,
    *,
    region_start: int = UPSTREAM_CHANGED_REGION_START,
    block_size: int = GLYPH_SIZE,
    block_count: int = UPSTREAM_CHANGED_GLYPH_COUNT,
) -> FontPatchAnalysis:
    if len(original) != len(candidate):
        raise ValueError("decoded font segments must have the same size")
    if region_start < 0 or block_size <= 0 or block_count <= 0:
        raise ValueError("font analysis region must be positive")
    region_end = region_start + block_size * block_count
    if region_end > len(original):
        raise ValueError("font analysis region is outside decoded segment")

    changed = tuple(
        index
        for index, (before, after) in enumerate(zip(original, candidate))
        if before != after
    )
    changed_blocks = []
    unchanged_blocks = []
    for block_index in range(block_count):
        start = region_start + block_index * block_size
        end = start + block_size
        target = (
            changed_blocks
            if original[start:end] != candidate[start:end]
            else unchanged_blocks
        )
        target.append(block_index)

    if len(original) % GLYPH_SIZE:
        raise ValueError("decoded font size is not glyph aligned")
    changed_glyphs = tuple(
        index
        for index in range(len(original) // GLYPH_SIZE)
        if (
            original[index * GLYPH_SIZE : (index + 1) * GLYPH_SIZE]
            != candidate[index * GLYPH_SIZE : (index + 1) * GLYPH_SIZE]
        )
    )
    ascii_glyphs = tuple(
        ascii_glyph_index(code) for code in range(ASCII_FIRST, ASCII_LAST + 1)
    )
    changed_glyph_set = set(changed_glyphs)
    changed_ascii = tuple(index for index in ascii_glyphs if index in changed_glyph_set)
    unchanged_ascii = tuple(
        index for index in ascii_glyphs if index not in changed_glyph_set
    )

    return FontPatchAnalysis(
        original_sha256=sha256_bytes(original),
        candidate_sha256=sha256_bytes(candidate),
        decoded_size=len(original),
        changed_byte_count=len(changed),
        difference_range_count=_difference_range_count(changed),
        first_changed_offset=changed[0] if changed else None,
        last_changed_offset=changed[-1] if changed else None,
        region_start=region_start,
        region_end=region_end,
        block_size=block_size,
        block_count=block_count,
        changed_block_indices=tuple(changed_blocks),
        unchanged_block_indices=tuple(unchanged_blocks),
        changed_bytes_outside_region=sum(
            not region_start <= index < region_end for index in changed
        ),
        glyph_size=GLYPH_SIZE,
        glyph_count=len(original) // GLYPH_SIZE,
        changed_glyph_indices=changed_glyphs,
        changed_ascii_glyph_indices=changed_ascii,
        unchanged_ascii_glyph_indices=unchanged_ascii,
    )


def inventory_codebook(table: TextTable) -> CodebookInventory:
    lead_bytes = tuple(sorted({code >> 8 for code in table.characters}))
    candidate_codes = tuple(
        (lead << 8) | trail for lead in lead_bytes for trail in SHIFT_JIS_TRAILS
    )
    candidate_unmapped = tuple(
        code for code in candidate_codes if code not in table.characters
    )
    unique_characters = set(table.characters.values())
    return CodebookInventory(
        mapped_code_count=len(table.characters),
        unique_character_count=len(unique_characters),
        duplicate_character_count=(len(table.characters) - len(unique_characters)),
        lead_bytes=lead_bytes,
        candidate_capacity=len(candidate_codes),
        candidate_unmapped_codes=candidate_unmapped,
    )


def safe_standard_allocation_candidates(
    table: TextTable,
    extended_entries: Iterable[ExtendedGlyphEntry],
    *,
    reserved_codes: Iterable[int] = (),
    reserved_glyphs: Iterable[int] = (),
) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    """Return legacy and expanded code/glyph candidates in stable order.

    A candidate must be absent from the pinned text table and must not share
    a glyph with printable ASCII, a reachable table entry, the executable's
    extension table, or an explicitly reserved assignment.
    """

    entries = tuple(extended_entries)
    blocked_codes = set(reserved_codes)
    used_glyphs = set(reserved_glyphs)
    for code in table.characters:
        try:
            used_glyphs.add(glyph_index_for_code(code, entries))
        except ValueError:
            pass
    used_glyphs.update(
        ascii_glyph_index(code) for code in range(ASCII_FIRST, ASCII_LAST + 1)
    )
    used_glyphs.update(extended_glyph_mapping(entries).values())

    legacy_codes = inventory_codebook(table).candidate_unmapped_codes
    legacy_set = set(legacy_codes)
    expanded_codes = tuple(
        (lead << 8) | trail
        for lead in range(STANDARD_LEAD_START, STANDARD_LEAD_END + 1)
        for trail in SHIFT_JIS_TRAILS
        if (lead << 8) | trail not in table.characters
        and (lead << 8) | trail not in legacy_set
    )

    def usable(codes: Iterable[int]) -> tuple[tuple[int, int], ...]:
        result = []
        for code in codes:
            if code in blocked_codes:
                continue
            try:
                glyph_index = standard_glyph_index(code)
            except ValueError:
                continue
            if glyph_index in used_glyphs:
                continue
            result.append((code, glyph_index))
        return tuple(result)

    return usable(legacy_codes), usable(expanded_codes)


def raw_standard_allocation_candidates(
    table: TextTable,
    extended_entries: Iterable[ExtendedGlyphEntry],
    *,
    reserved_codes: Iterable[int] = (),
    reserved_glyphs: Iterable[int] = (),
) -> tuple[tuple[int, int], ...]:
    """Return renderer-addressable non-Shift-JIS trail gaps in stable order.

    This is intentionally not part of :func:`safe_standard_allocation_candidates`.
    The codes are accepted by the original renderer's standard formula but are
    not valid Shift-JIS byte pairs.  A production profile must opt in only
    after locking the original measurement/resolver instruction windows and
    suitable runtime precedent.
    """

    entries = tuple(extended_entries)
    blocked_codes = set(reserved_codes)
    used_glyphs = set(reserved_glyphs)
    for code in table.characters:
        try:
            used_glyphs.add(glyph_index_for_code(code, entries))
        except ValueError:
            pass
    used_glyphs.update(
        ascii_glyph_index(code) for code in range(ASCII_FIRST, ASCII_LAST + 1)
    )
    used_glyphs.update(extended_glyph_mapping(entries).values())

    result = []
    for trail in RAW_STANDARD_TRAILS:
        for lead in range(STANDARD_LEAD_START, STANDARD_LEAD_END + 1):
            code = (lead << 8) | trail
            if (
                code >= EXTENDED_CODE_START
                or code in table.characters
                or code in blocked_codes
            ):
                continue
            try:
                glyph_index = standard_glyph_index(code)
            except ValueError:
                continue
            if glyph_index in used_glyphs:
                continue
            result.append((code, glyph_index))
    return tuple(result)


__all__ = [
    "ASCII_FIRST",
    "ASCII_GLYPH_BASE",
    "ASCII_GLYPH_SKIP_FROM",
    "ASCII_LAST",
    "CodebookInventory",
    "DecodedFontSegment",
    "EXTENDED_CODE_START",
    "EXTENDED_GLYPH_ENTRY_SIZE",
    "EXTENDED_GLYPH_TABLE_FILE_OFFSET",
    "EXTENDED_GLYPH_TABLE_VIRTUAL_ADDRESS",
    "ExtendedGlyphEntry",
    "FONT_SEGMENT_INDEX",
    "FontPatchAnalysis",
    "GLYPH_COUNT",
    "GLYPH_BITS_PER_PIXEL",
    "GLYPH_HEIGHT",
    "GLYPH_ROW_BYTES",
    "GLYPH_SIZE",
    "GLYPH_WIDTH",
    "GlyphCodeMappingAnalysis",
    "RAW_STANDARD_TRAILS",
    "SHIFT_JIS_TRAILS",
    "STANDARD_CODE_START",
    "STANDARD_GLYPH_STRIDE",
    "STANDARD_LEAD_END",
    "STANDARD_LEAD_START",
    "STANDARD_TRAIL_START",
    "UPSTREAM_CHANGED_GLYPH_COUNT",
    "UPSTREAM_CHANGED_GLYPH_START",
    "UPSTREAM_CHANGED_REGION_END",
    "UPSTREAM_CHANGED_REGION_START",
    "analyze_font_patch",
    "analyze_glyph_code_mapping",
    "ascii_glyph_index",
    "decode_glyph",
    "decode_font_stream",
    "decode_vt1_font_segment",
    "encode_glyph",
    "extended_glyph_index",
    "extended_glyph_mapping",
    "glyph_index_for_code",
    "glyph_offset",
    "grayscale_png",
    "inventory_codebook",
    "is_cjk_unified_ideograph",
    "render_glyph_grid",
    "read_extended_glyph_table",
    "raw_standard_allocation_candidates",
    "replace_glyph",
    "safe_standard_allocation_candidates",
    "sha256_bytes",
    "standard_glyph_index",
    "standard_code_for_glyph_index",
]
