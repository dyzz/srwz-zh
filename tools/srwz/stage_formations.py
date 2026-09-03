"""Discover and lock default formation-name records in STAGE chunks."""

from __future__ import annotations

import hashlib
import json
import struct
import unicodedata
from dataclasses import asdict, dataclass

from .codec import DecodeResult, decode_production as decode
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .stage import STAGE_BASE_ADDRESS
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
    **{
        f"packed8-{slot_size}": {
            "slot_size": slot_size,
            "stride": slot_size,
            "prefix_size": 0,
            "trailer_size": 0,
        }
        for slot_size in range(8, 65, 8)
    },
    **{
        f"pointer8-{slot_size}": {
            "slot_size": slot_size,
            "stride": slot_size,
            "prefix_size": 0,
            "trailer_size": 0,
        }
        for slot_size in range(8, 65, 8)
    },
}


def _is_stage_formation_pointer_record(
    data: bytes,
    pointer_offset: int,
    text_address: int,
) -> bool:
    if (
        pointer_offset < 16
        or pointer_offset + 16 > len(data)
        or struct.unpack_from("<I", data, pointer_offset)[0] != text_address
        or data[pointer_offset - 8 : pointer_offset - 6] != b"\xFF\xFF"
        or data[pointer_offset - 2 : pointer_offset] != b"\xFF\xFF"
    ):
        return False
    selector, next_record, terminal = struct.unpack_from(
        "<III", data, pointer_offset + 4
    )
    return (
        selector == 0xFF and next_record == 0 and terminal == 0
    ) or (
        selector >> 16 == 0xFF
        and selector & 0xFFFF
        and next_record == 0xFFFFFFFF
        and terminal == 0
    )


def has_stage_formation_pointer_owner(data: bytes, text_offset: int) -> bool:
    """Return whether a formation owner record points to *text_offset*.

    Some formation-name tables contain only one or two strings, so adjacency
    cannot prove ownership.  Their 32-byte owner records place the name pointer
    at byte 16 and retain two sentinel halfwords.  A leader uses the plain
    ``0xFF`` selector and zero tail; indexed squad members use ``0x00FFxxxx``
    plus the ``0xFFFFFFFF, 0`` tail.  Validate the complete local signature so
    a glossary row or ordinary dialogue pointer cannot claim the same text.
    """

    if not 0 <= text_offset < len(data):
        return False
    address = STAGE_BASE_ADDRESS + text_offset
    return any(
        _is_stage_formation_pointer_record(data, offset, address)
        for offset in range(16, len(data) - 15, 4)
    )


def discover_stage_formation_pointer_owners(data: bytes) -> dict[int, int]:
    """Return text-pointer offsets owned by validated formation records."""

    owners = {}
    for pointer_offset in range(16, len(data) - 15, 4):
        text_address = struct.unpack_from("<I", data, pointer_offset)[0]
        text_offset = text_address - STAGE_BASE_ADDRESS
        if (
            0 <= text_offset < len(data)
            and _is_stage_formation_pointer_record(
                data,
                pointer_offset,
                text_address,
            )
        ):
            owners[pointer_offset] = text_offset
    return owners


def _stage_formation_pointer_targets(data: bytes) -> frozenset[int]:
    """Return decoded name offsets owned by formation pointer records."""

    return frozenset(
        target
        for offset in range(16, len(data) - 15, 4)
        if 0
        <= (target := struct.unpack_from("<I", data, offset)[0] - STAGE_BASE_ADDRESS)
        < len(data)
        and _is_stage_formation_pointer_record(
            data,
            offset,
            STAGE_BASE_ADDRESS + target,
        )
    )


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
    """Find every independently owned known 6+23-byte name record.

    The old heuristic inferred groups from the *next* record's prefix and only
    accepted a subset of its type values.  That missed valid records when a
    squad was followed by a different leader type or when a valid record was
    isolated.  This scanner starts from the reviewed Japanese source inventory
    and validates the actual owning prefix, fixed slot, and zero padding
    independently instead.
    """

    for source_text in source_texts:
        encoded = encode_text(source_text, table, terminate=True)
        if len(encoded) > 23:
            raise ValueError(
                f"known default formation name exceeds its source slot: "
                f"{source_text!r}"
            )

    cells_by_offset: dict[int, FormationCell] = {}
    for offset in range(6, len(data) - 23 + 1):
        prefix = data[offset - 6 : offset]
        if not _known_record_prefix_is_valid(prefix):
            continue
        cell = _cell_at(data, offset, 23, table)
        if cell is None or cell.source_text not in source_texts:
            continue
        cells_by_offset[offset] = FormationCell(
            offset=cell.offset,
            source_text=cell.source_text,
            source_consumed=cell.source_consumed,
            trailer_hex="",
            prefix_hex=prefix.hex(),
        )
    if not cells_by_offset:
        return None
    return FormationGroup(
        stage_index=stage_index,
        layout="record6+23",
        slot_size=23,
        stride=29,
        cells=tuple(cells_by_offset[offset] for offset in sorted(cells_by_offset)),
    )


def _scan_known_formation_slots(
    data: bytes,
    table: TextTable,
    *,
    stage_index: int,
    source_texts: set[str] | frozenset[str],
) -> FormationGroup | None:
    """Find every independently owned known 18+33+1 formation record.

    Repeated adjacent records remain the authority for open-ended structural
    discovery.  Once the Japanese source-name set has been reviewed, however,
    a single record has sufficient ownership evidence: the full 18-byte owner
    prefix, a zero-padded 33-byte name from that reviewed source set, and its
    trailing identifier.  Some runtime auto-formation records use sentinel or
    packed values in the first 12 bytes instead of six ordinary bounded member
    IDs.  Those values are opaque owner metadata and are preserved byte-exact;
    rejecting them left valid auto-generated squad names outside the locked
    inventory.
    """

    candidates_by_offset: dict[int, FormationCell] = {}
    for offset in range(18, len(data) - 33):
        metadata = data[offset - 6 : offset]
        if metadata[0] != 0:
            continue
        cell = _cell_at(data, offset, 33, table)
        if cell is None or cell.source_text not in source_texts:
            continue
        candidates_by_offset[offset] = FormationCell(
            offset=cell.offset,
            source_text=cell.source_text,
            source_consumed=cell.source_consumed,
            trailer_hex=data[offset + 33 : offset + 34].hex(),
            prefix_hex=data[offset - 18 : offset].hex(),
        )
    if not candidates_by_offset:
        return None
    return FormationGroup(
        stage_index=stage_index,
        layout="formation18+33+1",
        slot_size=33,
        stride=52,
        cells=tuple(
            candidates_by_offset[offset]
            for offset in sorted(candidates_by_offset)
        ),
    )


def _scan_packed8_groups(
    data: bytes,
    table: TextTable,
    *,
    stage_index: int,
    source_texts: set[str] | frozenset[str] | None,
    owner_data: bytes | None = None,
) -> tuple[FormationGroup, ...]:
    """Find names inside eight-byte-aligned packed string tables.

    These tables store variable-size, NUL-terminated fields.  Each next field
    begins on an eight-byte boundary, so a fixed 23- or 32-byte probe misses a
    short field when another string immediately follows it.  Three linked
    fields prove table ownership after a formation pointer roots the run.
    One- and two-field tables require a formation pointer to every selected
    field and receive a separate locked layout so later builds revalidate that
    ownership proof.  A reviewed source set may additionally recover the same
    name from other repeated formation tables; passing ``None`` performs the
    owner-first discovery used to prevent source-inventory omissions.
    """

    starts: dict[int, tuple[FormationCell, int]] = {}
    for offset in range(0, len(data), 8):
        if offset and data[offset - 1] != 0:
            continue
        for slot_size in range(8, 65, 8):
            if offset + slot_size > len(data):
                break
            cell = _cell_at(data, offset, slot_size, table)
            if cell is not None:
                starts[offset] = (cell, slot_size)
                break

    ordered_offsets = sorted(starts)
    next_by_offset: dict[int, int] = {}
    for index, offset in enumerate(ordered_offsets):
        cell, _minimum_slot_size = starts[offset]
        for next_offset in ordered_offsets[index + 1 :]:
            if next_offset - offset > 64:
                break
            if not any(data[offset + cell.source_consumed : next_offset]):
                next_by_offset[offset] = next_offset
                break

    pointer_targets = _stage_formation_pointer_targets(
        data if owner_data is None else owner_data
    )
    previous_offsets = set(next_by_offset.values())
    cells_by_layout: dict[str, list[FormationCell]] = {}
    for run_start in ordered_offsets:
        if run_start in previous_offsets:
            continue
        run = [run_start]
        while run[-1] in next_by_offset:
            run.append(next_by_offset[run[-1]])
        repeated_table = len(run) >= 3
        if source_texts is None and repeated_table and not any(
            offset in pointer_targets for offset in run
        ):
            continue
        for index, offset in enumerate(run):
            cell, minimum_slot_size = starts[offset]
            if (
                (
                    source_texts is not None
                    and cell.source_text not in source_texts
                )
                or (not repeated_table and offset not in pointer_targets)
            ):
                continue
            slot_size = (
                run[index + 1] - offset
                if index + 1 < len(run)
                else minimum_slot_size
            )
            layout_prefix = "packed8" if repeated_table else "pointer8"
            layout = f"{layout_prefix}-{slot_size}"
            if layout not in _LOCKED_LAYOUT_SPECS:
                continue
            cells_by_layout.setdefault(layout, []).append(cell)

    return tuple(
        FormationGroup(
            stage_index=stage_index,
            layout=layout,
            slot_size=_LOCKED_LAYOUT_SPECS[layout]["slot_size"],
            stride=_LOCKED_LAYOUT_SPECS[layout]["stride"],
            cells=tuple(cells),
        )
        for layout, cells in sorted(cells_by_layout.items())
    )


_COMPACT_ASCII_FORMATION_TRANSLATIONS: dict[tuple[str, str], str] = {
    ("packed8-8", "ザフト"): "ZAFT",
}


def compact_formation_ascii_replacement(
    *,
    source_text: str,
    translation: str,
    layout: str,
    slot_size: int,
) -> bytes | None:
    """Return one explicitly reviewed raw-ASCII packed-field replacement.

    The allowlist is limited to source/layout pairs whose canonical Latin name
    cannot fit through the normal two-byte text encoder.  Every use is counted
    and reread from the final ISO.
    """

    if _COMPACT_ASCII_FORMATION_TRANSLATIONS.get(
        (layout, source_text)
    ) != translation:
        return None
    compact = translation.encode("ascii") + b"\x00"
    if len(compact) > slot_size:
        return None
    return compact + bytes(slot_size - len(compact))


def fit_formation_replacement(
    *,
    source_text: str,
    translation: str,
    layout: str,
    slot_size: int,
    encoded: bytes,
) -> bytes | None:
    """Fit a canonical replacement into one locked formation-name slot.

    Any overflows remain excluded from the frozen inventory unless an exact
    field/layout pair is explicitly reviewed in the compact-ASCII allowlist.
    """

    if len(encoded) <= slot_size:
        return encoded + bytes(slot_size - len(encoded))
    return compact_formation_ascii_replacement(
        source_text=source_text,
        translation=translation,
        layout=layout,
        slot_size=slot_size,
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


def discover_owned_stage_formation_names(
    stage: bytes,
    hb: bytes,
    table: TextTable,
    *,
    owner_stage: bytes | None = None,
) -> tuple[FormationGroup, ...]:
    """Return packed formation names rooted by their runtime owner records.

    This scan intentionally does not accept a source-text inventory.  It is the
    independent discovery side of an explicit refreeze: owner records prove the
    table first, then the current-component preimage filter decides which fixed
    slots remain safe to add to the locked occurrence inventory.
    """

    if owner_stage is not None and len(owner_stage) != len(stage):
        raise ValueError("owner STAGE size differs from source STAGE")
    offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(stage))
    groups: list[FormationGroup] = []
    for stage_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        decoded = decode(stage[start:end])
        owner_decoded = (
            decoded if owner_stage is None else decode(owner_stage[start:end])
        )
        if any(stage[start + decoded.consumed : end]):
            raise ValueError(f"STAGE {stage_index} has nonzero archive padding")
        if owner_stage is not None and (
            any(owner_stage[start + owner_decoded.consumed : end])
            or len(owner_decoded.output) != len(decoded.output)
        ):
            raise ValueError(
                f"owner STAGE {stage_index} decode or padding drift"
            )
        groups.extend(
            _scan_packed8_groups(
                decoded.output,
                table,
                stage_index=stage_index,
                source_texts=None,
                owner_data=owner_decoded.output,
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

    The reviewed source inventory is the selection authority.  Repeated
    structural groups are retained first, then independently owned singleton
    formation and unit-name records are added.  The separate 32-byte arrays
    retain their stricter repeated-array structural gate.
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

        structural_record_cells = {
            cell.offset: cell
            for structural_group in _scan_structural_record_groups(
                decoded.output,
                table,
                stage_index=stage_index,
            )
            for cell in structural_group.cells
            if cell.source_text in source_texts and cell.offset not in occupied
        }
        if structural_record_cells:
            cells = tuple(
                structural_record_cells[offset]
                for offset in sorted(structural_record_cells)
            )
            if cells:
                groups.append(
                    FormationGroup(
                        stage_index=stage_index,
                        layout="record6+23",
                        slot_size=23,
                        stride=29,
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
            occupied.update(cell.offset for cell in cells)
            seen_sources.update(cell.source_text for cell in cells)

        independent_formation_group = _scan_known_formation_slots(
            decoded.output,
            table,
            stage_index=stage_index,
            source_texts=source_texts,
        )
        independent_record_group = _scan_known_record_slots(
            decoded.output,
            table,
            stage_index=stage_index,
            source_texts=source_texts,
        )
        independent_fixed_offsets = {
            cell.offset
            for group in (independent_formation_group, independent_record_group)
            if group is not None
            for cell in group.cells
        }

        for packed_group in _scan_packed8_groups(
            decoded.output,
            table,
            stage_index=stage_index,
            source_texts=source_texts,
        ):
            cells = tuple(
                cell
                for cell in packed_group.cells
                if cell.offset not in occupied
                and not (
                    packed_group.layout.startswith("pointer8-")
                    and cell.offset in independent_fixed_offsets
                )
            )
            if not cells:
                continue
            groups.append(
                FormationGroup(
                    stage_index=stage_index,
                    layout=packed_group.layout,
                    slot_size=packed_group.slot_size,
                    stride=packed_group.stride,
                    cells=cells,
                )
            )
            occupied.update(cell.offset for cell in cells)
            seen_sources.update(cell.source_text for cell in cells)

        if independent_formation_group is not None:
            cells = tuple(
                cell
                for cell in independent_formation_group.cells
                if cell.offset not in occupied
            )
            if cells:
                groups.append(
                    FormationGroup(
                        stage_index=stage_index,
                        layout=independent_formation_group.layout,
                        slot_size=independent_formation_group.slot_size,
                        stride=independent_formation_group.stride,
                        cells=cells,
                    )
                )
                occupied.update(cell.offset for cell in cells)
                seen_sources.update(cell.source_text for cell in cells)

        if independent_record_group is not None:
            cells = tuple(
                cell
                for cell in independent_record_group.cells
                if cell.offset not in occupied
            )
            if cells:
                groups.append(
                    FormationGroup(
                        stage_index=stage_index,
                        layout=independent_record_group.layout,
                        slot_size=independent_record_group.slot_size,
                        stride=independent_record_group.stride,
                        cells=cells,
                    )
                )
                occupied.update(cell.offset for cell in cells)
                seen_sources.update(cell.source_text for cell in cells)
    missing_sources = source_texts - seen_sources
    if missing_sources:
        raise ValueError(
            "reviewed default formation sources were not found in STAGE: "
            + ", ".join(sorted(missing_sources))
        )
    return tuple(groups)


def filter_current_stage_default_formations(
    original_stage: bytes,
    current_stage: bytes,
    hb: bytes,
    groups: tuple[FormationGroup, ...],
    replacements_by_source: dict[str, bytes],
    translations_by_source: dict[str, str],
    accepted_current_replacements_by_source: dict[
        str, tuple[tuple[str, bytes], ...]
    ] | None = None,
) -> tuple[FormationGroup, ...]:
    """Keep only candidates whose current owner and text preimage are intact.

    A reviewed Japanese name plus zero padding is useful for finding candidates,
    but isolated dialogue strings can have the same byte shape by coincidence.
    The release component is therefore the second selection authority during an
    explicit refreeze: its slot must still contain the original bytes, the
    canonical translated bytes, or a source-bound prior translation explicitly
    accepted for migration, and record metadata must remain byte-exact.
    """

    if len(original_stage) != len(current_stage):
        raise ValueError("current STAGE size differs from the original STAGE")
    offsets = read_executable_archive_offsets(
        hb, STAGE_OFFSET_SPEC, len(original_stage)
    )
    original_by_stage: dict[int, bytes] = {}
    current_by_stage: dict[int, bytes] = {}
    filtered: list[FormationGroup] = []
    for group in groups:
        stage_index = group.stage_index
        if stage_index not in original_by_stage:
            start, end = offsets[stage_index : stage_index + 2]
            original_decoded = decode(original_stage[start:end])
            current_decoded = decode(current_stage[start:end])
            if (
                any(original_stage[start + original_decoded.consumed : end])
                or any(current_stage[start + current_decoded.consumed : end])
                or len(original_decoded.output) != len(current_decoded.output)
            ):
                raise ValueError(
                    f"current STAGE decode drift during refreeze: {stage_index}"
                )
            original_by_stage[stage_index] = original_decoded.output
            current_by_stage[stage_index] = current_decoded.output
        original = original_by_stage[stage_index]
        current = current_by_stage[stage_index]
        cells: list[FormationCell] = []
        for cell in group.cells:
            replacement = replacements_by_source.get(cell.source_text)
            translation = translations_by_source.get(cell.source_text)
            if replacement is None or translation is None:
                raise ValueError(
                    "missing current-stage replacement for reviewed source: "
                    f"{cell.source_text!r}"
                )
            slot_end = cell.offset + group.slot_size
            source_slot = original[cell.offset:slot_end]
            replacement_slot = fit_formation_replacement(
                source_text=cell.source_text,
                translation=translation,
                layout=group.layout,
                slot_size=group.slot_size,
                encoded=replacement,
            )
            if replacement_slot is None:
                continue
            accepted_slots = {source_slot, replacement_slot}
            for prior_translation, prior_encoded in (
                accepted_current_replacements_by_source or {}
            ).get(cell.source_text, ()):
                prior_slot = fit_formation_replacement(
                    source_text=cell.source_text,
                    translation=prior_translation,
                    layout=group.layout,
                    slot_size=group.slot_size,
                    encoded=prior_encoded,
                )
                if (
                    prior_slot is None
                    and prior_translation.isascii()
                    and len(prior_translation.encode("ascii")) + 1
                    <= group.slot_size
                ):
                    compact = prior_translation.encode("ascii") + b"\x00"
                    prior_slot = compact + bytes(group.slot_size - len(compact))
                if prior_slot is not None:
                    accepted_slots.add(prior_slot)
            current_slot = current[cell.offset:slot_end]
            if current_slot not in accepted_slots:
                continue
            prefix_size = _LOCKED_LAYOUT_SPECS[group.layout]["prefix_size"]
            trailer_size = _LOCKED_LAYOUT_SPECS[group.layout]["trailer_size"]
            prefix_start = cell.offset - prefix_size
            trailer_end = slot_end + trailer_size
            if (
                current[prefix_start:cell.offset]
                != original[prefix_start:cell.offset]
                or current[slot_end:trailer_end]
                != original[slot_end:trailer_end]
            ):
                continue
            cells.append(cell)
        if cells:
            filtered.append(
                FormationGroup(
                    stage_index=group.stage_index,
                    layout=group.layout,
                    slot_size=group.slot_size,
                    stride=group.stride,
                    cells=tuple(cells),
                )
            )
    return tuple(filtered)


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
            if layout.startswith(
                "pointer8-"
            ) and not has_stage_formation_pointer_owner(data, offset):
                raise ValueError(
                    "locked default formation pointer owner drift: "
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
