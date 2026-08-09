"""Parse and rewrite the save/load story-overview table in STAGE chunk 0."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Mapping

from .font import sha256_bytes
from .stage import STAGE_BASE_ADDRESS
from .text import (
    TextTable,
    decode_text,
    encode_text,
    normalize_original_fullwidth_ascii,
)
from .text import project_runtime_text_table


OVERVIEW_POINTER_TABLE_START = 0x10DD4
OVERVIEW_POINTER_TABLE_END_INCLUSIVE = 0x10F88
OVERVIEW_ENTRY_COUNT = 110


class StageOverviewError(ValueError):
    """The STAGE 0 overview table or its replacement corpus drifted."""


@dataclass(frozen=True)
class StageOverviewEntry:
    entry_id: str
    ordinal: int
    pointer_offset: int
    text_offset: int
    encoded_size: int
    source_text: str

    def to_mapping(self) -> dict:
        return {
            "id": self.entry_id,
            "ordinal": self.ordinal,
            "pointer_offset": f"0x{self.pointer_offset:X}",
            "text_offset": f"0x{self.text_offset:X}",
            "encoded_size_with_terminator": self.encoded_size,
            "source_text": self.source_text,
            "source_text_sha256": sha256_bytes(
                self.source_text.encode("utf-8")
            ),
        }


def parse_stage_overviews(
    decoded: bytes,
    table: TextTable,
    *,
    base_address: int = STAGE_BASE_ADDRESS,
) -> tuple[StageOverviewEntry, ...]:
    """Return all pointer-indexed story overviews in source table order."""

    if OVERVIEW_POINTER_TABLE_END_INCLUSIVE + 4 > len(decoded):
        raise StageOverviewError("STAGE 0 overview pointer table is truncated")
    entries = []
    seen_offsets = set()
    for ordinal, pointer_offset in enumerate(
        range(
            OVERVIEW_POINTER_TABLE_START,
            OVERVIEW_POINTER_TABLE_END_INCLUSIVE + 1,
            4,
        )
    ):
        pointer = struct.unpack_from("<I", decoded, pointer_offset)[0]
        text_offset = pointer - base_address
        if (
            not 0 <= text_offset < len(decoded)
            or text_offset in seen_offsets
        ):
            raise StageOverviewError(
                "STAGE 0 overview pointer is invalid or duplicated: "
                f"0x{pointer_offset:X}->0x{text_offset:X}"
            )
        source = decode_text(decoded, text_offset, table)
        if source.unknown_code_count or not source.text:
            raise StageOverviewError(
                f"STAGE 0 overview text is invalid at 0x{text_offset:X}"
            )
        seen_offsets.add(text_offset)
        entries.append(
            StageOverviewEntry(
                entry_id=f"overview:{ordinal:03d}",
                ordinal=ordinal,
                pointer_offset=pointer_offset,
                text_offset=text_offset,
                encoded_size=source.consumed,
                source_text=source.text,
            )
        )
    if len(entries) != OVERVIEW_ENTRY_COUNT:
        raise StageOverviewError(
            f"STAGE 0 overview count drift: {len(entries)}"
        )
    return tuple(entries)


def replace_stage_overviews_in_place(
    decoded: bytes,
    table: TextTable,
    corpus_entries: list[dict],
    *,
    encoding_overrides: Mapping[str, int],
) -> tuple[bytes, dict]:
    """Rewrite reviewed overview strings inside their original allocations."""

    parsed = parse_stage_overviews(decoded, table)
    if not corpus_entries:
        raise StageOverviewError("stage-overview corpus is empty")
    rows_by_id = {}
    for row in corpus_entries:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise StageOverviewError("stage-overview corpus row is malformed")
        if row["id"] in rows_by_id:
            raise StageOverviewError(
                f"duplicate stage-overview corpus id: {row['id']}"
            )
        rows_by_id[row["id"]] = row
    parsed_ids = {entry.entry_id for entry in parsed}
    unknown_ids = sorted(set(rows_by_id) - parsed_ids)
    if unknown_ids:
        raise StageOverviewError(
            f"stage-overview corpus has unknown ids: {unknown_ids}"
        )
    output_table = project_runtime_text_table(table, encoding_overrides)
    output = bytearray(decoded)
    minimum_headroom = None
    newline_count_exact = True
    seen_translations: dict[str, str] = {}
    translated_ids = []
    for source in parsed:
        row = rows_by_id.get(source.entry_id)
        if row is None:
            continue
        translation = row.get("translation")
        if (
            row.get("id") != source.entry_id
            or row.get("ordinal") != source.ordinal
            or row.get("pointer_offset") != f"0x{source.pointer_offset:X}"
            or row.get("text_offset") != f"0x{source.text_offset:X}"
            or row.get("encoded_size_with_terminator")
            != source.encoded_size
            or row.get("source_text_sha256")
            != sha256_bytes(source.source_text.encode("utf-8"))
            or row.get("editorial_status") != "reviewed"
            or not isinstance(translation, str)
            or not translation
            or "\r" in translation
            or translation.count("\n") != source.source_text.count("\n")
        ):
            raise StageOverviewError(
                f"stage-overview corpus drift: {source.entry_id}"
            )
        source_hash = row["source_text_sha256"]
        prior = seen_translations.get(source_hash)
        if prior is not None and prior != translation:
            raise StageOverviewError(
                f"duplicate overview source has inconsistent translation: "
                f"{source.entry_id}"
            )
        seen_translations[source_hash] = translation
        normalized = normalize_original_fullwidth_ascii(translation).replace(
            " ", "\u3000"
        )
        encoded = encode_text(
            normalized,
            table,
            overrides=encoding_overrides,
            terminate=True,
        )
        if len(encoded) > source.encoded_size:
            raise StageOverviewError(
                f"stage overview overflow at {source.entry_id}: "
                f"{len(encoded)}>{source.encoded_size}"
            )
        start = source.text_offset
        end = start + source.encoded_size
        original = decode_text(decoded, start, table)
        if (
            original.text != source.source_text
            or original.consumed != source.encoded_size
        ):
            raise StageOverviewError(
                f"stage overview source preimage drift: {source.entry_id}"
            )
        output[start:end] = encoded + bytes(source.encoded_size - len(encoded))
        reread = decode_text(bytes(output), start, output_table)
        if reread.text != normalized:
            raise StageOverviewError(
                f"stage overview readback mismatch: {source.entry_id}"
            )
        headroom = source.encoded_size - len(encoded)
        minimum_headroom = (
            headroom
            if minimum_headroom is None
            else min(minimum_headroom, headroom)
        )
        newline_count_exact &= (
            reread.text.count("\n") == source.source_text.count("\n")
        )
        translated_ids.append(source.entry_id)
    if bytes(output)[
        OVERVIEW_POINTER_TABLE_START : OVERVIEW_POINTER_TABLE_END_INCLUSIVE + 4
    ] != decoded[
        OVERVIEW_POINTER_TABLE_START : OVERVIEW_POINTER_TABLE_END_INCLUSIVE + 4
    ]:
        raise StageOverviewError("stage-overview pointer table changed")
    translated_ranges = [
        range(entry.text_offset, entry.text_offset + entry.encoded_size)
        for entry in parsed
        if entry.entry_id in rows_by_id
    ]
    translated_indexes = {
        index for current_range in translated_ranges for index in current_range
    }
    if any(
        before != after and index not in translated_indexes
        for index, (before, after) in enumerate(zip(decoded, output))
    ):
        raise StageOverviewError("stage-overview write escaped target allocations")
    return bytes(output), {
        "inventory_entry_count": len(parsed),
        "translated_entry_count": len(translated_ids),
        "translated_entry_ids": translated_ids,
        "unique_source_text_count": len(seen_translations),
        "minimum_output_headroom": minimum_headroom,
        "pointer_table_start": f"0x{OVERVIEW_POINTER_TABLE_START:X}",
        "pointer_table_end_inclusive": (
            f"0x{OVERVIEW_POINTER_TABLE_END_INCLUSIVE:X}"
        ),
        "pointer_table_preserved_byte_exact": True,
        "fixed_allocations_preserved": True,
        "untranslated_allocations_preserved": True,
        "newline_counts_preserved": newline_count_exact,
        "translated_readback_exact": True,
    }


__all__ = [
    "OVERVIEW_ENTRY_COUNT",
    "OVERVIEW_POINTER_TABLE_END_INCLUSIVE",
    "OVERVIEW_POINTER_TABLE_START",
    "StageOverviewEntry",
    "StageOverviewError",
    "parse_stage_overviews",
    "replace_stage_overviews_in_place",
]
