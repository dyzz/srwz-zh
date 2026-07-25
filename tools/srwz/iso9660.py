"""Small, strict ISO9660 reader used to audit reconstructed PS2 images.

This module intentionally implements only the read-only subset needed by the
SRWZ build: the primary volume descriptor and ordinary directory records.
It does not create filesystems and it does not contain game-specific code.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable


SECTOR_SIZE = 2048
PRIMARY_VOLUME_DESCRIPTOR_SECTOR = 16
VOLUME_DESCRIPTOR_ID = b"CD001"
HASH_CHUNK_SIZE = 4 * 1024 * 1024


class Iso9660Error(ValueError):
    """The image does not satisfy the narrow ISO9660 contract we require."""


@dataclass(frozen=True)
class IsoMember:
    path: str
    extent_lba: int
    size: int
    directory_record_offset: int


@dataclass(frozen=True)
class IsoImage:
    path: Path
    volume_space_size: int
    root_directory_extent_lba: int
    root_directory_size: int
    system_id: str
    volume_id: str
    application_id: str
    publisher_id: str
    members: tuple[IsoMember, ...]
    udf_volume_recognition_sequence: str | None


def _decode_ascii_field(value: bytes) -> str:
    return value.rstrip(b" \0").decode("ascii", errors="replace")


def _dual_endian_u32(data: bytes, offset: int, context: str) -> int:
    if offset + 8 > len(data):
        raise Iso9660Error(f"truncated dual-endian {context}")
    little = struct.unpack_from("<I", data, offset)[0]
    big = struct.unpack_from(">I", data, offset + 4)[0]
    if little != big:
        raise Iso9660Error(
            f"{context} endian copies disagree: {little} != {big}"
        )
    return little


def _read_exact(source: BinaryIO, offset: int, size: int, context: str) -> bytes:
    source.seek(offset)
    value = source.read(size)
    if len(value) != size:
        raise Iso9660Error(
            f"short read for {context}: {len(value)} of {size} bytes"
        )
    return value


def _normalized_identifier(raw: bytes) -> str:
    try:
        identifier = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise Iso9660Error("non-ASCII ISO9660 identifier") from exc
    if identifier.endswith(";1"):
        identifier = identifier[:-2]
    if not identifier or "/" in identifier or identifier in (".", ".."):
        raise Iso9660Error(f"unsafe ISO9660 identifier: {identifier!r}")
    return identifier


def pcsx2_v263_image_type(root_directory_size: int) -> str:
    """Mirror PCSX2 v2.6.3's ISO2048 CD/DVD classification field check."""

    return "CD" if (root_directory_size & 0xFFFF) == SECTOR_SIZE else "DVD"


def _parse_directory(
    source: BinaryIO,
    *,
    prefix: PurePosixPath,
    extent_lba: int,
    size: int,
    image_size: int,
    active_directories: set[tuple[int, int]],
    members: list[IsoMember],
) -> None:
    key = (extent_lba, size)
    if key in active_directories:
        raise Iso9660Error("recursive ISO9660 directory extent")
    active_directories.add(key)

    start = extent_lba * SECTOR_SIZE
    end = start + size
    if start < 0 or end > image_size:
        raise Iso9660Error("ISO9660 directory extent is outside the image")
    data = _read_exact(source, start, size, f"directory {prefix}")

    offset = 0
    while offset < len(data):
        record_length = data[offset]
        if record_length == 0:
            offset = ((offset // SECTOR_SIZE) + 1) * SECTOR_SIZE
            continue
        if record_length < 34 or offset + record_length > len(data):
            raise Iso9660Error("invalid ISO9660 directory record length")

        record = data[offset : offset + record_length]
        identifier_length = record[32]
        if 33 + identifier_length > len(record):
            raise Iso9660Error("truncated ISO9660 directory identifier")
        identifier_raw = record[33 : 33 + identifier_length]
        record_offset = start + offset
        offset += record_length

        if identifier_raw in (b"\x00", b"\x01"):
            continue

        identifier = _normalized_identifier(identifier_raw)
        member_path = prefix / identifier
        record_extent = _dual_endian_u32(record, 2, "extent")
        record_size = _dual_endian_u32(record, 10, "data length")
        flags = record[25]

        data_start = record_extent * SECTOR_SIZE
        data_end = data_start + record_size
        if data_start < 0 or data_end > image_size:
            raise Iso9660Error(
                f"{member_path.as_posix()} extent is outside the image"
            )

        if flags & 0x02:
            _parse_directory(
                source,
                prefix=member_path,
                extent_lba=record_extent,
                size=record_size,
                image_size=image_size,
                active_directories=active_directories,
                members=members,
            )
        else:
            members.append(
                IsoMember(
                    path=member_path.as_posix(),
                    extent_lba=record_extent,
                    size=record_size,
                    directory_record_offset=record_offset,
                )
            )

    active_directories.remove(key)


def _detect_udf_volume_recognition(
    source: BinaryIO,
    image_size: int,
) -> str | None:
    signatures = set()
    for sector in range(16, min(256, image_size // SECTOR_SIZE)):
        descriptor = _read_exact(
            source,
            sector * SECTOR_SIZE,
            SECTOR_SIZE,
            f"volume recognition sector {sector}",
        )
        signatures.add(descriptor[1:6])
    if b"NSR03" in signatures:
        return "NSR03"
    if b"NSR02" in signatures:
        return "NSR02"
    return None


def scan_iso9660(path: Path) -> IsoImage:
    path = path.resolve()
    image_size = path.stat().st_size
    with path.open("rb") as source:
        pvd = _read_exact(
            source,
            PRIMARY_VOLUME_DESCRIPTOR_SECTOR * SECTOR_SIZE,
            SECTOR_SIZE,
            "primary volume descriptor",
        )
        if pvd[0] != 1 or pvd[1:6] != VOLUME_DESCRIPTOR_ID or pvd[6] != 1:
            raise Iso9660Error("missing ISO9660 primary volume descriptor")

        volume_space_size = _dual_endian_u32(
            pvd,
            80,
            "volume space size",
        )
        if volume_space_size * SECTOR_SIZE > image_size:
            raise Iso9660Error("declared ISO9660 volume exceeds image size")

        root_length = pvd[156]
        if root_length < 34 or 156 + root_length > len(pvd):
            raise Iso9660Error("invalid root directory record")
        root = pvd[156 : 156 + root_length]
        root_extent = _dual_endian_u32(root, 2, "root extent")
        root_size = _dual_endian_u32(root, 10, "root data length")

        members: list[IsoMember] = []
        _parse_directory(
            source,
            prefix=PurePosixPath(),
            extent_lba=root_extent,
            size=root_size,
            image_size=image_size,
            active_directories=set(),
            members=members,
        )
        udf_volume_recognition_sequence = _detect_udf_volume_recognition(
            source,
            image_size,
        )

    paths = [member.path for member in members]
    if len(paths) != len(set(paths)):
        raise Iso9660Error("duplicate ISO9660 member path")

    return IsoImage(
        path=path,
        volume_space_size=volume_space_size,
        root_directory_extent_lba=root_extent,
        root_directory_size=root_size,
        system_id=_decode_ascii_field(pvd[8:40]),
        volume_id=_decode_ascii_field(pvd[40:72]),
        publisher_id=_decode_ascii_field(pvd[318:446]),
        application_id=_decode_ascii_field(pvd[574:702]),
        members=tuple(members),
        udf_volume_recognition_sequence=udf_volume_recognition_sequence,
    )


def sha256_member(image: Path, member: IsoMember) -> str:
    digest = hashlib.sha256()
    remaining = member.size
    with image.open("rb") as source:
        source.seek(member.extent_lba * SECTOR_SIZE)
        while remaining:
            chunk = source.read(min(remaining, HASH_CHUNK_SIZE))
            if not chunk:
                raise Iso9660Error(f"short read while hashing {member.path}")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def member_map(image: IsoImage) -> dict[str, IsoMember]:
    return {member.path: member for member in image.members}


def extent_order(image: IsoImage) -> tuple[str, ...]:
    return tuple(
        member.path
        for member in sorted(
            image.members,
            key=lambda item: (item.extent_lba, item.path),
        )
    )


def sort_file_lines(
    source_root: Path,
    ordered_paths: Iterable[str],
) -> tuple[str, ...]:
    paths = tuple(ordered_paths)
    weight = len(paths)
    return tuple(
        f"{(source_root / path).as_posix()}\t{weight - index}"
        for index, path in enumerate(paths)
    )


def member_manifest_sha256(
    entries: Iterable[tuple[str, int, str]],
) -> str:
    normalized = [
        {
            "path": path,
            "size": size,
            "sha256": sha256,
        }
        for path, size, sha256 in entries
    ]
    payload = json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "Iso9660Error",
    "IsoImage",
    "IsoMember",
    "SECTOR_SIZE",
    "extent_order",
    "member_map",
    "member_manifest_sha256",
    "pcsx2_v263_image_type",
    "scan_iso9660",
    "sha256_member",
    "sort_file_lines",
]
