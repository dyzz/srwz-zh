"""Read-only parser for decoded SRWZ stage text structures."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional, Sequence

from .text import TextTable, decode_text


STAGE_BASE_ADDRESS = 0x7566F0
STAGE_BLOCK_REFERENCE_OFFSET = 0x90
STAGE_FUNCTION_TABLE_START = 0x2FF0B0
STAGE_FUNCTION_TABLE_END = 0x2FF3E7


class StageParseError(ValueError):
    """A decoded stage contains an invalid pointer or truncated structure."""

    def __init__(self, message: str, *, offset: int):
        self.offset = offset
        super().__init__(f"{message} at decoded offset 0x{offset:X}")


@dataclass(frozen=True)
class StageTextEntry:
    entry_id: str
    kind: str
    section: str
    ordinal: int
    text: str
    pointer_offset: Optional[int] = None
    text_offset: Optional[int] = None
    speaker_id: Optional[int] = None

    def to_mapping(self) -> dict:
        return {
            "id": self.entry_id,
            "kind": self.kind,
            "section": self.section,
            "ordinal": self.ordinal,
            "text": self.text,
            "pointer_offset": self.pointer_offset,
            "text_offset": self.text_offset,
            "speaker_id": self.speaker_id,
        }


@dataclass(frozen=True)
class StageSystemDialogueEntry:
    """One direct-pointer dialogue record from STAGE chunk zero."""

    entry_id: str
    ordinal: int
    pointer_offset: int
    text_offset: int
    speaker: str
    text: str

    def to_mapping(self) -> dict:
        return {
            "id": self.entry_id,
            "ordinal": self.ordinal,
            "pointer_offset": self.pointer_offset,
            "text_offset": self.text_offset,
            "speaker": self.speaker,
            "text": self.text,
        }


@dataclass(frozen=True)
class StageParseResult:
    stage_index: int
    decoded_size: int
    block_references: tuple
    entries: tuple
    section_count: int
    unknown_code_count: int

    @property
    def speaker_count(self) -> int:
        return sum(entry.kind == "speaker" for entry in self.entries)

    @property
    def condition_count(self) -> int:
        return sum(entry.kind == "condition" for entry in self.entries)

    @property
    def dialogue_count(self) -> int:
        return sum(entry.kind == "dialogue" for entry in self.entries)

    def to_mapping(self) -> dict:
        return {
            "stage_index": self.stage_index,
            "decoded_size": self.decoded_size,
            "block_references": list(self.block_references),
            "section_count": self.section_count,
            "speaker_count": self.speaker_count,
            "condition_count": self.condition_count,
            "dialogue_count": self.dialogue_count,
            "unknown_code_count": self.unknown_code_count,
            "entries": [entry.to_mapping() for entry in self.entries],
        }


def _require_span(data: bytes, offset: int, size: int, context: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise StageParseError(f"truncated {context}", offset=max(offset, 0))


def _u32(data: bytes, offset: int, context: str) -> int:
    _require_span(data, offset, 4, context)
    return struct.unpack_from("<I", data, offset)[0]


def _i16(data: bytes, offset: int, context: str) -> int:
    _require_span(data, offset, 2, context)
    return struct.unpack_from("<h", data, offset)[0]


def _u16(data: bytes, offset: int, context: str) -> int:
    _require_span(data, offset, 2, context)
    return struct.unpack_from("<H", data, offset)[0]


def read_stage_function_addresses(
    executable: bytes,
    *,
    start: int = STAGE_FUNCTION_TABLE_START,
    end: int = STAGE_FUNCTION_TABLE_END,
) -> tuple:
    """Read the fixed SLPS stage-function table using its observed end rule."""

    if not 0 <= start < end <= len(executable):
        raise ValueError("stage function table is outside the executable")
    offsets = []
    for offset in range(start, end, 4):
        offsets.append(_u32(executable, offset, "stage function table"))
    return tuple(offsets)


def _read_block_references(
    data: bytes,
    *,
    base_address: int,
) -> tuple:
    references = []
    position = STAGE_BLOCK_REFERENCE_OFFSET
    for _ in range(3):
        _require_span(data, position, 16, "stage block reference")
        high = _i16(data, position, "stage block reference high value")
        low = _i16(data, position + 8, "stage block reference low value")
        target = (high << 16) + low - base_address
        if 0 < target <= len(data) - 8:
            references.append(target)
        position += 16
    return tuple(references)


def _decode_speaker_and_message(
    data: bytes,
    offset: int,
    table: TextTable,
) -> tuple:
    speaker = decode_text(data, offset, table, stop_at_newline=True)
    message = decode_text(data, speaker.end, table)
    speaker_text = speaker.text
    message_text = message.text
    if message_text == "":
        message_text = speaker_text
        speaker_text = ""
    return (
        speaker_text,
        message_text,
        speaker.unknown_code_count + message.unknown_code_count,
    )


def _condition_entries(
    data: bytes,
    function_address: int,
    table: TextTable,
    *,
    stage_index: int,
    base_address: int,
) -> tuple:
    labels = (
        ("_Victory Conditions", bytes.fromhex("b05222ac")),
        ("_Defeat Condtions", bytes.fromhex("b85222ac")),
        ("_SR Conditions", bytes.fromhex("c05222ac")),
    )
    function_offset = function_address - base_address
    if not 0 <= function_offset < len(data):
        return (), 0
    search_end = min(function_offset + 200, len(data))
    window = data[function_offset:search_end]
    tables = {}
    for label, pattern in labels:
        current = 0
        while True:
            found = window.find(pattern, current)
            if found < 0:
                break
            pattern_offset = function_offset + found
            pair_offset = pattern_offset - 12
            if pair_offset >= 0:
                high = _u16(data, pair_offset, "condition table high value")
                low = _i16(data, pair_offset + 4, "condition table low value")
                tables[label] = (high << 16) + low
            current = found + len(pattern)

    entries = []
    unknown_code_count = 0
    for condition_index, (label, _) in enumerate(labels):
        table_address = tables.get(label)
        if table_address is None:
            continue
        table_offset = table_address - base_address
        _require_span(data, table_offset, 8, "condition pointer table")
        ordinal = 0
        for index in range(2):
            pointer_offset = table_offset + index * 4
            text_address = _u32(data, pointer_offset, "condition text pointer")
            if text_address == 0:
                continue
            text_offset = text_address - base_address
            if not 0 <= text_offset < len(data):
                raise StageParseError(
                    "condition text pointer is outside decoded stage",
                    offset=pointer_offset,
                )
            decoded = decode_text(data, text_offset, table)
            entries.append(
                StageTextEntry(
                    entry_id=(
                        f"story/{stage_index:03d}/condition/"
                        f"{condition_index:02d}/{ordinal:02d}"
                    ),
                    kind="condition",
                    section=label,
                    ordinal=ordinal,
                    text=decoded.text,
                    pointer_offset=pointer_offset,
                    text_offset=text_offset,
                )
            )
            unknown_code_count += decoded.unknown_code_count
            ordinal += 1
    return tuple(entries), unknown_code_count


def parse_stage(
    data: bytes,
    table: TextTable,
    *,
    stage_index: int,
    function_address: int = 0,
    base_address: int = STAGE_BASE_ADDRESS,
    max_sections: int = 100_000,
    max_records_per_section: int = 100_000,
) -> StageParseResult:
    """Parse one decoded stage into stable text entries."""

    block_references = _read_block_references(
        data,
        base_address=base_address,
    )
    dialogue_entries = []
    speaker_order = {}
    section_count = 0
    unknown_code_count = 0

    # Ordinary stages reserve the first observed block reference for a
    # non-dialogue structure.  The route-selection and bazaar-only chunks use
    # a compact layout with exactly one reference, and that sole reference is
    # the dialogue block itself.  Selecting by structure cardinality keeps the
    # ordinary layout stable while exposing those otherwise skipped chunks.
    dialogue_block_start = 0 if len(block_references) == 1 else 1
    for block_index, block_reference in enumerate(
        block_references[dialogue_block_start:],
        start=dialogue_block_start,
    ):
        pointer_table_address = _u32(
            data,
            block_reference,
            "dialogue block pointer",
        )
        sections_count = _u32(
            data,
            block_reference + 4,
            "dialogue block section count",
        )
        if sections_count > max_sections:
            raise StageParseError(
                f"section count {sections_count} exceeds limit {max_sections}",
                offset=block_reference + 4,
            )
        pointer_table_offset = pointer_table_address - base_address
        if not 0 < pointer_table_offset < len(data):
            continue

        if sections_count == 0:
            speaker, message, unknown = _decode_speaker_and_message(
                data,
                pointer_table_offset,
                table,
            )
            speaker_order.setdefault(speaker, len(speaker_order) + 1)
            dialogue_entries.append(
                StageTextEntry(
                    entry_id=(
                        f"story/{stage_index:03d}/dialogue/"
                        f"{block_index:02d}.01/0000"
                    ),
                    kind="dialogue",
                    section=f"Section {block_index}.1",
                    ordinal=0,
                    text=message,
                    text_offset=pointer_table_offset,
                    speaker_id=speaker_order[speaker],
                )
            )
            section_count += 1
            unknown_code_count += unknown
            continue

        _require_span(
            data,
            pointer_table_offset,
            sections_count * 8,
            "dialogue section pointer table",
        )
        for section_index in range(sections_count):
            # Each pointer occupies the first word of an eight-byte table row.
            section_pointer_offset = pointer_table_offset + section_index * 8
            section_address = _u32(
                data,
                section_pointer_offset,
                "dialogue section pointer",
            )
            section_offset = section_address - base_address
            if not 0 < section_offset < len(data):
                continue

            record_offset = section_offset + 0x20
            section_name = f"Section {block_index}.{section_index + 1}"
            ordinal = 0
            for _ in range(max_records_per_section):
                _require_span(data, record_offset, 4, "dialogue record")
                structure_value = _u32(
                    data,
                    record_offset,
                    "dialogue record type",
                )
                if structure_value >= 0x60:
                    break
                _require_span(data, record_offset, 32, "dialogue record")
                text_pointer_offset = record_offset + 16
                text_address = _u32(
                    data,
                    text_pointer_offset,
                    "dialogue text pointer",
                )
                if text_address > base_address:
                    text_offset = text_address - base_address
                    if not 0 <= text_offset < len(data):
                        raise StageParseError(
                            "dialogue text pointer is outside decoded stage",
                            offset=text_pointer_offset,
                        )
                    speaker, message, unknown = _decode_speaker_and_message(
                        data,
                        text_offset,
                        table,
                    )
                    speaker_order.setdefault(speaker, len(speaker_order) + 1)
                    dialogue_entries.append(
                        StageTextEntry(
                            entry_id=(
                                f"story/{stage_index:03d}/dialogue/"
                                f"{block_index:02d}.{section_index + 1:02d}/"
                                f"{ordinal:04d}"
                            ),
                            kind="dialogue",
                            section=section_name,
                            ordinal=ordinal,
                            text=message,
                            pointer_offset=text_pointer_offset,
                            text_offset=text_offset,
                            speaker_id=speaker_order[speaker],
                        )
                    )
                    unknown_code_count += unknown
                    ordinal += 1
                record_offset += 32
            else:
                raise StageParseError(
                    f"dialogue record count exceeds limit "
                    f"{max_records_per_section}",
                    offset=record_offset,
                )
            section_count += 1

    speaker_entries = tuple(
        StageTextEntry(
            entry_id=(
                f"story/{stage_index:03d}/speaker/{speaker_id:03d}"
            ),
            kind="speaker",
            section="Speaker",
            ordinal=speaker_id - 1,
            text=speaker,
            speaker_id=speaker_id,
        )
        for speaker, speaker_id in speaker_order.items()
    )
    conditions, condition_unknown = _condition_entries(
        data,
        function_address,
        table,
        stage_index=stage_index,
        base_address=base_address,
    )
    unknown_code_count += condition_unknown

    return StageParseResult(
        stage_index=stage_index,
        decoded_size=len(data),
        block_references=block_references,
        entries=speaker_entries + conditions + tuple(dialogue_entries),
        section_count=section_count,
        unknown_code_count=unknown_code_count,
    )


def parse_stage_system_dialogues(
    data: bytes,
    table: TextTable,
    *,
    base_address: int = STAGE_BASE_ADDRESS,
) -> tuple[StageSystemDialogueEntry, ...]:
    """Parse the structurally distinct quit-dialogue table in chunk zero.

    These records are not reachable from the ordinary stage block references.
    Each observed row is 0x20-aligned, begins with a direct text pointer, has
    three zero words, the fixed command value 0x3A, and two trailing zero
    words.  Rows belonging to one scene are normally 0x80 bytes apart, with
    larger gaps between scenes.  Matching the complete row signature keeps
    the scan fail-closed instead of treating arbitrary stage pointers as text.
    """

    entries = []
    for pointer_offset in range(0, len(data) - 31, 0x20):
        text_address = _u32(data, pointer_offset, "system dialogue pointer")
        text_offset = text_address - base_address
        if not 0 < text_offset < len(data):
            continue
        if (
            data[pointer_offset + 4 : pointer_offset + 16] != bytes(12)
            or _u32(data, pointer_offset + 16, "system dialogue command")
            != 0x3A
            or data[pointer_offset + 24 : pointer_offset + 32] != bytes(8)
        ):
            continue
        speaker = decode_text(
            data,
            text_offset,
            table,
            stop_at_newline=True,
        )
        if speaker.terminator != "newline" or not speaker.text:
            continue
        message = decode_text(data, speaker.end, table)
        if message.terminator != "nul" or not message.text:
            continue
        ordinal = len(entries)
        entries.append(
            StageSystemDialogueEntry(
                entry_id=(
                    "story/000/system-dialogue/"
                    f"{pointer_offset:06X}"
                ),
                ordinal=ordinal,
                pointer_offset=pointer_offset,
                text_offset=text_offset,
                speaker=speaker.text,
                text=message.text,
            )
        )
    return tuple(entries)


def stage_reference_signature(entries: Sequence[StageTextEntry]) -> tuple:
    """Normalize parser entries to the fields present in upstream XML."""

    return tuple(
        (
            entry.kind,
            entry.section,
            entry.text,
            entry.pointer_offset,
            entry.speaker_id,
        )
        for entry in entries
    )


__all__ = [
    "STAGE_BASE_ADDRESS",
    "STAGE_FUNCTION_TABLE_END",
    "STAGE_FUNCTION_TABLE_START",
    "StageParseError",
    "StageParseResult",
    "StageSystemDialogueEntry",
    "StageTextEntry",
    "parse_stage",
    "parse_stage_system_dialogues",
    "read_stage_function_addresses",
    "stage_reference_signature",
]
