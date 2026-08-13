"""Bind the 52 runtime glossary entries across LIBRARY, COMPDATA and STAGE.

The game keeps three independent copies of glossary data:

* ``DATA/MTVZKNKW.BIN`` owns the encyclopedia popup title/body;
* decoded ``DATA/COMPDATA.BN`` owns the encyclopedia list labels;
* 44 decoded ``DATA/STAGE.BIN`` chunks own 77 story-popup copies.

This module treats the reviewed LIBRARY archive as the byte authority for all
four KYWD fields and rewrites the other two stores without changing their
outer archive layouts.  The few translated WORD values that exceed their
retail allocation are moved into explicitly locked, zero-filled slack and the
owning pointer is updated.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import struct
from typing import Mapping, Sequence

from .codec import decode_production, reencode_changed_suffix
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .library import ZkanField, parse_runtime_zkn_decoded_chunk
from .text import (
    PreparedTextEncoder,
    TextTable,
    decode_text,
    normalize_original_fullwidth_ascii,
)


FIELD_TAGS = ("WORD", "SRCE", "DSCR", "DSC2")
FIELD_INDEX = {tag: index for index, tag in enumerate(FIELD_TAGS)}


class RuntimeKeywordError(ValueError):
    """A runtime-keyword source, ownership, or readback contract failed."""


@dataclass(frozen=True)
class KeywordEntry:
    entry_index: int
    source_term: str
    source_text_sha256: str
    translation: str


@dataclass(frozen=True)
class KeywordAuthority:
    entries: tuple[KeywordEntry, ...]
    fields: tuple[Mapping[str, ZkanField], ...]


@dataclass(frozen=True)
class EmbeddedRecord:
    stage_index: int
    row_offset: int
    keyword_index: int
    field_offsets: tuple[int, int, int, int]


@dataclass(frozen=True)
class AllocationReference:
    keyword_index: int
    tag: str
    row_offset: int


@dataclass(frozen=True)
class EmbeddedAllocation:
    stage_index: int
    offset: int
    capacity: int
    source_slot: bytes
    target: bytes
    references: tuple[AllocationReference, ...]


def _number(value: object, *, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise RuntimeKeywordError(f"{label} is not an integer") from error
    raise RuntimeKeywordError(f"{label} is not an integer")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _aligned(value: int, alignment: int = 2) -> int:
    return (value + alignment - 1) & -alignment


def _require_expected(actual: int, expected: Mapping[str, object], key: str) -> None:
    if actual != expected.get(key):
        raise RuntimeKeywordError(
            f"runtime-keyword {key} drift: {actual} != {expected.get(key)!r}"
        )


def load_keyword_authority(
    catalog_data: bytes,
    library_archive: bytes,
    executable: bytes,
    runtime_table: TextTable,
    *,
    table_start: int,
    table_end: int,
    expected_count: int = 52,
) -> KeywordAuthority:
    """Load the approved slot catalog and exact translated KYWD field bytes."""

    try:
        catalog = json.loads(catalog_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeKeywordError("runtime-keyword catalog is not valid JSON") from error
    rows = catalog.get("entries")
    if (
        catalog.get("schema_version") != 1
        or catalog.get("profile_id") != "srwz-stage-runtime-keywords-v1"
        or catalog.get("status") != "approved"
        or not isinstance(rows, list)
        or len(rows) != expected_count
    ):
        raise RuntimeKeywordError("runtime-keyword catalog identity drift")

    entries = []
    for expected_index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RuntimeKeywordError("runtime-keyword catalog row is malformed")
        entry_index = row.get("entry_index")
        source_term = row.get("source_term")
        source_hash = row.get("source_text_sha256")
        translation = row.get("translation")
        if (
            entry_index != expected_index
            or not isinstance(source_term, str)
            or not source_term
            or not isinstance(source_hash, str)
            or source_hash != _sha256(source_term.encode("utf-8"))
            or not isinstance(translation, str)
            or not translation
        ):
            raise RuntimeKeywordError(
                f"runtime-keyword catalog row drift at slot {expected_index}"
            )
        entries.append(
            KeywordEntry(
                entry_index=entry_index,
                source_term=source_term,
                source_text_sha256=source_hash,
                translation=translation,
            )
        )

    offsets = read_executable_archive_offsets(
        executable,
        ExecutableOffsetSpec(
            name="DATA/MTVZKNKW.BIN",
            member="DATA/MTVZKNKW.BIN",
            table_start=table_start,
            table_end=table_end,
        ),
        len(library_archive),
    )
    if len(offsets) - 1 != expected_count:
        raise RuntimeKeywordError("translated KYWD archive entry-count drift")

    field_sets = []
    for entry, (start, end) in zip(entries, zip(offsets, offsets[1:])):
        stored = library_archive[start:end]
        decoded = decode_production(stored)
        if any(stored[decoded.consumed :]):
            raise RuntimeKeywordError(
                f"translated KYWD slot {entry.entry_index} has nonzero padding"
            )
        document = parse_runtime_zkn_decoded_chunk(decoded.output, runtime_table)
        fields = {field.tag: field for field in document.fields}
        if document.kind != "KYWD" or tuple(fields) != FIELD_TAGS:
            raise RuntimeKeywordError(
                f"translated KYWD field contract drift at slot {entry.entry_index}"
            )
        if (
            normalize_original_fullwidth_ascii(fields["WORD"].text or "")
            != entry.translation
        ):
            raise RuntimeKeywordError(
                f"translated KYWD WORD disagrees with catalog at slot "
                f"{entry.entry_index}"
            )
        field_sets.append(fields)
    return KeywordAuthority(entries=tuple(entries), fields=tuple(field_sets))


def _allocation_end(decoded: bytes, text_end: int) -> int:
    end = text_end
    while end < len(decoded) and decoded[end] == 0:
        end += 1
    return end


def _discover_embedded_inventory(
    original_stage: bytes,
    hb: bytes,
    authority: KeywordAuthority,
    source_table: TextTable,
    *,
    runtime_base: int,
    hb_table_start: int,
    hb_table_end: int,
    expected: Mapping[str, object],
) -> tuple[
    tuple[int, ...],
    dict[int, object],
    tuple[EmbeddedRecord, ...],
    tuple[EmbeddedAllocation, ...],
]:
    offsets = read_executable_archive_offsets(
        hb,
        ExecutableOffsetSpec(
            name="HEDBDY/HB.BIN STAGE offsets",
            member="HEDBDY/HB.BIN",
            table_start=hb_table_start,
            table_end=hb_table_end,
        ),
        len(original_stage),
    )
    encoder = PreparedTextEncoder(source_table)
    decoded_by_stage: dict[int, object] = {}
    records_by_key: dict[tuple[int, int, int], EmbeddedRecord] = {}

    for stage_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        stored = original_stage[start:end]
        decoded = decode_production(stored)
        if any(stored[decoded.consumed :]):
            raise RuntimeKeywordError(
                f"original STAGE chunk {stage_index} has nonzero padding"
            )
        raw = decoded.output
        found_in_stage = False
        for entry in authority.entries:
            source_payload = encoder.encode(entry.source_term, terminate=True)
            source_offset = 0
            while True:
                source_offset = raw.find(source_payload, source_offset)
                if source_offset < 0:
                    break
                pointer_bytes = struct.pack("<I", runtime_base + source_offset)
                row_offset = 0
                while True:
                    row_offset = raw.find(pointer_bytes, row_offset)
                    if row_offset < 0:
                        break
                    if row_offset % 4 == 0 and row_offset + 16 <= len(raw):
                        pointers = struct.unpack_from("<4I", raw, row_offset)
                        field_offsets = tuple(
                            pointer - runtime_base for pointer in pointers
                        )
                        if (
                            field_offsets[0] == source_offset
                            and all(0 <= offset < len(raw) for offset in field_offsets)
                        ):
                            try:
                                word = decode_text(raw, field_offsets[0], source_table)
                            except ValueError:
                                word = None
                            if word is not None and word.text == entry.source_term:
                                key = (stage_index, row_offset, entry.entry_index)
                                records_by_key[key] = EmbeddedRecord(
                                    stage_index=stage_index,
                                    row_offset=row_offset,
                                    keyword_index=entry.entry_index,
                                    field_offsets=field_offsets,
                                )
                                found_in_stage = True
                    row_offset += 1
                source_offset += 1
        if found_in_stage:
            decoded_by_stage[stage_index] = decoded

    records = tuple(sorted(records_by_key.values(), key=lambda row: (
        row.stage_index,
        row.row_offset,
        row.keyword_index,
    )))
    allocation_rows: dict[tuple[int, int], dict[str, object]] = {}
    for record in records:
        raw = decoded_by_stage[record.stage_index].output
        for tag, offset in zip(FIELD_TAGS, record.field_offsets):
            source = decode_text(raw, offset, source_table)
            end = _allocation_end(raw, source.end)
            target = authority.fields[record.keyword_index][tag].data + b"\0"
            key = (record.stage_index, offset)
            row = allocation_rows.setdefault(
                key,
                {
                    "capacity": end - offset,
                    "source_slot": raw[offset:end],
                    "target": target,
                    "references": [],
                },
            )
            if (
                row["capacity"] != end - offset
                or row["source_slot"] != raw[offset:end]
                or row["target"] != target
            ):
                raise RuntimeKeywordError(
                    f"shared STAGE keyword allocation conflict at "
                    f"{record.stage_index}:0x{offset:X}"
                )
            row["references"].append(
                AllocationReference(
                    keyword_index=record.keyword_index,
                    tag=tag,
                    row_offset=record.row_offset,
                )
            )

    allocations = tuple(
        EmbeddedAllocation(
            stage_index=stage_index,
            offset=offset,
            capacity=int(row["capacity"]),
            source_slot=bytes(row["source_slot"]),
            target=bytes(row["target"]),
            references=tuple(row["references"]),
        )
        for (stage_index, offset), row in sorted(allocation_rows.items())
    )
    stage_indices = {record.stage_index for record in records}
    keyword_indices = {record.keyword_index for record in records}
    reference_count = sum(len(allocation.references) for allocation in allocations)
    shared_reference_count = reference_count - len(allocations)
    _require_expected(len(records), expected, "stage_record_count")
    _require_expected(len(stage_indices), expected, "stage_chunk_count")
    _require_expected(len(keyword_indices), expected, "stage_keyword_count")
    _require_expected(reference_count, expected, "stage_field_reference_count")
    _require_expected(len(allocations), expected, "stage_allocation_count")
    _require_expected(
        shared_reference_count,
        expected,
        "stage_shared_reference_count",
    )
    if keyword_indices != set(range(len(authority.entries))):
        raise RuntimeKeywordError("embedded STAGE keywords do not cover all slots")
    return offsets, decoded_by_stage, records, allocations


def _stage_relocation_plan(
    raw_relocations: object,
    allocations: Sequence[EmbeddedAllocation],
    records: Sequence[EmbeddedRecord],
    *,
    runtime_base: int,
) -> tuple[
    dict[tuple[int, int], tuple[int, bytes, str]],
    list[dict[str, object]],
]:
    if not isinstance(raw_relocations, list):
        raise RuntimeKeywordError("STAGE keyword relocations must be an array")
    by_key = {(row.stage_index, row.offset): row for row in allocations}
    all_pointer_targets = {
        (record.stage_index, offset)
        for record in records
        for offset in record.field_offsets
    }
    plan: dict[tuple[int, int], tuple[int, bytes, str]] = {}
    report = []
    for index, raw in enumerate(raw_relocations):
        if not isinstance(raw, dict):
            raise RuntimeKeywordError("STAGE keyword relocation is malformed")
        stage_index = _number(raw.get("stage_index"), label="stage_index")
        keyword_index = _number(raw.get("keyword_index"), label="keyword_index")
        tag = raw.get("tag")
        source_offset = _number(raw.get("source_offset"), label="source_offset")
        donor_offset = _number(raw.get("donor_offset"), label="donor_offset")
        relocation_offset = _number(
            raw.get("relocation_offset"), label="relocation_offset"
        )
        reason = raw.get("reason")
        if tag not in FIELD_INDEX:
            raise RuntimeKeywordError("STAGE keyword relocation tag is invalid")
        source = by_key.get((stage_index, source_offset))
        donor = by_key.get((stage_index, donor_offset))
        matching_refs = (
            []
            if source is None
            else [
                ref
                for ref in source.references
                if ref.keyword_index == keyword_index and ref.tag == tag
            ]
        )
        expected_relocation = (
            donor_offset + _aligned(len(donor.target)) if donor is not None else -1
        )
        if (
            source is None
            or donor is None
            or not matching_refs
            or (
                len(source.target) <= source.capacity
                and reason != "occupied_current_allocation"
            )
            or reason not in {"fixed_allocation_overflow", "occupied_current_allocation"}
            or (
                len(source.target) > source.capacity
                and reason != "fixed_allocation_overflow"
            )
            or relocation_offset != expected_relocation
            or relocation_offset + len(source.target)
            > donor.offset + donor.capacity
            or (stage_index, relocation_offset) in all_pointer_targets
        ):
            raise RuntimeKeywordError(
                f"STAGE keyword relocation contract drift at row {index}"
            )
        key = (stage_index, source_offset)
        if key in plan:
            raise RuntimeKeywordError("duplicate STAGE keyword relocation")
        plan[key] = (relocation_offset, source.target, reason)
        report.append(
            {
                "stage_index": stage_index,
                "keyword_index": keyword_index,
                "tag": tag,
                "source_offset": source_offset,
                "source_capacity": source.capacity,
                "target_size": len(source.target),
                "donor_offset": donor_offset,
                "donor_capacity": donor.capacity,
                "donor_target_size": len(donor.target),
                "relocation_offset": relocation_offset,
                "runtime_pointer": runtime_base + relocation_offset,
                "pointer_reference_count": len(matching_refs),
                "reason": reason,
                "source_allocation_preserved": True,
            }
        )
    overflows = {
        (row.stage_index, row.offset)
        for row in allocations
        if len(row.target) > row.capacity
    }
    if not overflows <= set(plan):
        raise RuntimeKeywordError(
            f"STAGE keyword overflow coverage drift: "
            f"plan={sorted(plan)} overflows={sorted(overflows)}"
        )
    return plan, report


def _rewrite_stage_decoded(
    current: bytes,
    original: bytes,
    stage_index: int,
    records: Sequence[EmbeddedRecord],
    allocations: Sequence[EmbeddedAllocation],
    relocation_plan: Mapping[tuple[int, int], tuple[int, bytes, str]],
    *,
    runtime_base: int,
) -> tuple[bytes, dict[str, int]]:
    stage_records = [row for row in records if row.stage_index == stage_index]
    stage_allocations = [row for row in allocations if row.stage_index == stage_index]
    if len(current) != len(original):
        raise RuntimeKeywordError(f"STAGE decoded size drift at {stage_index}")

    final_slots: dict[int, bytes] = {}
    donors: dict[int, list[tuple[int, bytes]]] = {}
    for allocation in stage_allocations:
        relocation = relocation_plan.get((stage_index, allocation.offset))
        if relocation is None:
            if len(allocation.target) > allocation.capacity:
                raise RuntimeKeywordError("unplanned STAGE keyword overflow")
            final = allocation.target + bytes(allocation.capacity - len(allocation.target))
        else:
            # The old WORD allocation may have been reclaimed by translated
            # dialogue (Stage 2 does this).  Redirect the glossary pointer but
            # preserve every byte of the current source allocation.
            final = current[
                allocation.offset : allocation.offset + allocation.capacity
            ]
            relocation_offset, payload, _reason = relocation
            donor = next(
                (
                    candidate
                    for candidate in stage_allocations
                    if candidate.offset <= relocation_offset
                    and relocation_offset + len(payload)
                    <= candidate.offset + candidate.capacity
                ),
                None,
            )
            if donor is None:
                raise RuntimeKeywordError("STAGE keyword relocation donor vanished")
            donors.setdefault(donor.offset, []).append((relocation_offset, payload))
        final_slots[allocation.offset] = final

    for donor_offset, payloads in donors.items():
        donor = next(row for row in stage_allocations if row.offset == donor_offset)
        reclaimed_start = donor_offset + _aligned(len(donor.target))
        reclaimed_end = donor_offset + donor.capacity
        expected_relocated_pointers = {
            (
                reference.row_offset + FIELD_INDEX[reference.tag] * 4,
                relocation_offset,
            )
            for allocation in stage_allocations
            for relocation_offset, _payload, _reason in (
                (relocation_plan.get((stage_index, allocation.offset)),)
                if relocation_plan.get((stage_index, allocation.offset)) is not None
                else ()
            )
            for reference in allocation.references
        }
        for word_offset in range(0, len(current) - 3, 4):
            pointer = struct.unpack_from("<I", current, word_offset)[0]
            pointed_offset = pointer - runtime_base
            if (
                reclaimed_start <= pointed_offset < reclaimed_end
                and (word_offset, pointed_offset) not in expected_relocated_pointers
            ):
                raise RuntimeKeywordError(
                    "STAGE keyword donor slack has a live interior pointer at "
                    f"{stage_index}:0x{word_offset:X}->0x{pointed_offset:X}"
                )
        final = bytearray(final_slots[donor_offset])
        for relocation_offset, payload in payloads:
            relative = relocation_offset - donor_offset
            if any(final[relative : relative + len(payload)]):
                raise RuntimeKeywordError("STAGE keyword relocation overlaps donor text")
            final[relative : relative + len(payload)] = payload
        final_slots[donor_offset] = bytes(final)

    final_pointers: dict[int, int] = {}
    for record in stage_records:
        for tag, source_offset in zip(FIELD_TAGS, record.field_offsets):
            pointer_offset = record.row_offset + FIELD_INDEX[tag] * 4
            relocation = relocation_plan.get((stage_index, source_offset))
            final_pointers[pointer_offset] = runtime_base + (
                relocation[0] if relocation is not None else source_offset
            )

    for allocation in stage_allocations:
        start = allocation.offset
        end = start + allocation.capacity
        current_slot = current[start:end]
        final_slot = final_slots[start]
        normal_target = (
            allocation.target + bytes(allocation.capacity - len(allocation.target))
            if len(allocation.target) <= allocation.capacity
            else None
        )
        accepted = {allocation.source_slot, final_slot}
        if normal_target is not None:
            accepted.add(normal_target)
        # Relocated source allocations are preserved verbatim because other
        # translated records may now own bytes inside the old retail padding.
        if (stage_index, start) in relocation_plan:
            accepted.add(current_slot)
        if current_slot not in accepted:
            raise RuntimeKeywordError(
                f"STAGE keyword current preimage drift at "
                f"{stage_index}:0x{start:X}"
            )
    for pointer_offset, final_pointer in final_pointers.items():
        original_pointer = struct.unpack_from("<I", original, pointer_offset)[0]
        current_pointer = struct.unpack_from("<I", current, pointer_offset)[0]
        if current_pointer not in {original_pointer, final_pointer}:
            raise RuntimeKeywordError(
                f"STAGE keyword pointer drift at "
                f"{stage_index}:0x{pointer_offset:X}"
            )

    output = bytearray(current)
    allowed = set()
    for start, final in final_slots.items():
        output[start : start + len(final)] = final
        allowed.update(range(start, start + len(final)))
    for pointer_offset, pointer in final_pointers.items():
        struct.pack_into("<I", output, pointer_offset, pointer)
        allowed.update(range(pointer_offset, pointer_offset + 4))
    changed = {
        offset
        for offset, (before, after) in enumerate(zip(current, output))
        if before != after
    }
    if not changed <= allowed:
        raise RuntimeKeywordError("STAGE keyword write escaped owned ranges")

    for record in stage_records:
        for tag in FIELD_TAGS:
            pointer_offset = record.row_offset + FIELD_INDEX[tag] * 4
            pointer = struct.unpack_from("<I", output, pointer_offset)[0]
            target_offset = pointer - runtime_base
            source_allocation = next(
                allocation
                for allocation in stage_allocations
                if any(
                    ref.keyword_index == record.keyword_index and ref.tag == tag
                    and ref.row_offset == record.row_offset
                    for ref in allocation.references
                )
            )
            target = source_allocation.target
            if output[target_offset : target_offset + len(target)] != target:
                raise RuntimeKeywordError(
                    f"STAGE keyword field readback failed at "
                    f"{stage_index}:0x{pointer_offset:X}"
                )
    return bytes(output), {
        "changed_byte_count": len(changed),
    }


def apply_stage_keyword_popups(
    stage: bytes,
    original_stage: bytes,
    hb: bytes,
    authority: KeywordAuthority,
    source_table: TextTable,
    reference: Mapping[str, object],
    codec: Mapping[str, object],
    *,
    verify_only: bool = False,
) -> tuple[bytes, dict[str, object]]:
    """Rewrite or verify all 77 embedded story-popup records."""

    expected = reference.get("expected")
    if not isinstance(expected, dict):
        raise RuntimeKeywordError("runtime-keyword expected counts are missing")
    runtime_base = _number(reference.get("stage_runtime_base"), label="stage_runtime_base")
    hb_table_start = _number(reference.get("hb_table_start"), label="hb_table_start")
    hb_table_end = _number(reference.get("hb_table_end"), label="hb_table_end")
    offsets, original_decoded_by_stage, records, allocations = (
        _discover_embedded_inventory(
            original_stage,
            hb,
            authority,
            source_table,
            runtime_base=runtime_base,
            hb_table_start=hb_table_start,
            hb_table_end=hb_table_end,
            expected=expected,
        )
    )
    relocation_plan, relocation_report = _stage_relocation_plan(
        reference.get("stage_relocations"),
        allocations,
        records,
        runtime_base=runtime_base,
    )
    stage_indices = sorted({record.stage_index for record in records})
    output = bytearray(stage)
    chunk_jobs = []
    executor = None
    if not verify_only:
        if codec.get("strategy") != "rust-fit":
            raise RuntimeKeywordError("STAGE keyword codec must be rust-fit")
        executor = ThreadPoolExecutor(
            max_workers=min(4, len(stage_indices)),
            thread_name_prefix="srwz-keyword",
        )
    chunk_reports = []
    for stage_index in stage_indices:
        start, end = offsets[stage_index : stage_index + 2]
        stored = stage[start:end]
        current_decoded = decode_production(stored)
        original_decoded = original_decoded_by_stage[stage_index]
        if (
            any(stored[current_decoded.consumed :])
            or len(current_decoded.output) != len(original_decoded.output)
        ):
            raise RuntimeKeywordError(
                f"current STAGE keyword chunk decode drift at {stage_index}"
            )
        rewritten, decoded_report = _rewrite_stage_decoded(
            current_decoded.output,
            original_decoded.output,
            stage_index,
            records,
            allocations,
            relocation_plan,
            runtime_base=runtime_base,
        )
        if verify_only:
            if rewritten != current_decoded.output:
                raise RuntimeKeywordError(
                    f"STAGE keyword popup is not fully localized at {stage_index}"
                )
            chunk_reports.append(
                {
                    "stage_index": stage_index,
                    "record_count": sum(
                        record.stage_index == stage_index for record in records
                    ),
                    "encoded_size": current_decoded.consumed,
                    "slot_size": len(stored),
                    "output_headroom": len(stored) - current_decoded.consumed,
                    "changed_byte_count": 0,
                    "codec_round_trip_exact": True,
                }
            )
            continue
        future = executor.submit(
            reencode_changed_suffix,
            stored[: current_decoded.consumed],
            rewritten,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=len(stored),
            original_result=current_decoded,
        )
        chunk_jobs.append(
            (stage_index, start, end, current_decoded, rewritten, decoded_report, future)
        )

    if executor is not None:
        for (
            stage_index,
            start,
            end,
            current_decoded,
            rewritten,
            decoded_report,
            future,
        ) in chunk_jobs:
            try:
                rebuilt = future.result()
            except (RuntimeError, ValueError) as error:
                executor.shutdown(wait=True, cancel_futures=True)
                raise RuntimeKeywordError(
                    f"STAGE keyword compression failed at {stage_index}: {error}"
                ) from error
            reread = decode_production(rebuilt)
            if (
                reread.consumed != len(rebuilt)
                or reread.output != rewritten
                or reread.flags != current_decoded.flags
            ):
                raise RuntimeKeywordError(
                    f"STAGE keyword codec round-trip failed at {stage_index}"
                )
            output[start:end] = rebuilt + bytes(end - start - len(rebuilt))
            chunk_reports.append(
                {
                    "stage_index": stage_index,
                    "record_count": sum(
                        record.stage_index == stage_index for record in records
                    ),
                    "source_encoded_size": current_decoded.consumed,
                    "output_encoded_size": len(rebuilt),
                    "output_encoded_sha256": _sha256(rebuilt),
                    "slot_size": end - start,
                    "output_headroom": end - start - len(rebuilt),
                    "changed_byte_count": decoded_report["changed_byte_count"],
                    "codec_strategy": codec["strategy"],
                    "codec_round_trip_exact": True,
                }
            )
        executor.shutdown(wait=True, cancel_futures=True)

    result = bytes(output)
    if len(result) != len(stage) or read_executable_archive_offsets(
        hb,
        ExecutableOffsetSpec(
            name="HEDBDY/HB.BIN STAGE offsets",
            member="HEDBDY/HB.BIN",
            table_start=hb_table_start,
            table_end=hb_table_end,
        ),
        len(result),
    ) != offsets:
        raise RuntimeKeywordError("STAGE keyword archive layout changed")
    return result, {
        "authority": "translated DATA/MTVZKNKW.BIN KYWD fields",
        "keyword_count": len(authority.entries),
        "record_count": len(records),
        "stage_chunk_count": len(stage_indices),
        "field_reference_count": sum(
            len(allocation.references) for allocation in allocations
        ),
        "allocation_count": len(allocations),
        "shared_reference_count": sum(
            len(allocation.references) for allocation in allocations
        )
        - len(allocations),
        "relocations": relocation_report,
        "relocation_count": len(relocation_report),
        "preserved_relocated_source_allocation_count": len(relocation_report),
        "chunks": sorted(chunk_reports, key=lambda row: row["stage_index"]),
        "minimum_output_headroom": min(
            row["output_headroom"] for row in chunk_reports
        ),
        "all_four_fields_match_library": True,
        "archive_size_preserved": True,
        "hb_offsets_preserved": True,
        "codec_round_trip_exact": True,
        "verify_only": verify_only,
    }


def apply_compdata_keyword_names(
    current: bytes,
    original: bytes,
    authority: KeywordAuthority,
    source_table: TextTable,
    reference: Mapping[str, object],
    *,
    runtime_base: int,
    pointer_table_offset: int,
) -> tuple[bytes, dict[str, object]]:
    """Rewrite all 52 encyclopedia list labels in decoded COMPDATA."""

    expected = reference.get("expected")
    relocations = reference.get("compdata_relocations")
    if not isinstance(expected, dict) or not isinstance(relocations, list):
        raise RuntimeKeywordError("COMPDATA keyword configuration is malformed")
    if len(current) != len(original):
        raise RuntimeKeywordError("COMPDATA keyword decoded size drift")
    count = len(authority.entries)
    pointer_end = pointer_table_offset + count * 4
    if pointer_end > len(original):
        raise RuntimeKeywordError("COMPDATA keyword pointer table is out of bounds")
    original_pointers = struct.unpack_from(f"<{count}I", original, pointer_table_offset)
    allocations = {}
    for entry, pointer, fields in zip(
        authority.entries,
        original_pointers,
        authority.fields,
    ):
        offset = pointer - runtime_base
        if not 0 <= offset < len(original):
            raise RuntimeKeywordError(
                f"COMPDATA keyword pointer is out of bounds at {entry.entry_index}"
            )
        source = decode_text(original, offset, source_table)
        if source.text != entry.source_term:
            raise RuntimeKeywordError(
                f"COMPDATA keyword source drift at slot {entry.entry_index}"
            )
        end = _allocation_end(original, source.end)
        allocations[entry.entry_index] = {
            "offset": offset,
            "capacity": end - offset,
            "source_slot": original[offset:end],
            "target": fields["WORD"].data + b"\0",
        }
    if len(set(original_pointers)) != count:
        raise RuntimeKeywordError("COMPDATA keyword pointers are not unique")

    plan = {}
    relocation_report = []
    for index, row in enumerate(relocations):
        if not isinstance(row, dict):
            raise RuntimeKeywordError("COMPDATA keyword relocation is malformed")
        keyword_index = _number(row.get("keyword_index"), label="keyword_index")
        donor_index = _number(row.get("donor_index"), label="donor_index")
        relocation_offset = _number(
            row.get("relocation_offset"), label="relocation_offset"
        )
        source = allocations.get(keyword_index)
        donor = allocations.get(donor_index)
        expected_offset = (
            donor["offset"] + _aligned(len(donor["target"]))
            if donor is not None
            else -1
        )
        if (
            source is None
            or donor is None
            or len(source["target"]) <= source["capacity"]
            or relocation_offset != expected_offset
            or relocation_offset + len(source["target"])
            > donor["offset"] + donor["capacity"]
            or relocation_offset in {pointer - runtime_base for pointer in original_pointers}
        ):
            raise RuntimeKeywordError(
                f"COMPDATA keyword relocation contract drift at row {index}"
            )
        if keyword_index in plan:
            raise RuntimeKeywordError("duplicate COMPDATA keyword relocation")
        plan[keyword_index] = (donor_index, relocation_offset)
        relocation_report.append(
            {
                "keyword_index": keyword_index,
                "donor_index": donor_index,
                "source_capacity": source["capacity"],
                "target_size": len(source["target"]),
                "donor_capacity": donor["capacity"],
                "donor_target_size": len(donor["target"]),
                "relocation_offset": relocation_offset,
                "runtime_pointer": runtime_base + relocation_offset,
                "source_allocation_preserved": True,
            }
        )
    overflows = {
        index
        for index, allocation in allocations.items()
        if len(allocation["target"]) > allocation["capacity"]
    }
    if set(plan) != overflows:
        raise RuntimeKeywordError("COMPDATA keyword overflow coverage drift")

    final_slots = {}
    donor_payloads = {}
    final_pointers = list(original_pointers)
    for index, allocation in allocations.items():
        if index in plan:
            donor_index, relocation_offset = plan[index]
            final_slots[index] = current[
                allocation["offset"] : allocation["offset"] + allocation["capacity"]
            ]
            donor_payloads.setdefault(donor_index, []).append(
                (relocation_offset, allocation["target"])
            )
            final_pointers[index] = runtime_base + relocation_offset
        else:
            final_slots[index] = allocation["target"] + bytes(
                allocation["capacity"] - len(allocation["target"])
            )
    for donor_index, payloads in donor_payloads.items():
        donor = allocations[donor_index]
        reclaimed_start = donor["offset"] + _aligned(len(donor["target"]))
        reclaimed_end = donor["offset"] + donor["capacity"]
        expected_relocated_pointers = {
            (pointer_table_offset + keyword_index * 4, relocation_offset)
            for keyword_index, (_donor_index, relocation_offset) in plan.items()
        }
        for word_offset in range(0, len(current) - 3, 4):
            pointer = struct.unpack_from("<I", current, word_offset)[0]
            pointed_offset = pointer - runtime_base
            if (
                reclaimed_start <= pointed_offset < reclaimed_end
                and (word_offset, pointed_offset) not in expected_relocated_pointers
            ):
                raise RuntimeKeywordError(
                    "COMPDATA keyword donor slack has a live interior pointer at "
                    f"0x{word_offset:X}->0x{pointed_offset:X}"
                )
        slot = bytearray(final_slots[donor_index])
        for relocation_offset, payload in payloads:
            relative = relocation_offset - donor["offset"]
            if any(slot[relative : relative + len(payload)]):
                raise RuntimeKeywordError("COMPDATA keyword donor overlap")
            slot[relative : relative + len(payload)] = payload
        final_slots[donor_index] = bytes(slot)

    current_pointers = struct.unpack_from(f"<{count}I", current, pointer_table_offset)
    if any(
        pointer not in {original_pointers[index], final_pointers[index]}
        for index, pointer in enumerate(current_pointers)
    ):
        raise RuntimeKeywordError("COMPDATA keyword pointer preimage drift")
    for index, allocation in allocations.items():
        start = allocation["offset"]
        end = start + allocation["capacity"]
        current_slot = current[start:end]
        accepted = {allocation["source_slot"], final_slots[index]}
        if len(allocation["target"]) <= allocation["capacity"]:
            accepted.add(
                allocation["target"]
                + bytes(allocation["capacity"] - len(allocation["target"]))
            )
        if index in plan:
            accepted.add(current_slot)
        if current_slot not in accepted:
            raise RuntimeKeywordError(
                f"COMPDATA keyword current preimage drift at slot {index}"
            )

    output = bytearray(current)
    allowed = set(range(pointer_table_offset, pointer_end))
    for index, allocation in allocations.items():
        start = allocation["offset"]
        final = final_slots[index]
        output[start : start + len(final)] = final
        allowed.update(range(start, start + len(final)))
    struct.pack_into(f"<{count}I", output, pointer_table_offset, *final_pointers)
    changed = {
        offset
        for offset, (before, after) in enumerate(zip(current, output))
        if before != after
    }
    if not changed <= allowed:
        raise RuntimeKeywordError("COMPDATA keyword write escaped owned ranges")
    for index, allocation in allocations.items():
        offset = final_pointers[index] - runtime_base
        target = allocation["target"]
        if output[offset : offset + len(target)] != target:
            raise RuntimeKeywordError(
                f"COMPDATA keyword readback failed at slot {index}"
            )

    _require_expected(count, expected, "keyword_count")
    _require_expected(len(plan), expected, "compdata_relocation_count")
    return bytes(output), {
        "list_label_count": count,
        "pointer_table_offset": pointer_table_offset,
        "runtime_base": runtime_base,
        "relocations": relocation_report,
        "relocation_count": len(relocation_report),
        "changed_byte_count": len(changed),
        "all_list_labels_match_library_word": True,
        "pointer_table_reread_exact": True,
        "decoded_size_preserved": True,
    }


__all__ = [
    "KeywordAuthority",
    "RuntimeKeywordError",
    "apply_compdata_keyword_names",
    "apply_stage_keyword_popups",
    "load_keyword_authority",
]
