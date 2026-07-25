"""Fail-closed writeback planning primitives for future SRWZ file writers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Optional


class WritebackError(ValueError):
    """A write plan violates source identity, bounds, or ownership."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PatchOperation:
    owner: str
    offset: int
    before: bytes
    after: bytes

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError("patch operation owner must be non-empty")
        if self.offset < 0:
            raise ValueError("patch operation offset must be non-negative")
        if len(self.before) != len(self.after):
            raise ValueError("patch operations must be size-preserving")
        if not self.before:
            raise ValueError("patch operation must not be empty")

    @property
    def end(self) -> int:
        return self.offset + len(self.before)

    def to_metadata(self) -> dict:
        return {
            "owner": self.owner,
            "offset": self.offset,
            "end": self.end,
            "size": len(self.before),
            "before_sha256": sha256_bytes(self.before),
            "after_sha256": sha256_bytes(self.after),
        }


@dataclass(frozen=True)
class PatchPlan:
    source_name: str
    source_size: int
    source_sha256: str
    operations: tuple

    def __post_init__(self) -> None:
        if not self.source_name:
            raise ValueError("patch plan source name must be non-empty")
        if self.source_size < 0:
            raise ValueError("patch plan source size must be non-negative")
        if len(self.source_sha256) != 64:
            raise ValueError("patch plan source SHA-256 is malformed")
        operations = tuple(self.operations)
        object.__setattr__(self, "operations", operations)
        previous = None
        for operation in sorted(operations, key=lambda item: item.offset):
            if operation.end > self.source_size:
                raise WritebackError(
                    f"{operation.owner} write extends outside "
                    f"{self.source_name}"
                )
            if previous is not None and operation.offset < previous.end:
                raise WritebackError(
                    f"overlapping owners {previous.owner!r} and "
                    f"{operation.owner!r}"
                )
            previous = operation

    def verify_source(self, source: bytes) -> None:
        if len(source) != self.source_size:
            raise WritebackError(
                f"{self.source_name} size mismatch: expected "
                f"{self.source_size}, got {len(source)}"
            )
        actual_sha256 = sha256_bytes(source)
        if actual_sha256 != self.source_sha256:
            raise WritebackError(
                f"{self.source_name} SHA-256 mismatch: expected "
                f"{self.source_sha256}, got {actual_sha256}"
            )
        for operation in self.operations:
            actual = source[operation.offset:operation.end]
            if actual != operation.before:
                raise WritebackError(
                    f"{operation.owner} preimage mismatch at "
                    f"0x{operation.offset:X}"
                )

    def apply(self, source: bytes) -> bytes:
        self.verify_source(source)
        output = bytearray(source)
        for operation in self.operations:
            output[operation.offset:operation.end] = operation.after
        return bytes(output)

    def to_metadata(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_size": self.source_size,
            "source_sha256": self.source_sha256,
            "operation_count": len(self.operations),
            "operations": [
                operation.to_metadata() for operation in self.operations
            ],
        }


@dataclass
class AllocationPool:
    owner: str
    start: int
    end: int
    cursor: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError("allocation pool owner must be non-empty")
        if not 0 <= self.start <= self.end:
            raise ValueError("allocation pool range is invalid")
        if self.cursor is None:
            self.cursor = self.start
        if not self.start <= self.cursor <= self.end:
            raise ValueError("allocation pool cursor is outside its range")

    @property
    def remaining(self) -> int:
        return self.end - self.cursor

    def allocate(self, size: int, *, alignment: int = 1) -> int:
        if size < 0:
            raise ValueError("allocation size must be non-negative")
        if alignment <= 0 or alignment & (alignment - 1):
            raise ValueError("alignment must be a positive power of two")
        position = (self.cursor + alignment - 1) & ~(alignment - 1)
        allocation_end = position + size
        if allocation_end > self.end:
            raise WritebackError(
                f"{self.owner} pool overflow: need {size} bytes with "
                f"{self.remaining} remaining"
            )
        self.cursor = allocation_end
        return position


def fit_fixed_allocation(
    payload: bytes,
    capacity: int,
    *,
    terminator: bytes = b"\x00",
    padding_byte: int = 0,
) -> bytes:
    """Return a strictly bounded fixed-size payload or fail on overflow."""

    if capacity < 0:
        raise ValueError("fixed allocation capacity must be non-negative")
    if not 0 <= padding_byte <= 0xFF:
        raise ValueError("padding byte must fit one byte")
    final = payload + terminator
    if len(final) > capacity:
        raise WritebackError(
            f"fixed allocation overflow: need {len(final)}, "
            f"capacity {capacity}"
        )
    return final + bytes([padding_byte]) * (capacity - len(final))


def rebuild_aligned_archive(
    chunks: Iterable[bytes],
    *,
    alignment: int = 16,
    pad_byte: int = 0,
) -> tuple:
    """Join chunks with deterministic alignment and return all offsets."""

    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("alignment must be a positive power of two")
    if not 0 <= pad_byte <= 0xFF:
        raise ValueError("pad byte must fit one byte")

    output = bytearray()
    offsets = []
    for chunk in chunks:
        offsets.append(len(output))
        output.extend(chunk)
        padding = (-len(output)) & (alignment - 1)
        output.extend(bytes([pad_byte]) * padding)
    offsets.append(len(output))
    return bytes(output), tuple(offsets)


__all__ = [
    "AllocationPool",
    "PatchOperation",
    "PatchPlan",
    "WritebackError",
    "fit_fixed_allocation",
    "rebuild_aligned_archive",
    "sha256_bytes",
]
