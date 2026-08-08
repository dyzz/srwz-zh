"""Parse and rewrite the fixed Scenario Chart summaries in HSFC chunk 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .font import sha256_bytes
from .text import (
    TextTable,
    decode_text,
    encode_text,
    normalize_original_fullwidth_ascii,
)
from .text import project_runtime_text_table


HSFC_OVERVIEW_TABLE_START = 0xB6
HSFC_OVERVIEW_RECORD_COUNT = 180
HSFC_OVERVIEW_RECORD_SIZE = 0x96
HSFC_OVERVIEW_CELL_COUNT = 3
HSFC_OVERVIEW_CELL_SIZE = 0x32


class HsfcOverviewError(ValueError):
    """The HSFC Scenario Chart table or its reviewed corpus drifted."""


@dataclass(frozen=True)
class HsfcOverviewRecord:
    ordinal: int
    record_offset: int
    source_lines: tuple[str, str, str]

    @property
    def source_text(self) -> str:
        return "\n".join(self.source_lines)

    @property
    def source_text_sha256(self) -> str:
        return sha256_bytes(self.source_text.encode("utf-8"))


@dataclass(frozen=True)
class HsfcOverviewGroup:
    entry_id: str
    first_ordinal: int
    ordinals: tuple[int, ...]
    source_lines: tuple[str, str, str]

    @property
    def source_text(self) -> str:
        return "\n".join(self.source_lines)

    @property
    def source_text_sha256(self) -> str:
        return sha256_bytes(self.source_text.encode("utf-8"))

    def to_mapping(self) -> dict:
        return {
            "id": self.entry_id,
            "first_ordinal": self.first_ordinal,
            "ordinals": list(self.ordinals),
            "source_text": self.source_text,
            "source_text_sha256": self.source_text_sha256,
            "translation": "",
            "editorial_status": "todo",
        }


def parse_hsfc_overviews(
    decoded: bytes,
    table: TextTable,
) -> tuple[HsfcOverviewRecord, ...]:
    """Return the 180 three-cell fixed records in source order."""

    table_end = (
        HSFC_OVERVIEW_TABLE_START
        + HSFC_OVERVIEW_RECORD_COUNT * HSFC_OVERVIEW_RECORD_SIZE
    )
    if table_end > len(decoded):
        raise HsfcOverviewError("HSFC overview table is truncated")
    records = []
    for ordinal in range(HSFC_OVERVIEW_RECORD_COUNT):
        record_offset = (
            HSFC_OVERVIEW_TABLE_START
            + ordinal * HSFC_OVERVIEW_RECORD_SIZE
        )
        lines = []
        for cell_index in range(HSFC_OVERVIEW_CELL_COUNT):
            cell_offset = record_offset + cell_index * HSFC_OVERVIEW_CELL_SIZE
            cell = decoded[cell_offset : cell_offset + HSFC_OVERVIEW_CELL_SIZE]
            parsed = decode_text(cell, 0, table)
            if (
                parsed.unknown_code_count
                or not parsed.text
                or parsed.consumed > HSFC_OVERVIEW_CELL_SIZE
                or any(cell[parsed.consumed :])
                or "\n" in parsed.text
                or "\r" in parsed.text
            ):
                raise HsfcOverviewError(
                    "invalid HSFC overview cell: "
                    f"record={ordinal} cell={cell_index}"
                )
            lines.append(parsed.text)
        records.append(
            HsfcOverviewRecord(
                ordinal=ordinal,
                record_offset=record_offset,
                source_lines=tuple(lines),
            )
        )
    return tuple(records)


def group_hsfc_overviews(
    records: tuple[HsfcOverviewRecord, ...],
) -> tuple[HsfcOverviewGroup, ...]:
    """Group byte-identical source summaries while preserving first use order."""

    grouped: dict[str, list[HsfcOverviewRecord]] = {}
    for record in records:
        grouped.setdefault(record.source_text_sha256, []).append(record)
    groups = []
    for matches in grouped.values():
        first = matches[0]
        if any(item.source_lines != first.source_lines for item in matches):
            raise HsfcOverviewError("HSFC source hash collision")
        groups.append(
            HsfcOverviewGroup(
                entry_id=f"hsfc-overview:{first.ordinal:03d}",
                first_ordinal=first.ordinal,
                ordinals=tuple(item.ordinal for item in matches),
                source_lines=first.source_lines,
            )
        )
    return tuple(groups)


def replace_hsfc_overviews_in_place(
    decoded: bytes,
    table: TextTable,
    corpus_entries: list[dict],
    *,
    encoding_overrides: Mapping[str, int],
) -> tuple[bytes, dict]:
    """Rewrite every occurrence inside its original three 50-byte cells."""

    records = parse_hsfc_overviews(decoded, table)
    groups = group_hsfc_overviews(records)
    if not corpus_entries:
        raise HsfcOverviewError("HSFC overview corpus is empty")
    rows_by_id = {}
    for row in corpus_entries:
        entry_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(entry_id, str) or entry_id in rows_by_id:
            raise HsfcOverviewError("HSFC overview corpus row is malformed")
        rows_by_id[entry_id] = row
    expected_ids = {group.entry_id for group in groups}
    if set(rows_by_id) != expected_ids:
        raise HsfcOverviewError("HSFC overview corpus selection drift")

    output_table = project_runtime_text_table(table, encoding_overrides)
    output = bytearray(decoded)
    changed_indexes: set[int] = set()
    minimum_cell_headroom = HSFC_OVERVIEW_CELL_SIZE
    translated_occurrences = 0
    for group in groups:
        row = rows_by_id[group.entry_id]
        translation = row.get("translation")
        if (
            (
                "first_ordinal" in row
                and row.get("first_ordinal") != group.first_ordinal
            )
            or (
                "ordinals" in row
                and row.get("ordinals") != list(group.ordinals)
            )
            or (
                "source_text_sha256" in row
                and row.get("source_text_sha256")
                != group.source_text_sha256
            )
            or row.get("editorial_status") != "reviewed"
            or not isinstance(translation, str)
            or translation.count("\n") != 2
            or "\r" in translation
        ):
            raise HsfcOverviewError(
                f"HSFC overview corpus drift: {group.entry_id}"
            )
        translated_lines = tuple(
            normalize_original_fullwidth_ascii(line)
            for line in translation.split("\n")
        )
        if any(not line for line in translated_lines):
            raise HsfcOverviewError(
                f"HSFC overview has an empty translated cell: {group.entry_id}"
            )
        encoded_lines = []
        for cell_index, line in enumerate(translated_lines):
            encoded = encode_text(
                line,
                table,
                overrides=encoding_overrides,
                terminate=True,
            )
            if len(encoded) > HSFC_OVERVIEW_CELL_SIZE:
                raise HsfcOverviewError(
                    "HSFC overview cell overflow: "
                    f"{group.entry_id} cell={cell_index} "
                    f"{len(encoded)}>{HSFC_OVERVIEW_CELL_SIZE}"
                )
            encoded_lines.append(encoded)
            minimum_cell_headroom = min(
                minimum_cell_headroom,
                HSFC_OVERVIEW_CELL_SIZE - len(encoded),
            )
        for ordinal in group.ordinals:
            record = records[ordinal]
            for cell_index, (line, encoded) in enumerate(
                zip(translated_lines, encoded_lines)
            ):
                start = (
                    record.record_offset
                    + cell_index * HSFC_OVERVIEW_CELL_SIZE
                )
                end = start + HSFC_OVERVIEW_CELL_SIZE
                replacement = encoded + bytes(
                    HSFC_OVERVIEW_CELL_SIZE - len(encoded)
                )
                before = bytes(output[start:end])
                output[start:end] = replacement
                changed_indexes.update(
                    index
                    for index, (old, new) in enumerate(
                        zip(before, replacement), start=start
                    )
                    if old != new
                )
                reread = decode_text(bytes(output[start:end]), 0, output_table)
                if reread.text != line:
                    raise HsfcOverviewError(
                        "HSFC overview readback mismatch: "
                        f"record={ordinal} cell={cell_index}"
                    )
            translated_occurrences += 1

    table_start = HSFC_OVERVIEW_TABLE_START
    table_end = table_start + HSFC_OVERVIEW_RECORD_COUNT * HSFC_OVERVIEW_RECORD_SIZE
    if any(
        before != after and not table_start <= index < table_end
        for index, (before, after) in enumerate(zip(decoded, output))
    ):
        raise HsfcOverviewError("HSFC overview write escaped fixed table")
    return bytes(output), {
        "inventory_record_count": len(records),
        "unique_source_text_count": len(groups),
        "translated_unique_entry_count": len(groups),
        "translated_occurrence_count": translated_occurrences,
        "minimum_cell_headroom": minimum_cell_headroom,
        "changed_byte_count": len(changed_indexes),
        "table_start": f"0x{table_start:X}",
        "table_end_exclusive": f"0x{table_end:X}",
        "record_size": HSFC_OVERVIEW_RECORD_SIZE,
        "cell_size": HSFC_OVERVIEW_CELL_SIZE,
        "fixed_cells_preserved": True,
        "non_target_bytes_preserved": True,
        "translated_readback_exact": True,
    }


__all__ = [
    "HSFC_OVERVIEW_CELL_COUNT",
    "HSFC_OVERVIEW_CELL_SIZE",
    "HSFC_OVERVIEW_RECORD_COUNT",
    "HSFC_OVERVIEW_RECORD_SIZE",
    "HSFC_OVERVIEW_TABLE_START",
    "HsfcOverviewError",
    "HsfcOverviewGroup",
    "HsfcOverviewRecord",
    "group_hsfc_overviews",
    "parse_hsfc_overviews",
    "replace_hsfc_overviews_in_place",
]
