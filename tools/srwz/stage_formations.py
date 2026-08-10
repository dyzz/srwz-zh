"""Discover and lock default formation-name records in STAGE chunks."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass

from .codec import decode
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .text import TextTable, decode_text


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


@dataclass(frozen=True)
class FormationGroup:
    stage_index: int
    layout: str
    slot_size: int
    stride: int
    cells: tuple[FormationCell, ...]


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


def formation_inventory_sha256(groups: tuple[FormationGroup, ...]) -> str:
    """Hash the exact stage/order/source/trailer inventory."""

    payload = json.dumps(
        [asdict(group) for group in groups],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
