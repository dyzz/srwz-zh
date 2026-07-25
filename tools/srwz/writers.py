"""Fail-closed text and compressed-archive writers for SRWZ resources."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Mapping

from .codec import decode, encode
from .iso_layout import ExecutableOffsetSpec
from .summary import parse_summary
from .text import TextTable, encode_text
from .writeback import (
    PatchOperation,
    PatchPlan,
    WritebackError,
    fit_fixed_allocation,
    rebuild_aligned_archive,
    sha256_bytes,
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


def build_summary_patch_plan(
    data: bytes,
    table: TextTable,
    *,
    chunk_index: int,
    replacements: Mapping[str, str],
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
        payload = encode_text(replacements[entry_id], table)
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
) -> bytes:
    """Apply and reparse a fixed-allocation MTV_PROS text plan."""

    plan = build_summary_patch_plan(
        data,
        table,
        chunk_index=chunk_index,
        replacements=replacements,
    )
    output = plan.apply(data)
    reparsed = parse_summary(output, table, chunk_index=chunk_index)
    actual = {entry.entry_id: entry.text for entry in reparsed.entries}
    for entry_id, expected in replacements.items():
        if actual.get(entry_id) != expected:
            raise WritebackError(
                f"{entry_id} reparse mismatch after summary write"
            )
    return output


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
        source_name="SLPS_258.87",
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
    "apply_summary_replacements",
    "build_executable_offset_patch_plan",
    "build_summary_patch_plan",
    "rebuild_codec_archive",
]
