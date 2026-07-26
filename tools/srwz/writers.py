"""Fail-closed text and compressed-archive writers for SRWZ resources."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Mapping

from .codec import decode, encode
from .iso_layout import ExecutableOffsetSpec
from .menu import MenuParseResult
from .stage import STAGE_BASE_ADDRESS, parse_stage
from .summary import parse_summary
from .text import TextTable, decode_text, encode_text
from .writeback import (
    AllocationPool,
    PatchOperation,
    PatchPlan,
    WritebackError,
    fit_fixed_allocation,
    rebuild_aligned_archive,
    sha256_bytes,
)


def _table_with_overrides(
    table: TextTable,
    overrides: Mapping[str, int] | None,
) -> TextTable:
    if not overrides:
        return table
    return TextTable(
        characters={
            **table.characters,
            **{encoded: character for character, encoded in overrides.items()},
        },
        tags=table.tags,
    )


@dataclass(frozen=True)
class CodecArchiveRebuild:
    data: bytes
    offsets: tuple
    encoded_sizes: tuple
    padding_sizes: tuple
    decoded_sha256: tuple
    strategy: str

    @property
    def chunk_count(self) -> int:
        return len(self.encoded_sizes)

    def to_metadata(self) -> dict:
        return {
            "strategy": self.strategy,
            "chunk_count": self.chunk_count,
            "archive_size": len(self.data),
            "archive_sha256": sha256_bytes(self.data),
            "offset_count": len(self.offsets),
            "offsets_aligned_16": all(
                offset % 16 == 0 for offset in self.offsets
            ),
            "encoded_size": sum(self.encoded_sizes),
            "padding_size": sum(self.padding_sizes),
            "decoded_sha256": list(self.decoded_sha256),
        }


@dataclass(frozen=True)
class StageArenaWrite:
    data: bytes
    entry_id: str
    source_text_offset: int
    pointer_offset: int
    arena_offset: int
    arena_padding_size: int
    arena_tail_padding_size: int
    payload_size: int
    source_message_size: int
    source_decoded_size: int
    used_source_tail: bool
    used_source_allocation: bool

    @property
    def decoded_growth(self) -> int:
        return len(self.data) - self.source_decoded_size

    def to_metadata(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "source_text_offset": self.source_text_offset,
            "pointer_offset": self.pointer_offset,
            "arena_offset": self.arena_offset,
            "arena_padding_size": self.arena_padding_size,
            "arena_tail_padding_size": self.arena_tail_padding_size,
            "payload_size": self.payload_size,
            "source_message_size": self.source_message_size,
            "source_decoded_size": self.source_decoded_size,
            "output_decoded_size": len(self.data),
            "decoded_growth": self.decoded_growth,
            "pointer_address": STAGE_BASE_ADDRESS + self.arena_offset,
            "used_source_tail": self.used_source_tail,
            "used_source_allocation": self.used_source_allocation,
        }


@dataclass(frozen=True)
class TextPoolAllocation:
    entry_id: str
    pool_offset: int
    pointer_address: int
    payload_size: int
    direct_pointer_offsets: tuple
    embedded_hi_offsets: tuple
    embedded_lo_offsets: tuple

    def to_metadata(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "pool_offset": self.pool_offset,
            "pointer_address": self.pointer_address,
            "payload_size": self.payload_size,
            "direct_pointer_offsets": list(self.direct_pointer_offsets),
            "embedded_hi_offsets": list(self.embedded_hi_offsets),
            "embedded_lo_offsets": list(self.embedded_lo_offsets),
        }


@dataclass(frozen=True)
class TextPoolWrite:
    data: bytes
    source_size: int
    source_sha256: str
    pool_start: int
    pool_end: int
    pool_used: int
    alignment: int
    allocations: tuple
    patch_plan: PatchPlan

    def to_metadata(self) -> dict:
        return {
            "source_size": self.source_size,
            "source_sha256": self.source_sha256,
            "output_size": len(self.data),
            "output_sha256": sha256_bytes(self.data),
            "pool_start": self.pool_start,
            "pool_end": self.pool_end,
            "pool_capacity": self.pool_end - self.pool_start,
            "pool_used": self.pool_used,
            "alignment": self.alignment,
            "allocation_count": len(self.allocations),
            "allocations": [
                allocation.to_metadata()
                for allocation in self.allocations
            ],
            "patch_plan": self.patch_plan.to_metadata(),
        }


def _split_mips_address(address: int) -> tuple:
    if not 0 <= address <= 0xFFFFFFFF:
        raise WritebackError("text pool pointer exceeds 32 bits")
    return ((address + 0x8000) >> 16) & 0xFFFF, address & 0xFFFF


def relocate_menu_texts_to_pool(
    data: bytes,
    parsed: MenuParseResult,
    table: TextTable,
    *,
    replacements: Mapping[str, str],
    pool_start: int,
    pool_end: int,
    overrides: Mapping[str, int] | None = None,
    alignment: int = 2,
    source_name: str | None = None,
) -> TextPoolWrite:
    """Relocate SLPS/COMPDATA menu strings into a verified empty pool.

    Every selected record is encoded once, then all ordinary 32-bit pointers
    and all recorded MIPS HI/LO immediate pairs are redirected to the new
    allocation. Inline ``T`` records are deliberately rejected because they
    have no pointer semantics that can safely be changed by this writer.
    """

    if parsed.source_size != len(data):
        raise WritebackError(
            f"{parsed.friendly_name} parse/source size mismatch"
        )
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("text pool alignment must be a power of two")
    if not 0 <= pool_start <= pool_end <= len(data):
        raise WritebackError("text pool is outside source")
    if any(data[pool_start:pool_end]):
        raise WritebackError("text pool is not zero-filled")

    entries = {entry.entry_id: entry for entry in parsed.entries}
    unknown = sorted(set(replacements) - set(entries))
    if unknown:
        raise WritebackError(
            f"unknown menu replacement ids: {unknown!r}"
        )

    pool = AllocationPool(
        f"{parsed.friendly_name} text",
        pool_start,
        pool_end,
    )
    operations = []
    allocations = []
    output_table = _table_with_overrides(table, overrides)

    for entry_id in sorted(replacements):
        entry = entries[entry_id]
        if not entry.pointer_offsets and not entry.embedded_hi:
            raise WritebackError(
                f"{entry_id} has no relocatable pointer references"
            )
        if len(entry.embedded_hi) != len(entry.embedded_lo):
            raise WritebackError(
                f"{entry_id} has unmatched MIPS HI/LO references"
            )
        if len(entry.pointer_offsets) > len(entry.target_offsets):
            raise WritebackError(
                f"{entry_id} pointer provenance is incomplete"
            )

        source_addresses = {
            parsed.base_offset + target
            for target in entry.target_offsets
        }
        for target_offset in entry.target_offsets:
            source = decode_text(data, target_offset, table)
            if source.text != entry.text:
                raise WritebackError(
                    f"{entry_id} source text preimage mismatch"
                )

        direct_sites = []
        for pointer_offset, target_offset in zip(
            entry.pointer_offsets,
            entry.target_offsets,
        ):
            if not 0 <= pointer_offset <= len(data) - 4:
                raise WritebackError(
                    f"{entry_id} direct pointer is outside source"
                )
            before = data[pointer_offset:pointer_offset + 4]
            actual_address = struct.unpack("<I", before)[0]
            expected_address = parsed.base_offset + target_offset
            if actual_address != expected_address:
                raise WritebackError(
                    f"{entry_id} direct pointer preimage mismatch"
                )
            direct_sites.append((pointer_offset, before))

        embedded_sites = []
        for hi_address, lo_address in zip(
            entry.embedded_hi,
            entry.embedded_lo,
        ):
            hi_offset = hi_address - parsed.base_offset
            lo_offset = lo_address - parsed.base_offset
            if not (
                0 <= hi_offset <= len(data) - 2
                and 0 <= lo_offset <= len(data) - 2
            ):
                raise WritebackError(
                    f"{entry_id} embedded pointer is outside source"
                )
            before_hi = data[hi_offset:hi_offset + 2]
            before_lo = data[lo_offset:lo_offset + 2]
            old_hi = struct.unpack("<H", before_hi)[0]
            old_lo = struct.unpack("<h", before_lo)[0]
            actual_address = (old_hi << 16) + old_lo
            if actual_address not in source_addresses:
                raise WritebackError(
                    f"{entry_id} embedded pointer preimage mismatch"
                )
            embedded_sites.append(
                (hi_offset, lo_offset, before_hi, before_lo)
            )

        payload = encode_text(
            replacements[entry_id],
            table,
            overrides=overrides,
            terminate=True,
        )
        allocation_offset = pool.allocate(
            len(payload),
            alignment=alignment,
        )
        pointer_address = parsed.base_offset + allocation_offset
        new_hi, new_lo = _split_mips_address(pointer_address)
        operations.append(
            PatchOperation(
                owner=f"{entry_id} pool allocation",
                offset=allocation_offset,
                before=data[
                    allocation_offset:allocation_offset + len(payload)
                ],
                after=payload,
            )
        )
        for pointer_offset, before in direct_sites:
            operations.append(
                PatchOperation(
                    owner=f"{entry_id} direct pointer",
                    offset=pointer_offset,
                    before=before,
                    after=struct.pack("<I", pointer_address),
                )
            )
        for hi_offset, lo_offset, before_hi, before_lo in embedded_sites:
            operations.extend(
                (
                    PatchOperation(
                        owner=f"{entry_id} MIPS HI",
                        offset=hi_offset,
                        before=before_hi,
                        after=struct.pack("<H", new_hi),
                    ),
                    PatchOperation(
                        owner=f"{entry_id} MIPS LO",
                        offset=lo_offset,
                        before=before_lo,
                        after=struct.pack("<H", new_lo),
                    ),
                )
            )

        allocations.append(
            TextPoolAllocation(
                entry_id=entry_id,
                pool_offset=allocation_offset,
                pointer_address=pointer_address,
                payload_size=len(payload),
                direct_pointer_offsets=tuple(
                    site[0] for site in direct_sites
                ),
                embedded_hi_offsets=tuple(
                    site[0] for site in embedded_sites
                ),
                embedded_lo_offsets=tuple(
                    site[1] for site in embedded_sites
                ),
            )
        )

    plan = PatchPlan(
        source_name=source_name or parsed.friendly_name,
        source_size=len(data),
        source_sha256=sha256_bytes(data),
        operations=tuple(operations),
    )
    output = plan.apply(data)

    for allocation in allocations:
        replacement = replacements[allocation.entry_id]
        decoded = decode_text(
            output,
            allocation.pool_offset,
            output_table,
        )
        if decoded.text != replacement:
            raise WritebackError(
                f"{allocation.entry_id} pool text reparse mismatch"
            )
        for pointer_offset in allocation.direct_pointer_offsets:
            actual = struct.unpack_from("<I", output, pointer_offset)[0]
            if actual != allocation.pointer_address:
                raise WritebackError(
                    f"{allocation.entry_id} direct pointer reread mismatch"
                )
        for hi_offset, lo_offset in zip(
            allocation.embedded_hi_offsets,
            allocation.embedded_lo_offsets,
        ):
            hi = struct.unpack_from("<H", output, hi_offset)[0]
            lo = struct.unpack_from("<h", output, lo_offset)[0]
            if (hi << 16) + lo != allocation.pointer_address:
                raise WritebackError(
                    f"{allocation.entry_id} MIPS pointer reread mismatch"
                )

    return TextPoolWrite(
        data=output,
        source_size=len(data),
        source_sha256=sha256_bytes(data),
        pool_start=pool_start,
        pool_end=pool_end,
        pool_used=pool.cursor - pool_start,
        alignment=alignment,
        allocations=tuple(allocations),
        patch_plan=plan,
    )


def build_summary_patch_plan(
    data: bytes,
    table: TextTable,
    *,
    chunk_index: int,
    replacements: Mapping[str, str],
    overrides: Mapping[str, int] | None = None,
) -> PatchPlan:
    """Plan fixed-allocation MTV_PROS text writes without truncation."""

    parsed = parse_summary(data, table, chunk_index=chunk_index)
    entries = {entry.entry_id: entry for entry in parsed.entries}
    unknown = sorted(set(replacements) - set(entries))
    if unknown:
        raise WritebackError(
            f"unknown summary replacement ids: {unknown!r}"
        )

    operations = []
    for entry_id in sorted(replacements):
        entry = entries[entry_id]
        payload = encode_text(
            replacements[entry_id],
            table,
            overrides=overrides,
        )
        after = fit_fixed_allocation(
            payload,
            entry.allocated_length,
            terminator=(
                b"\x00" if entry.terminator == "nul" else b""
            ),
        )
        before = data[
            entry.text_offset:entry.text_offset + entry.allocated_length
        ]
        operations.append(
            PatchOperation(
                owner=entry_id,
                offset=entry.text_offset,
                before=before,
                after=after,
            )
        )

    return PatchPlan(
        source_name=f"MTV_PROS decoded chunk {chunk_index:02d}",
        source_size=len(data),
        source_sha256=sha256_bytes(data),
        operations=tuple(operations),
    )


def apply_summary_replacements(
    data: bytes,
    table: TextTable,
    *,
    chunk_index: int,
    replacements: Mapping[str, str],
    overrides: Mapping[str, int] | None = None,
) -> bytes:
    """Apply and reparse a fixed-allocation MTV_PROS text plan."""

    plan = build_summary_patch_plan(
        data,
        table,
        chunk_index=chunk_index,
        replacements=replacements,
        overrides=overrides,
    )
    output = plan.apply(data)
    reparsed = parse_summary(
        output,
        _table_with_overrides(table, overrides),
        chunk_index=chunk_index,
    )
    actual = {entry.entry_id: entry.text for entry in reparsed.entries}
    for entry_id, expected in replacements.items():
        if actual.get(entry_id) != expected:
            raise WritebackError(
                f"{entry_id} reparse mismatch after summary write"
            )
    return output


def relocate_stage_text_to_arena(
    data: bytes,
    table: TextTable,
    *,
    stage_index: int,
    function_address: int,
    entry_id: str,
    replacement: str,
    overrides: Mapping[str, int] | None = None,
    alignment: int = 16,
    base_address: int = STAGE_BASE_ADDRESS,
) -> StageArenaWrite:
    """Relocate one direct-pointer STAGE string to an aligned arena.

    Dialogue records point to a combined ``speaker\\nmessage\\0`` string.
    Preserve the speaker prefix byte-exact and encode only the replacement
    message. Conditions contain no speaker prefix. Prefer aligned, contiguous
    zero slack following the source allocation; otherwise use a verified
    zero-filled source tail or append an aligned arena.
    """

    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("stage arena alignment must be a power of two")
    parsed = parse_stage(
        data,
        table,
        stage_index=stage_index,
        function_address=function_address,
        base_address=base_address,
    )
    matches = tuple(
        entry for entry in parsed.entries if entry.entry_id == entry_id
    )
    if len(matches) != 1:
        raise WritebackError(
            f"stage entry {entry_id!r} has {len(matches)} matches"
        )
    entry = matches[0]
    if entry.pointer_offset is None or entry.text_offset is None:
        raise WritebackError(
            f"stage entry {entry_id!r} has no relocatable direct pointer"
        )
    pointer_offset = entry.pointer_offset
    text_offset = entry.text_offset
    expected_address = base_address + text_offset
    actual_address = struct.unpack_from("<I", data, pointer_offset)[0]
    if actual_address != expected_address:
        raise WritebackError(
            f"stage entry {entry_id!r} pointer preimage mismatch"
        )

    if entry.kind == "dialogue":
        speaker = decode_text(
            data,
            text_offset,
            table,
            stop_at_newline=True,
        )
        if speaker.terminator == "newline":
            message = decode_text(data, speaker.end, table)
            prefix = data[text_offset:speaker.end]
        else:
            message = speaker
            prefix = b""
    else:
        message = decode_text(data, text_offset, table)
        prefix = b""
    if message.text != entry.text:
        raise WritebackError(
            f"stage entry {entry_id!r} parser/source text mismatch"
        )

    encoded_message = encode_text(
        replacement,
        table,
        overrides=overrides,
        terminate=True,
    )
    payload = prefix + encoded_message
    source_payload_size = len(prefix) + message.consumed
    source_payload_end = text_offset + source_payload_size
    source_slack_end = source_payload_end
    while (
        source_slack_end < len(data)
        and data[source_slack_end] == 0
    ):
        source_slack_end += 1
    used_source_allocation = (
        text_offset % alignment == 0
        and text_offset + len(payload) <= source_slack_end
    )

    last_nonzero = max(
        (index for index, value in enumerate(data) if value),
        default=-1,
    )
    source_tail_start = last_nonzero + 1
    source_tail_arena = (
        source_tail_start + alignment - 1
    ) & ~(alignment - 1)
    used_source_tail = (
        not used_source_allocation
        and source_tail_arena + len(payload) <= len(data)
        and not any(data[source_tail_start:])
    )
    arena_offset = (
        text_offset
        if used_source_allocation
        else (
            source_tail_arena
            if used_source_tail
            else (len(data) + alignment - 1) & ~(alignment - 1)
        )
    )
    arena_padding = (
        0
        if used_source_allocation
        else (
            arena_offset - source_tail_start
            if used_source_tail
            else arena_offset - len(data)
        )
    )
    pointer_address = base_address + arena_offset
    if pointer_address > 0xFFFFFFFF:
        raise WritebackError("stage arena pointer exceeds 32 bits")

    output = bytearray(data)
    if used_source_allocation:
        output[arena_offset:arena_offset + len(payload)] = payload
        arena_tail_padding = (
            source_slack_end - arena_offset - len(payload)
        )
    elif used_source_tail:
        output[arena_offset:arena_offset + len(payload)] = payload
        arena_tail_padding = len(output) - arena_offset - len(payload)
    else:
        output.extend(bytes(arena_padding))
        output.extend(payload)
        arena_tail_padding = (-len(output)) & (alignment - 1)
        output.extend(bytes(arena_tail_padding))
    struct.pack_into("<I", output, pointer_offset, pointer_address)
    rebuilt = bytes(output)

    expected = bytearray(data)
    if used_source_allocation or used_source_tail:
        expected[arena_offset:arena_offset + len(payload)] = payload
    else:
        expected.extend(bytes(arena_padding))
        expected.extend(payload)
        expected.extend(bytes(arena_tail_padding))
    struct.pack_into("<I", expected, pointer_offset, pointer_address)
    if rebuilt != bytes(expected):
        raise WritebackError(
            f"stage entry {entry_id!r} changed outside its pointer and arena"
        )
    reparsed = parse_stage(
        rebuilt,
        _table_with_overrides(table, overrides),
        stage_index=stage_index,
        function_address=function_address,
        base_address=base_address,
    )
    rematches = tuple(
        item for item in reparsed.entries if item.entry_id == entry_id
    )
    if (
        len(rematches) != 1
        or rematches[0].text != replacement
        or rematches[0].text_offset != arena_offset
    ):
        raise WritebackError(
            f"stage entry {entry_id!r} reparse mismatch after relocation"
        )
    return StageArenaWrite(
        data=rebuilt,
        entry_id=entry_id,
        source_text_offset=text_offset,
        pointer_offset=pointer_offset,
        arena_offset=arena_offset,
        arena_padding_size=arena_padding,
        arena_tail_padding_size=arena_tail_padding,
        payload_size=len(payload),
        source_message_size=message.consumed,
        source_decoded_size=len(data),
        used_source_tail=used_source_tail,
        used_source_allocation=used_source_allocation,
    )


def rebuild_codec_archive(
    decoded_chunks: Iterable[bytes],
    *,
    strategy: str = "greedy",
    alignment: int = 16,
) -> CodecArchiveRebuild:
    """Encode, align and independently decode every rebuilt archive chunk."""

    sources = tuple(bytes(chunk) for chunk in decoded_chunks)
    encoded = tuple(encode(chunk, strategy=strategy) for chunk in sources)
    archive, offsets = rebuild_aligned_archive(
        encoded,
        alignment=alignment,
    )
    encoded_sizes = tuple(len(chunk) for chunk in encoded)
    padding_sizes = tuple(
        offsets[index + 1] - offsets[index] - encoded_sizes[index]
        for index in range(len(encoded))
    )

    decoded_hashes = []
    for index, expected in enumerate(sources):
        start = offsets[index]
        end = offsets[index + 1]
        rebuilt_slice = archive[start:end]
        result = decode(rebuilt_slice)
        if result.consumed != encoded_sizes[index]:
            raise WritebackError(
                f"rebuilt chunk {index} consumed {result.consumed}, "
                f"expected {encoded_sizes[index]}"
            )
        if result.output != expected:
            raise WritebackError(
                f"rebuilt chunk {index} decoded content mismatch"
            )
        trailing = rebuilt_slice[result.consumed:]
        if any(trailing):
            raise WritebackError(
                f"rebuilt chunk {index} has nonzero archive padding"
            )
        decoded_hashes.append(sha256_bytes(result.output))

    return CodecArchiveRebuild(
        data=archive,
        offsets=offsets,
        encoded_sizes=encoded_sizes,
        padding_sizes=padding_sizes,
        decoded_sha256=tuple(decoded_hashes),
        strategy=strategy,
    )


def build_executable_offset_patch_plan(
    executable: bytes,
    spec: ExecutableOffsetSpec,
    archive_offsets: Iterable[int],
    *,
    source_name: str = "SLPS_258.87",
) -> PatchPlan:
    """Plan an exact in-memory update of one SLPS archive offset table.

    Observed tables use both shapes: some contain every chunk start and rely
    on the external archive size, while MTV_PROS stores the terminal archive
    size in the table as well.  Preserve the source table's entry count.
    """

    offsets = tuple(archive_offsets)
    positions = tuple(range(spec.table_start, spec.table_end, 4))
    if len(positions) == len(offsets):
        stored_offsets = offsets
    elif len(positions) + 1 == len(offsets):
        stored_offsets = offsets[:-1]
    else:
        raise WritebackError(
            f"{spec.name} table has {len(positions)} entries but rebuilt "
            f"layout has {len(offsets)} offsets"
        )
    if offsets[0] != 0 or any(
        current >= following
        for current, following in zip(offsets, offsets[1:])
    ):
        raise WritebackError(f"{spec.name} rebuilt offsets are invalid")
    if spec.table_start < 0 or spec.table_start + len(positions) * 4 > len(
        executable
    ):
        raise WritebackError(f"{spec.name} SLPS table is outside source")

    before = executable[
        spec.table_start:spec.table_start + len(positions) * 4
    ]
    after = b"".join(
        struct.pack("<I", offset) for offset in stored_offsets
    )
    return PatchPlan(
        source_name=source_name,
        source_size=len(executable),
        source_sha256=sha256_bytes(executable),
        operations=(
            PatchOperation(
                owner=f"{spec.name} offset table",
                offset=spec.table_start,
                before=before,
                after=after,
            ),
        ),
    )


__all__ = [
    "CodecArchiveRebuild",
    "StageArenaWrite",
    "TextPoolAllocation",
    "TextPoolWrite",
    "apply_summary_replacements",
    "build_executable_offset_patch_plan",
    "build_summary_patch_plan",
    "rebuild_codec_archive",
    "relocate_menu_texts_to_pool",
    "relocate_stage_text_to_arena",
]
