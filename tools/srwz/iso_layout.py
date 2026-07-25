"""Pinned SLPS offset-table readers for localization-relevant archives."""

from __future__ import annotations

import struct
from dataclasses import dataclass


class IsoLayoutError(ValueError):
    """An executable offset table is truncated or invalid for its archive."""


@dataclass(frozen=True)
class ExecutableOffsetSpec:
    name: str
    member: str
    table_start: int
    table_end: int


CORE_ARCHIVE_SPECS = {
    "COMPDATA.BN": ExecutableOffsetSpec(
        name="COMPDATA.BN",
        member="DATA/COMPDATA.BN",
        table_start=0x322440,
        table_end=0x322444,
    ),
    "MTV_PROS.BIN": ExecutableOffsetSpec(
        name="MTV_PROS.BIN",
        member="DATA/MTV_PROS.BIN",
        table_start=0x32BAA0,
        table_end=0x32BADB,
    ),
    "VT1.BIN": ExecutableOffsetSpec(
        name="VT1.BIN",
        member="DATA/VT1.BIN",
        table_start=0x2FA100,
        table_end=0x2FA13B,
    ),
}


def read_executable_archive_offsets(
    executable: bytes,
    spec: ExecutableOffsetSpec,
    archive_size: int,
) -> tuple:
    """Read an inclusive-byte-end table and append archive size when needed."""

    if archive_size <= 0:
        raise IsoLayoutError("archive size must be positive")
    if not 0 <= spec.table_start < spec.table_end <= len(executable):
        raise IsoLayoutError(
            f"{spec.name} offset table is outside the executable"
        )

    offsets = tuple(
        struct.unpack_from("<I", executable, position)[0]
        for position in range(spec.table_start, spec.table_end, 4)
    )
    if not offsets:
        raise IsoLayoutError(f"{spec.name} offset table is empty")
    if offsets[0] != 0:
        raise IsoLayoutError(f"{spec.name} first offset must be zero")
    if any(
        current >= following
        for current, following in zip(offsets, offsets[1:])
    ):
        raise IsoLayoutError(f"{spec.name} offsets are not strictly increasing")
    if offsets[-1] > archive_size:
        raise IsoLayoutError(
            f"{spec.name} final offset {offsets[-1]} exceeds "
            f"archive size {archive_size}"
        )
    if offsets[-1] < archive_size:
        offsets += (archive_size,)
    return offsets


__all__ = [
    "CORE_ARCHIVE_SPECS",
    "ExecutableOffsetSpec",
    "IsoLayoutError",
    "read_executable_archive_offsets",
]
