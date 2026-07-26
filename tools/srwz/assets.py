"""Pure asset-inventory rules shared by the SRWZ command-line tools."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping

from .codec import decode
from .codec_contract import SrwzCodecError
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .tim2 import Tim2File, scan_tim2


class AssetInventoryError(ValueError):
    """Asset bytes or configuration do not satisfy the inventory contract."""


@dataclass(frozen=True)
class AssetArchiveSpec:
    name: str
    member: str
    table_start: int
    table_end: int
    storage: str


@dataclass(frozen=True)
class AssetInventoryConfig:
    schema_version: int
    upstream_commit: str
    provenance_source_path: str
    reuse_scope: str
    executable_member: str
    archives: tuple[AssetArchiveSpec, ...]
    direct_members: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "AssetInventoryConfig":
        raw = _require_mapping(raw, "asset inventory config")
        expected_keys = {
            "schema_version",
            "provenance",
            "executable_member",
            "archives",
            "direct_members",
        }
        _require_exact_keys(raw, expected_keys, "asset inventory config")
        if raw["schema_version"] != 1 or isinstance(
            raw["schema_version"],
            bool,
        ):
            raise AssetInventoryError("asset inventory schema_version must be 1")

        provenance = _require_mapping(raw["provenance"], "provenance")
        _require_exact_keys(
            provenance,
            {"upstream_commit", "source_path", "reuse_scope"},
            "provenance",
        )
        upstream_commit = _require_string(
            provenance["upstream_commit"],
            "provenance.upstream_commit",
        )
        if len(upstream_commit) != 40 or any(
            character not in "0123456789abcdef"
            for character in upstream_commit
        ):
            raise AssetInventoryError(
                "provenance.upstream_commit must be 40 lowercase hex digits"
            )
        provenance_source_path = _require_relative_path(
            provenance["source_path"],
            "provenance.source_path",
        )
        reuse_scope = _require_string(
            provenance["reuse_scope"],
            "provenance.reuse_scope",
        )
        executable_member = _require_relative_path(
            raw["executable_member"],
            "executable_member",
        )

        archives_raw = raw["archives"]
        if not isinstance(archives_raw, list) or not archives_raw:
            raise AssetInventoryError("archives must be a non-empty list")
        archives = []
        for index, value in enumerate(archives_raw):
            item = _require_mapping(value, f"archives[{index}]")
            _require_exact_keys(
                item,
                {
                    "name",
                    "member",
                    "table_start",
                    "table_end",
                    "storage",
                },
                f"archives[{index}]",
            )
            name = _require_string(item["name"], f"archives[{index}].name")
            member = _require_relative_path(
                item["member"],
                f"archives[{index}].member",
            )
            table_start = parse_integer(
                item["table_start"],
                f"archives[{index}].table_start",
            )
            table_end = parse_integer(
                item["table_end"],
                f"archives[{index}].table_end",
            )
            if not 0 <= table_start < table_end:
                raise AssetInventoryError(
                    f"archives[{index}] table range must be positive and ordered"
                )
            storage = _require_string(
                item["storage"],
                f"archives[{index}].storage",
            )
            if storage not in ("raw", "srwz_stream"):
                raise AssetInventoryError(
                    f"archives[{index}] has unsupported storage {storage!r}"
                )
            archives.append(
                AssetArchiveSpec(
                    name=name,
                    member=member,
                    table_start=table_start,
                    table_end=table_end,
                    storage=storage,
                )
            )

        archive_names = [item.name for item in archives]
        archive_members = [item.member for item in archives]
        _require_unique(archive_names, "archive names")
        _require_unique(archive_members, "archive members")

        direct_raw = raw["direct_members"]
        if not isinstance(direct_raw, list):
            raise AssetInventoryError("direct_members must be a list")
        direct_members = tuple(
            _require_relative_path(value, f"direct_members[{index}]")
            for index, value in enumerate(direct_raw)
        )
        _require_unique(direct_members, "direct members")
        overlap = sorted(set(archive_members) & set(direct_members))
        if overlap:
            raise AssetInventoryError(
                f"archive and direct members overlap: {overlap}"
            )
        if executable_member in set(archive_members) | set(direct_members):
            raise AssetInventoryError(
                "executable_member must not also be an asset member"
            )

        return cls(
            schema_version=1,
            upstream_commit=upstream_commit,
            provenance_source_path=provenance_source_path,
            reuse_scope=reuse_scope,
            executable_member=executable_member,
            archives=tuple(archives),
            direct_members=direct_members,
        )

    def archive_for_member(self, member: str) -> AssetArchiveSpec | None:
        return next(
            (item for item in self.archives if item.member == member),
            None,
        )

    @property
    def required_members(self) -> frozenset[str]:
        return frozenset(
            {
                self.executable_member,
                *(item.member for item in self.archives),
                *self.direct_members,
            }
        )


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AssetInventoryError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise AssetInventoryError(f"{field} keys must be strings")
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise AssetInventoryError(
            f"{field} keys differ: missing={missing}, unknown={unknown}"
        )


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AssetInventoryError(f"{field} must be a non-empty string")
    return value


def _require_relative_path(value: object, field: str) -> str:
    text = _require_string(value, field)
    if "\\" in text:
        raise AssetInventoryError(f"{field} must use forward slashes")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise AssetInventoryError(f"{field} must be a safe relative path")
    return path.as_posix()


def _require_unique(values, field: str) -> None:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise AssetInventoryError(
            f"{field} contain duplicates: {sorted(duplicates)}"
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise AssetInventoryError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise AssetInventoryError(
                f"{field} is not an integer: {value!r}"
            ) from error
    raise AssetInventoryError(f"{field} must be an integer")


def picture_descriptor(record: Tim2File, picture_index: int) -> dict:
    picture = record.pictures[picture_index]
    return {
        "record_offset": record.offset,
        "record_size": record.size,
        "picture_index": picture_index,
        "width": picture.width,
        "height": picture.height,
        "bits_per_pixel": picture.bits_per_pixel,
        "image_size": picture.image_size,
        "clut_color_count": picture.clut_color_count,
        "clut_bits_per_color": picture.clut_bits_per_color,
        "uses_shared_clut": picture.uses_shared_clut,
        "mipmap_count": picture.mipmap_count,
    }


def summarize_records(records: tuple[Tim2File, ...]) -> dict:
    pictures = [
        picture_descriptor(record, picture_index)
        for record in records
        for picture_index in range(len(record.pictures))
    ]
    format_counts = Counter(
        (
            picture["width"],
            picture["height"],
            picture["bits_per_pixel"],
            picture["clut_color_count"],
        )
        for picture in pictures
    )
    return {
        "tim2_record_count": len(records),
        "picture_count": len(pictures),
        "formats": [
            {
                "width": key[0],
                "height": key[1],
                "bits_per_pixel": key[2],
                "clut_color_count": key[3],
                "count": count,
            }
            for key, count in sorted(format_counts.items())
        ],
        "pictures": pictures,
    }


def raw_magic_count(data: bytes) -> int:
    count = 0
    position = 0
    while True:
        position = data.find(b"TIM2", position)
        if position < 0:
            return count
        count += 1
        position += 4


def classify_stream_tail(chunk: bytes, consumed: int) -> str:
    if consumed == len(chunk):
        return "complete"
    tail = chunk[consumed:]
    return "zero_padding" if not any(tail) else "nonzero_tail"


def inventory_archive(
    executable: bytes,
    archive: bytes,
    spec: AssetArchiveSpec,
) -> dict:
    layout_spec = ExecutableOffsetSpec(
        name=spec.name,
        member=spec.member,
        table_start=spec.table_start,
        table_end=spec.table_end,
    )
    offsets = read_executable_archive_offsets(
        executable,
        layout_spec,
        len(archive),
    )

    chunks = []
    total_decoded_size = 0
    decode_status_counts = Counter()
    total_records = 0
    total_pictures = 0
    total_raw_magic = 0
    all_formats = Counter()

    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        chunk = archive[start:end]
        chunk_result = {
            "index": index,
            "offset": start,
            "stored_size": len(chunk),
        }
        if spec.storage == "raw":
            payload = chunk
            chunk_result["decode_status"] = "not_compressed"
        else:
            try:
                decoded = decode(chunk)
            except SrwzCodecError as error:
                chunk_result["decode_status"] = "decode_error"
                chunk_result["decode_error"] = str(error)
                decode_status_counts["decode_error"] += 1
                chunks.append(chunk_result)
                continue
            payload = decoded.output
            tail_status = classify_stream_tail(chunk, decoded.consumed)
            chunk_result.update(
                {
                    "decode_status": tail_status,
                    "decoded_size": len(payload),
                    "compressed_stream_size": decoded.consumed,
                    "stored_tail_size": len(chunk) - decoded.consumed,
                }
            )
            total_decoded_size += len(payload)

        decode_status_counts[chunk_result["decode_status"]] += 1
        records = scan_tim2(payload)
        summary = summarize_records(records)
        magic_count = raw_magic_count(payload)
        chunk_result.update(
            {
                "raw_tim2_magic_count": magic_count,
                "tim2_record_count": summary["tim2_record_count"],
                "picture_count": summary["picture_count"],
                "tim2_pictures": summary["pictures"],
            }
        )
        total_records += summary["tim2_record_count"]
        total_pictures += summary["picture_count"]
        total_raw_magic += magic_count
        for item in summary["formats"]:
            all_formats[
                (
                    item["width"],
                    item["height"],
                    item["bits_per_pixel"],
                    item["clut_color_count"],
                )
            ] += item["count"]
        chunks.append(chunk_result)

    return {
        "name": spec.name,
        "member": spec.member,
        "storage": spec.storage,
        "size": len(archive),
        "sha256": sha256_bytes(archive),
        "table_start": spec.table_start,
        "table_end": spec.table_end,
        "chunk_count": len(offsets) - 1,
        "decode_status_counts": dict(sorted(decode_status_counts.items())),
        "decoded_size": (
            total_decoded_size if spec.storage == "srwz_stream" else None
        ),
        "raw_tim2_magic_count": total_raw_magic,
        "tim2_record_count": total_records,
        "picture_count": total_pictures,
        "formats": [
            {
                "width": key[0],
                "height": key[1],
                "bits_per_pixel": key[2],
                "clut_color_count": key[3],
                "count": count,
            }
            for key, count in sorted(all_formats.items())
        ],
        "chunks": chunks,
    }


def changed_ranges(original: bytes, reference: bytes) -> list[tuple[int, int]]:
    if len(original) != len(reference):
        raise AssetInventoryError(
            f"reference size {len(reference)} != original {len(original)}"
        )
    ranges = []
    start = None
    for offset, (left, right) in enumerate(zip(original, reference)):
        if left != right and start is None:
            start = offset
        elif left == right and start is not None:
            ranges.append((start, offset))
            start = None
    if start is not None:
        ranges.append((start, len(original)))
    return ranges


def compare_kvm_reference(
    original: bytes,
    archive_entry: dict,
    reference: bytes,
) -> dict:
    ranges = changed_ranges(original, reference)
    offsets = [chunk["offset"] for chunk in archive_entry["chunks"]]
    offsets.append(len(original))
    changed_chunks = [
        index
        for index, (start, end) in enumerate(zip(offsets, offsets[1:]))
        if original[start:end] != reference[start:end]
    ]
    return {
        "size": len(reference),
        "sha256": sha256_bytes(reference),
        "changed_byte_count": sum(
            left != right for left, right in zip(original, reference)
        ),
        "changed_range_count": len(ranges),
        "first_changed_offset": ranges[0][0] if ranges else None,
        "last_changed_end": ranges[-1][1] if ranges else None,
        "changed_chunk_indices": changed_chunks,
    }


def compact_asset_manifest(report: dict, recorded_on: str) -> dict:
    def compact_asset(item: dict) -> dict:
        keys = (
            "name",
            "member",
            "storage",
            "size",
            "sha256",
            "chunk_count",
            "decode_status_counts",
            "decoded_size",
            "raw_tim2_magic_count",
            "tim2_record_count",
            "picture_count",
            "formats",
        )
        return {key: item[key] for key in keys if key in item}

    def compact_direct(item: dict) -> dict:
        keys = (
            "member",
            "size",
            "sha256",
            "raw_tim2_magic_count",
            "tim2_record_count",
            "picture_count",
            "formats",
        )
        return {key: item[key] for key in keys}

    return {
        "schema_version": report["schema_version"],
        "recorded_on": recorded_on,
        "scope": report["scope"],
        "source": report["source"],
        "config_sha256": report["config_sha256"],
        "archive_count": report["archive_count"],
        "direct_member_count": report["direct_member_count"],
        "totals": report["totals"],
        "archives": [compact_asset(item) for item in report["archives"]],
        "direct_members": [
            compact_direct(item) for item in report["direct_members"]
        ],
        "reference_kvm_comparison": report["reference_kvm_comparison"],
    }


__all__ = [
    "AssetArchiveSpec",
    "AssetInventoryConfig",
    "AssetInventoryError",
    "changed_ranges",
    "classify_stream_tail",
    "compact_asset_manifest",
    "compare_kvm_reference",
    "inventory_archive",
    "parse_integer",
    "picture_descriptor",
    "raw_magic_count",
    "sha256_bytes",
    "summarize_records",
]
