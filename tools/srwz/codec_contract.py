"""Shared result and error types for the future SRWZ codec implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


class SrwzCodecError(ValueError):
    """A malformed or unsupported SRWZ compressed stream."""

    def __init__(self, message: str, *, offset: int | None = None):
        self.offset = offset
        location = "" if offset is None else f" at input offset 0x{offset:X}"
        super().__init__(f"{message}{location}")


@dataclass(frozen=True)
class CodedInteger:
    """One decoded SRWZ variable-length integer and its source span."""

    value: int
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("coded integer value must be non-negative")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("coded integer source span must be non-empty")

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class DecodeResult:
    """Stable hand-off between the decoder and archive/text tooling."""

    output: bytes
    consumed: int
    declared_size: int
    flags: int
    header_size: int
    metadata: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.declared_size != len(self.output):
            raise ValueError(
                "declared_size must equal the number of decoded output bytes"
            )
        if self.consumed <= 0:
            raise ValueError("consumed must be positive")
        if not 0 < self.header_size <= self.consumed:
            raise ValueError("header_size must be within the consumed input span")
        if self.flags < 0:
            raise ValueError("flags must be non-negative")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
