"""Strict helpers for archives described by an external offset table.

This module is an independent implementation of a generic operation used by
the upstream project: split one byte stream at monotonically increasing
offsets. It intentionally contains no SRWZ compression logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence


class ArchiveLayoutError(ValueError):
    """Raised when an offset manifest or archive does not satisfy its contract."""


@dataclass(frozen=True)
class OffsetLayout:
    archive_path: str
    offsets: tuple[int, ...]
    expected_size: int | None = None
    expected_sha256: str | None = None

    @property
    def chunk_count(self) -> int:
        return len(self.offsets) - 1

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "OffsetLayout":
        archive = raw.get("archive")
        offsets = raw.get("offsets")
        expected_size = raw.get("expected_size")
        expected_sha256 = raw.get("expected_sha256")
        declared_offset_count = raw.get("offset_count")
        declared_chunk_count = raw.get("chunk_count")

        if not isinstance(archive, str) or not archive:
            raise ArchiveLayoutError("manifest archive must be a non-empty string")
        if not isinstance(offsets, list) or not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in offsets
        ):
            raise ArchiveLayoutError("manifest offsets must be a list of integers")
        if expected_size is not None and (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or expected_size < 0
        ):
            raise ArchiveLayoutError("manifest expected_size must be non-negative")
        if expected_sha256 is not None and (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            raise ArchiveLayoutError(
                "manifest expected_sha256 must be 64 lowercase hexadecimal digits"
            )
        if declared_offset_count is not None and declared_offset_count != len(offsets):
            raise ArchiveLayoutError(
                "manifest offset_count does not match the offsets list"
            )
        if declared_chunk_count is not None and declared_chunk_count != len(offsets) - 1:
            raise ArchiveLayoutError(
                "manifest chunk_count does not match the offsets list"
            )

        layout = cls(
            archive_path=archive,
            offsets=tuple(offsets),
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
        layout.validate()
        return layout

    def validate(self) -> None:
        if len(self.offsets) < 2:
            raise ArchiveLayoutError("an archive layout needs at least two offsets")
        if self.offsets[0] != 0:
            raise ArchiveLayoutError("the first archive offset must be zero")
        if any(current >= following for current, following in zip(
            self.offsets, self.offsets[1:]
        )):
            raise ArchiveLayoutError("archive offsets must be strictly increasing")
        if self.expected_size is not None and self.offsets[-1] != self.expected_size:
            raise ArchiveLayoutError(
                "the final offset must equal manifest expected_size"
            )


def load_offset_layout(path: Path) -> OffsetLayout:
    with path.open(encoding="utf-8") as source:
        raw = json.load(source)
    if not isinstance(raw, dict):
        raise ArchiveLayoutError("offset manifest root must be an object")
    return OffsetLayout.from_mapping(raw)


def slice_archive(data: bytes, layout: OffsetLayout) -> Iterator[bytes]:
    layout.validate()
    expected_size = layout.expected_size or layout.offsets[-1]
    if len(data) != expected_size:
        raise ArchiveLayoutError(
            f"archive has {len(data)} bytes, expected {expected_size}"
        )
    for start, end in zip(layout.offsets, layout.offsets[1:]):
        yield data[start:end]


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(path: Path, layout: OffsetLayout) -> None:
    actual_size = path.stat().st_size
    expected_size = layout.expected_size or layout.offsets[-1]
    if actual_size != expected_size:
        raise ArchiveLayoutError(
            f"{path} has {actual_size} bytes, expected {expected_size}"
        )
    if layout.expected_sha256 is not None:
        actual_sha256 = sha256_file(path)
        if actual_sha256 != layout.expected_sha256:
            raise ArchiveLayoutError(
                f"{path} SHA-256 is {actual_sha256}, "
                f"expected {layout.expected_sha256}"
            )


def normalize_indices(indices: Iterable[int], chunk_count: int) -> tuple[int, ...]:
    selected = tuple(sorted(set(indices)))
    if not selected:
        raise ArchiveLayoutError("select at least one archive index")
    invalid = [index for index in selected if not 0 <= index < chunk_count]
    if invalid:
        raise ArchiveLayoutError(
            f"archive indices out of range 0..{chunk_count - 1}: {invalid}"
        )
    return selected


def split_archive_file(
    source_path: Path,
    output_dir: Path,
    layout: OffsetLayout,
    indices: Sequence[int],
    *,
    force: bool = False,
) -> list[Path]:
    verify_archive(source_path, layout)
    selected = normalize_indices(indices, layout.chunk_count)
    width = max(3, len(str(layout.chunk_count - 1)))
    targets = [output_dir / f"{index:0{width}d}.bin" for index in selected]

    if not force:
        existing = [target for target in targets if target.exists()]
        if existing:
            raise FileExistsError(f"refusing to replace existing file: {existing[0]}")

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with source_path.open("rb") as source:
        for index, target in zip(selected, targets):
            start = layout.offsets[index]
            end = layout.offsets[index + 1]
            source.seek(start)
            data = source.read(end - start)
            if len(data) != end - start:
                raise ArchiveLayoutError(
                    f"short read for archive index {index}: "
                    f"{len(data)} of {end - start} bytes"
                )
            target.write_bytes(data)
            written.append(target)
    return written
