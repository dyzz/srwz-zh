"""Read-only parser for decoded MTV_PROS summary records."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .text import TextTable, decode_text


class SummaryParseError(ValueError):
    """A decoded MTV_PROS chunk contains an invalid record."""

    def __init__(self, message: str, *, offset: int):
        self.offset = offset
        super().__init__(f"{message} at decoded offset 0x{offset:X}")


@dataclass(frozen=True)
class SummaryTextEntry:
    entry_id: str
    ordinal: int
    text: str
    text_offset: int
    allocated_length: int
    terminator: str
    unknown_code_count: int = 0

    def to_mapping(self) -> dict:
        return {
            "id": self.entry_id,
            "ordinal": self.ordinal,
            "text": self.text,
            "text_offset": self.text_offset,
            "allocated_length": self.allocated_length,
            "terminator": self.terminator,
            "unknown_code_count": self.unknown_code_count,
        }


@dataclass(frozen=True)
class SummaryParseResult:
    chunk_index: int
    decoded_size: int
    section_count: int
    entries: tuple

    @property
    def unknown_code_count(self) -> int:
        return sum(entry.unknown_code_count for entry in self.entries)

    def to_mapping(self) -> dict:
        return {
            "chunk_index": self.chunk_index,
            "decoded_size": self.decoded_size,
            "section_count": self.section_count,
            "entry_count": len(self.entries),
            "unknown_code_count": self.unknown_code_count,
            "entries": [entry.to_mapping() for entry in self.entries],
        }


def _require_span(data: bytes, offset: int, size: int, context: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise SummaryParseError(f"truncated {context}", offset=max(offset, 0))


def _u32(data: bytes, offset: int, context: str) -> int:
    _require_span(data, offset, 4, context)
    return struct.unpack_from("<I", data, offset)[0]


def parse_summary(
    data: bytes,
    table: TextTable,
    *,
    chunk_index: int,
    max_sections: int = 100_000,
) -> SummaryParseResult:
    """Parse text records from one decoded MTV_PROS archive chunk."""

    _require_span(data, 0x2C, 12, "summary section counts")
    section_count = sum(
        _u32(data, offset, "summary section count")
        for offset in (0x2C, 0x30, 0x34)
    )
    if section_count > max_sections:
        raise SummaryParseError(
            f"section count {section_count} exceeds limit {max_sections}",
            offset=0x2C,
        )

    entries = []
    position = 0x3C
    for _ in range(section_count):
        _require_span(data, position, 8, "summary section header")
        raw_type = data[position:position + 4]
        try:
            section_type = raw_type.decode("ascii")
        except UnicodeDecodeError as error:
            raise SummaryParseError(
                "summary section type is not ASCII",
                offset=position,
            ) from error
        payload_size = _u32(
            data,
            position + 4,
            "summary section payload size",
        )
        next_position = position + payload_size + 8
        if next_position <= position or next_position > len(data):
            raise SummaryParseError(
                "summary section extends outside decoded chunk",
                offset=position + 4,
            )

        if section_type == "text":
            length_offset = position + 8 + 0x22
            allocated_length = _u32(
                data,
                length_offset,
                "summary text length",
            )
            text_offset = length_offset + 4
            _require_span(
                data,
                text_offset,
                allocated_length,
                "summary text allocation",
            )
            decoded = decode_text(
                data,
                text_offset,
                table,
                end=text_offset + allocated_length,
                allow_end=True,
            )
            entries.append(
                SummaryTextEntry(
                    entry_id=(
                        f"summary/{chunk_index:02d}/{len(entries):03d}"
                    ),
                    ordinal=len(entries),
                    text=decoded.text,
                    text_offset=text_offset,
                    allocated_length=allocated_length,
                    terminator=decoded.terminator,
                    unknown_code_count=decoded.unknown_code_count,
                )
            )

        position = next_position

    return SummaryParseResult(
        chunk_index=chunk_index,
        decoded_size=len(data),
        section_count=section_count,
        entries=tuple(entries),
    )


__all__ = [
    "SummaryParseError",
    "SummaryParseResult",
    "SummaryTextEntry",
    "parse_summary",
]
