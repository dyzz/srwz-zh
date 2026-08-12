"""Discover and lock default formation-name records in STAGE chunks."""

from __future__ import annotations

import hashlib
import json
import struct
import unicodedata
from dataclasses import asdict, dataclass

from .codec import DecodeResult, decode_production as decode
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .text import TextTable, decode_text, encode_text


STAGE_OFFSET_SPEC = ExecutableOffsetSpec(
    name="HEDBDY/HB.BIN STAGE offsets",
    member="HEDBDY/HB.BIN",
    table_start=30320,
    table_end=31144,
)


@dataclass(frozen=True)
class FormationCell:
    offset: int
    source_text: str
    source_consumed: int
    trailer_hex: str
    prefix_hex: str = ""


@dataclass(frozen=True)
class FormationGroup:
    stage_index: int
    layout: str
    slot_size: int
    stride: int
    cells: tuple[FormationCell, ...]


_LOCKED_LAYOUT_SPECS = {
    "formation18+33+1": {
        "slot_size": 33,
        "stride": 52,
        "prefix_size": 18,
        "trailer_size": 1,
    },
    "record6+23": {
        "slot_size": 23,
        "stride": 29,
        "prefix_size": 6,
        "trailer_size": 0,
    },
    "slot32": {
        "slot_size": 32,
        "stride": 32,
        "prefix_size": 0,
        "trailer_size": 0,
    },
}


def _cell_at(
    data: bytes,
    offset: int,
    slot_size: int,
    table: TextTable,
) -> FormationCell | None:
    end = offset + slot_size
    if offset < 0 or end > len(data) or data[offset] == 0:
        return None
    try:
        decoded = decode_text(data, offset, table, end=end)
    except (IndexError, KeyError, UnicodeError, ValueError):
        return None
    if (
        decoded.terminator != "nul"
        or decoded.unknown_code_count
        or len(decoded.text) < 2
        or len(decoded.text) > 20
        or decoded.consumed > slot_size
        or any(data[offset + decoded.consumed : end])
        or "\n" in decoded.text
        or "<" in decoded.text
        or "{" in decoded.text
        or any(
            character in "「」『』！？。\n"
            or "\uFF61" <= character <= "\uFF9F"
            or unicodedata.category(character).startswith("C")
            for character in decoded.text
        )
        or decoded.text.count("(") != decoded.text.count(")")
        or decoded.text.count("（") != decoded.text.count("）")
    ):
        return None
    return FormationCell(
        offset=offset,
        source_text=decoded.text,
        source_consumed=decoded.consumed,
        trailer_hex="",
    )


def _scan_layout(
    data: bytes,
    table: TextTable,
    *,
    stage_index: int,
    layout: str,
    slot_size: int,
    stride: int,
) -> list[FormationGroup]:
    valid = {}
    for offset in range(len(data) - stride + 1):
        cell = _cell_at(data, offset, slot_size, table)
        if cell is None:
            continue
        trailer = data[offset + slot_size : offset + stride]
        if layout == "record23+6" and trailer[5] not in {0x00, 0x04, 0x0C}:
            continue
        valid[offset] = cell

    groups = []
    for offset in sorted(valid):
        previous = offset - stride
        if previous in valid and (
            layout != "record23+6" or data[previous + stride - 1] != 0
        ):
            continue
        cells = []
        current = offset
        while current in valid:
            cell = valid[current]
            trailer = data[current + slot_size : current + stride]
            cells.append(
                FormationCell(
                    offset=cell.offset,
                    source_text=cell.source_text,
                    source_consumed=cell.source_consumed,
                    trailer_hex=trailer.hex(),
                )
            )
            current += stride
            if layout == "record23+6" and trailer[5] == 0:
                break
        terminated = layout != "record23+6" or (
            bool(cells) and bytes.fromhex(cells[-1].trailer_hex)[5] == 0
        )
        minimum_count = 2 if layout == "record23+6" else 3
        if len(cells) >= minimum_count and terminated:
            groups.append(
                FormationGroup(
                    stage_index=stage_index,
                    layout=layout,
                    slot_size=slot_size,
                    stride=stride,
                    cells=tuple(cells),
                )
            )
    return groups


def discover_stage_default_formations(
    stage: bytes,
    hb: bytes,
    table: TextTable,
) -> tuple[FormationGroup, ...]:
    """Return every structurally valid default-formation group in STAGE."""

    offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(stage))
    groups = []
    for stage_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        decoded = decode(stage[start:end])
        if any(stage[start + decoded.consumed : end]):
            raise ValueError(f"STAGE {stage_index} has nonzero archive padding")
        groups.extend(
            _scan_layout(
                decoded.output,
                table,
                stage_index=stage_index,
                layout="record23+6",
                slot_size=23,
                stride=29,
            )
        )
        groups.extend(
            _scan_layout(
                decoded.output,
                table,
                stage_index=stage_index,
                layout="slot32",
                slot_size=32,
                stride=32,
            )
        )
    return tuple(groups)


_KNOWN_RECORD_FIRST_BYTES = frozenset({0x00, 0x10, 0x11, 0x12, 0x20, 0x22})
_FORMATION_MEMBER_ID_MAX = 0x03FF


def _known_record_prefix_is_valid(prefix: bytes) -> bool:
    """Return whether *prefix* matches a six-byte STAGE unit record header."""

    return (
        len(prefix) == 6
        and prefix[0] in _KNOWN_RECORD_FIRST_BYTES
        and prefix[4] in {0x00, 0x01}
        and prefix[5] <= 0x0D
    )


def _scan_structural_record_groups(
    data: bytes,
    table: TextTable,
    *,
    stage_index: int,
) -> tuple[FormationGroup, ...]:
    """Return maximal adjacent six-byte-prefix plus 23-byte-name runs."""

    structural_cells: dict[int, FormationCell] = {}
    for offset in range(6, len(data) - 23 + 1):
        prefix = data[offset - 6 : offset]
        if not _known_record_prefix_is_valid(prefix):
            continue
        cell = _cell_at(data, offset, 23, table)
        if cell is not None:
            structural_cells[offset] = cell

    groups: list[FormationGroup] = []
    for offset in sorted(structural_cells):
        if offset - 29 in structural_cells:
            continue
        cells: list[FormationCell] = []
        current = offset
        while current in structural_cells:
            cell = structural_cells[current]
            cells.append(
                FormationCell(
                    offset=cell.offset,
                    source_text=cell.source_text,
                    source_consumed=cell.source_consumed,
                    trailer_hex="",
                    prefix_hex=data[current - 6 : current].hex(),
                )
            )
            current += 29
        # A lone prefix and zero-filled field can occur before ordinary
        # dialogue by chance.  Adjacent records are the independent ownership
        # proof for this runtime unit-table layout.
        if len(cells) < 2:
            continue
        groups.append(
            FormationGroup(
                stage_index=stage_index,
                layout="record6+23",
                slot_size=23,
                stride=29,
                cells=tuple(cells),
            )
        )
    return tuple(groups)


def _scan_structural_formation_groups(
    data: bytes,
    table: TextTable,
    *,
    stage_index: int,
) -> tuple[FormationGroup, ...]:
    """Return the actual 52-byte default-formation table records.

    Each record owns six big-endian member IDs (12 bytes), six bytes of
    metadata, a 33-byte zero-padded display name and one trailing identifier.
    Requiring at least two adjacent records plus valid member IDs prevents
    ordinary dialogue strings at the same byte alignment from being claimed.
    """

    structural_cells: dict[int, FormationCell] = {}
    for offset in range(18, len(data) - 33):
        member_ids = struct.unpack(">6H", data[offset - 18 : offset - 6])
        metadata = data[offset - 6 : offset]
        if (
            metadata[0] != 0
            or any(
                member_id != 0xFFFF
                and member_id > _FORMATION_MEMBER_ID_MAX
                for member_id in member_ids
            )
        ):
            continue
        cell = _cell_at(data, offset, 33, table)
        if cell is None:
            continue
        structural_cells[offset] = FormationCell(
            offset=cell.offset,
            source_text=cell.source_text,
            source_consumed=cell.source_consumed,
            trailer_hex=data[offset + 33 : offset + 34].hex(),
            prefix_hex=data[offset - 18 : offset].hex(),
        )

    groups: list[FormationGroup] = []
    for offset in sorted(structural_cells):
        if offset - 52 in structural_cells:
            continue
        cells: list[FormationCell] = []
        current = offset
        while current in structural_cells:
            cells.append(structural_cells[current])
            current += 52
        if len(cells) < 2:
            continue
        groups.append(
            FormationGroup(
                stage_index=stage_index,
                layout="formation18+33+1",
                slot_size=33,
                stride=52,
                cells=tuple(cells),
            )
        )
    return tuple(groups)


def discover_stage_default_formation_tables(
    stage: bytes,
    hb: bytes,
    table: TextTable,
) -> tuple[FormationGroup, ...]:
    """Return only the actual 52-byte default-formation table records."""

    offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(stage))
    groups: list[FormationGroup] = []
    for stage_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        decoded = decode(stage[start:end])
        if any(stage[start + decoded.consumed : end]):
            raise ValueError(f"STAGE {stage_index} has nonzero archive padding")
        groups.extend(
            _scan_structural_formation_groups(
                decoded.output,
                table,
                stage_index=stage_index,
            )
        )
    return tuple(groups)


def _scan_known_record_slots(
    data: bytes,
    table: TextTable,
    *,
    stage_index: int,
    source_texts: set[str] | frozenset[str],
) -> FormationGroup | None:
    """Find every known name in a six-byte-prefix plus 23-byte slot record.

    The old heuristic inferred groups from the *next* record's prefix and only
    accepted a subset of its type values.  That missed valid records when a
    squad was followed by a different leader type.  This scanner starts from
    the reviewed Japanese source inventory and validates the actual owning
    record, fixed slot, and zero padding instead.
    """

    for source_text in source_texts:
        encoded = encode_text(source_text, table, terminate=True)
        if len(encoded) > 23:
            raise ValueError(
                f"known default formation name exceeds its source slot: "
                f"{source_text!r}"
            )

    cells_by_offset: dict[int, FormationCell] = {}
    for group in _scan_structural_record_groups(
        data,
        table,
        stage_index=stage_index,
    ):
        for cell in group.cells:
            if cell.source_text in source_texts:
                cells_by_offset[cell.offset] = cell
    if not cells_by_offset:
        return None
    return FormationGroup(
        stage_index=stage_index,
        layout="record6+23",
        slot_size=23,
        stride=29,
        cells=tuple(cells_by_offset[offset] for offset in sorted(cells_by_offset)),
    )


def discover_structural_stage_default_formations(
    stage: bytes,
    hb: bytes,
    table: TextTable,
) -> tuple[FormationGroup, ...]:
    """Return every independently owned fixed-slot formation-name array."""

    offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(stage))
    groups: list[FormationGroup] = []
    for stage_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        decoded = decode(stage[start:end])
        if any(stage[start + decoded.consumed : end]):
            raise ValueError(f"STAGE {stage_index} has nonzero archive padding")
        record_groups = _scan_structural_record_groups(
            decoded.output,
            table,
            stage_index=stage_index,
        )
        formation_groups = _scan_structural_formation_groups(
            decoded.output,
            table,
            stage_index=stage_index,
        )
        groups.extend(formation_groups)
        groups.extend(record_groups)
        occupied = {
            cell.offset
            for group in (*formation_groups, *record_groups)
            for cell in group.cells
        }
        for group in _scan_layout(
            decoded.output,
            table,
            stage_index=stage_index,
            layout="slot32",
            slot_size=32,
            stride=32,
        ):
            cells = tuple(cell for cell in group.cells if cell.offset not in occupied)
            if cells:
                groups.append(
                    FormationGroup(
                        stage_index=group.stage_index,
                        layout=group.layout,
                        slot_size=group.slot_size,
                        stride=group.stride,
                        cells=cells,
                    )
                )
    return tuple(groups)


def discover_known_stage_default_formations(
    stage: bytes,
    hb: bytes,
    table: TextTable,
    source_texts: set[str] | frozenset[str],
) -> tuple[FormationGroup, ...]:
    """Return every fixed-slot occurrence of the reviewed Japanese names.

    The reviewed source inventory is the selection authority.  Record-backed
    names are found independently in every decoded STAGE chunk; the separate
    32-byte arrays retain their stricter repeated-array structural gate.
    """

    if not source_texts or any(not text for text in source_texts):
        raise ValueError("known default formation source inventory is empty")
    offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(stage))
    groups: list[FormationGroup] = []
    seen_sources: set[str] = set()
    for stage_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        decoded = decode(stage[start:end])
        if any(stage[start + decoded.consumed : end]):
            raise ValueError(f"STAGE {stage_index} has nonzero archive padding")
        formation_groups = _scan_structural_formation_groups(
            decoded.output,
            table,
            stage_index=stage_index,
        )
        occupied: set[int] = set()
        for structural_group in formation_groups:
            cells = tuple(
                cell
                for cell in structural_group.cells
                if cell.source_text in source_texts
            )
            if not cells:
                continue
            groups.append(
                FormationGroup(
                    stage_index=structural_group.stage_index,
                    layout=structural_group.layout,
                    slot_size=structural_group.slot_size,
                    stride=structural_group.stride,
                    cells=cells,
                )
            )
            occupied.update(cell.offset for cell in cells)
            seen_sources.update(cell.source_text for cell in cells)

        record_group = _scan_known_record_slots(
            decoded.output,
            table,
            stage_index=stage_index,
            source_texts=source_texts,
        )
        if record_group is not None:
            cells = tuple(
                cell for cell in record_group.cells if cell.offset not in occupied
            )
            if cells:
                groups.append(
                    FormationGroup(
                        stage_index=record_group.stage_index,
                        layout=record_group.layout,
                        slot_size=record_group.slot_size,
                        stride=record_group.stride,
                        cells=cells,
                    )
                )
                occupied.update(cell.offset for cell in cells)
                seen_sources.update(cell.source_text for cell in cells)
        for group in _scan_layout(
            decoded.output,
            table,
            stage_index=stage_index,
            layout="slot32",
            slot_size=32,
            stride=32,
        ):
            cells = tuple(
                cell
                for cell in group.cells
                if cell.source_text in source_texts and cell.offset not in occupied
            )
            if not cells:
                continue
            groups.append(
                FormationGroup(
                    stage_index=stage_index,
                    layout=group.layout,
                    slot_size=group.slot_size,
                    stride=group.stride,
                    cells=cells,
                )
            )
            seen_sources.update(cell.source_text for cell in cells)
    missing_sources = source_texts - seen_sources
    if missing_sources:
        raise ValueError(
            "reviewed default formation sources were not found in STAGE: "
            + ", ".join(sorted(missing_sources))
        )
    return tuple(groups)


def formation_inventory_sha256(groups: tuple[FormationGroup, ...]) -> str:
    """Hash the exact stage/order/source/trailer inventory."""

    payload = json.dumps(
        [asdict(group) for group in groups],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_locked_formation_inventory(
    groups: tuple[FormationGroup, ...],
) -> dict:
    """Serialize one reviewed scan into a compact fixed-position inventory."""

    sources = sorted(
        {cell.source_text for group in groups for cell in group.cells}
    )
    source_indices = {source: index for index, source in enumerate(sources)}
    return {
        "schema_version": 1,
        "status": "reviewed_locked",
        "selection_authority": "explicit_stage_offsets",
        "scan_policy": "explicit_refreeze_only",
        "sources": sources,
        "groups": [
            {
                "stage_index": group.stage_index,
                "layout": group.layout,
                "cells": [
                    [cell.offset, source_indices[cell.source_text]]
                    for cell in group.cells
                ],
            }
            for group in groups
        ],
        "expected": {
            "group_count": len(groups),
            "stage_count": len({group.stage_index for group in groups}),
            "entry_count": sum(len(group.cells) for group in groups),
            "unique_source_count": len(sources),
            "inventory_sha256": formation_inventory_sha256(groups),
        },
    }


def load_locked_stage_default_formations(
    stage: bytes,
    hb: bytes,
    table: TextTable,
    document: dict,
    decoded_cache: dict[int, DecodeResult] | None = None,
) -> tuple[FormationGroup, ...]:
    """Validate and load reviewed positions without scanning STAGE contents."""

    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 1
        or document.get("status") != "reviewed_locked"
        or document.get("selection_authority") != "explicit_stage_offsets"
        or document.get("scan_policy") != "explicit_refreeze_only"
        or not isinstance(document.get("sources"), list)
        or not isinstance(document.get("groups"), list)
        or not isinstance(document.get("expected"), dict)
    ):
        raise ValueError("locked default formation inventory contract drift")
    sources = document["sources"]
    if (
        not sources
        or any(not isinstance(source, str) or not source for source in sources)
        or sources != sorted(set(sources))
    ):
        raise ValueError("locked default formation source pool drift")

    offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(stage))
    decoded_by_stage: dict[int, bytes] = {}
    decoded_cache = decoded_cache if decoded_cache is not None else {}
    ranges_by_stage: dict[int, list[tuple[int, int]]] = {}
    groups: list[FormationGroup] = []
    for group_index, item in enumerate(document["groups"]):
        if (
            not isinstance(item, dict)
            or set(item) != {"stage_index", "layout", "cells"}
            or not isinstance(item.get("stage_index"), int)
            or item["stage_index"] < 0
            or item["stage_index"] + 1 >= len(offsets)
            or item.get("layout") not in _LOCKED_LAYOUT_SPECS
            or not isinstance(item.get("cells"), list)
            or not item["cells"]
        ):
            raise ValueError(
                f"locked default formation group drift: {group_index}"
            )
        stage_index = item["stage_index"]
        layout = item["layout"]
        spec = _LOCKED_LAYOUT_SPECS[layout]
        if stage_index not in decoded_by_stage:
            start, end = offsets[stage_index : stage_index + 2]
            if stage_index not in decoded_cache:
                decoded_cache[stage_index] = decode(stage[start:end])
            decoded = decoded_cache[stage_index]
            if any(stage[start + decoded.consumed : end]):
                raise ValueError(
                    f"STAGE {stage_index} has nonzero archive padding"
                )
            decoded_by_stage[stage_index] = decoded.output
            ranges_by_stage[stage_index] = []
        data = decoded_by_stage[stage_index]
        cells: list[FormationCell] = []
        for cell_index, pair in enumerate(item["cells"]):
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(value, int) for value in pair)
            ):
                raise ValueError(
                    "locked default formation cell drift: "
                    f"{group_index}/{cell_index}"
                )
            offset, source_index = pair
            if source_index < 0 or source_index >= len(sources):
                raise ValueError(
                    "locked default formation source index drift: "
                    f"{group_index}/{cell_index}"
                )
            slot_end = offset + spec["slot_size"]
            if offset < 0 or slot_end > len(data):
                raise ValueError(
                    "locked default formation offset drift: "
                    f"{group_index}/{cell_index}"
                )
            ranges = ranges_by_stage[stage_index]
            if any(offset < end and slot_end > start for start, end in ranges):
                raise ValueError(
                    "locked default formation overlap: "
                    f"{group_index}/{cell_index}"
                )
            cell = _cell_at(data, offset, spec["slot_size"], table)
            if cell is None or cell.source_text != sources[source_index]:
                raise ValueError(
                    "locked default formation source preimage drift: "
                    f"{group_index}/{cell_index}"
                )
            prefix_start = offset - spec["prefix_size"]
            trailer_end = slot_end + spec["trailer_size"]
            if prefix_start < 0 or trailer_end > len(data):
                raise ValueError(
                    "locked default formation owner boundary drift: "
                    f"{group_index}/{cell_index}"
                )
            cells.append(
                FormationCell(
                    offset=offset,
                    source_text=cell.source_text,
                    source_consumed=cell.source_consumed,
                    prefix_hex=data[prefix_start:offset].hex(),
                    trailer_hex=data[slot_end:trailer_end].hex(),
                )
            )
            ranges.append((offset, slot_end))
        groups.append(
            FormationGroup(
                stage_index=stage_index,
                layout=layout,
                slot_size=spec["slot_size"],
                stride=spec["stride"],
                cells=tuple(cells),
            )
        )

    result = tuple(groups)
    expected = document["expected"]
    if (
        len(result) != expected.get("group_count")
        or len(decoded_by_stage) != expected.get("stage_count")
        or sum(len(group.cells) for group in result)
        != expected.get("entry_count")
        or len(sources) != expected.get("unique_source_count")
        or {cell.source_text for group in result for cell in group.cells}
        != set(sources)
        or formation_inventory_sha256(result)
        != expected.get("inventory_sha256")
    ):
        raise ValueError("locked default formation inventory summary drift")
    return result
