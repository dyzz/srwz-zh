"""Inventory and localize MAPMODEL runtime terrain-name records."""

from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path
from typing import Mapping

from .codec import decode, reencode_changed_suffix
from .font import sha256_bytes
from .text import TextTable, decode_text, encode_text


class TerrainNameError(ValueError):
    """A terrain-name source, layout, or fixed-allocation invariant failed."""


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise TerrainNameError("terrain-name path must be a non-empty string")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise TerrainNameError(f"terrain-name path escapes project root: {raw}") from error
    return path


def _locked_file(
    project_root: Path,
    reference: object,
    *,
    label: str,
) -> tuple[Path, bytes]:
    if not isinstance(reference, Mapping):
        raise TerrainNameError(f"{label} lock is invalid")
    path = _project_path(project_root, reference.get("path"))
    data = path.read_bytes()
    if (
        not isinstance(reference.get("size"), int)
        or isinstance(reference.get("size"), bool)
        or len(data) != reference.get("size")
        or sha256_bytes(data) != reference.get("sha256")
    ):
        raise TerrainNameError(f"{label} lock drift")
    return path, data


def _integer(raw: object, *, label: str) -> int:
    if isinstance(raw, bool):
        raise TerrainNameError(f"{label} is not an integer")
    try:
        value = int(str(raw), 0) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError) as error:
        raise TerrainNameError(f"{label} is not an integer") from error
    if value < 0:
        raise TerrainNameError(f"{label} cannot be negative")
    return value


def _output_table(table: TextTable, overrides: Mapping[str, int]) -> TextTable:
    return TextTable(
        characters={
            **table.characters,
            **{code: character for character, code in overrides.items()},
        },
        tags=table.tags,
    )


def inventory_terrain_names(
    archive: bytes,
    offsets: tuple[int, ...],
    table: TextTable,
    *,
    first_member: int,
    last_member: int,
) -> tuple[dict, ...]:
    """Discover the fixed 0x1C records immediately before ``Frame``.

    The first field is a NUL-terminated terrain label of at most four
    double-byte glyphs.  A 12-byte gap and a 16-byte MAPMODEL header separate
    the final record from the first ``Frame`` marker.  Walking backwards from
    that structural anchor avoids scanning unrelated Japanese strings.
    """

    rows: list[dict] = []
    for member in range(first_member, last_member + 1):
        stored = archive[offsets[member] : offsets[member + 1]]
        decoded = decode(stored)
        if decoded.consumed > len(stored) or any(stored[decoded.consumed :]):
            raise TerrainNameError(f"MAPMODEL member {member} padding drift")
        frame = decoded.output.find(b"Frame\0")
        if frame < 0x1C:
            continue
        position = frame - 0x1C - 0x1C
        member_rows = []
        while position >= 0:
            cell = decoded.output[position : position + 9]
            if not cell or cell[0] == 0:
                break
            try:
                source = decode_text(cell, 0, table)
            except ValueError:
                break
            if (
                source.terminator != "nul"
                or not source.text
                or source.consumed > 9
                or source.unknown_code_count
                or any(ord(character) < 0x3000 for character in source.text)
            ):
                break
            member_rows.append(
                {
                    "member": member,
                    "decoded_offset": position,
                    "source": source.text,
                    "source_consumed": source.consumed,
                }
            )
            position -= 0x1C
        rows.extend(reversed(member_rows))
    return tuple(rows)


def _inventory_sha256(rows: tuple[dict, ...]) -> str:
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(payload)


def build_terrain_names(
    project_root: Path,
    reference: object,
    *,
    archive_payload: bytes,
    table: TextTable,
    encoding_overrides: Mapping[str, int],
) -> tuple[bytes, dict, tuple[Path, Path, Path]]:
    """Return a same-size MAPMODEL archive with every terrain label encoded."""

    if not isinstance(reference, Mapping):
        raise TerrainNameError("terrain-name configuration is invalid")
    original_slps_path, original_slps = _locked_file(
        project_root,
        reference.get("original_slps"),
        label="terrain-name original SLPS",
    )
    original_archive_path, original_archive = _locked_file(
        project_root,
        reference.get("original_archive"),
        label="terrain-name original MAPMODEL",
    )
    corpus_path, corpus_data = _locked_file(
        project_root,
        reference.get("corpus"),
        label="terrain-name corpus",
    )
    if len(archive_payload) != len(original_archive):
        raise TerrainNameError("terrain-name MAPMODEL size drift")

    archive_config = reference.get("archive")
    expected = reference.get("expected")
    codec = reference.get("codec")
    if not all(isinstance(item, Mapping) for item in (archive_config, expected, codec)):
        raise TerrainNameError("terrain-name contract is incomplete")
    table_start = _integer(
        archive_config.get("offset_table_start"), label="offset table start"
    )
    offset_count = _integer(archive_config.get("offset_count"), label="offset count")
    table_end = table_start + offset_count * 4
    table_data = original_slps[table_start:table_end]
    if (
        len(table_data) != offset_count * 4
        or sha256_bytes(table_data) != archive_config.get("offset_table_sha256")
    ):
        raise TerrainNameError("terrain-name offset table drift")
    offsets = struct.unpack(f"<{offset_count}I", table_data)
    if offsets[0] != 0 or offsets[-1] != len(original_archive):
        raise TerrainNameError("terrain-name archive coverage drift")
    first_member = _integer(archive_config.get("first_member"), label="first member")
    last_member = _integer(archive_config.get("last_member"), label="last member")
    if not 0 <= first_member <= last_member < len(offsets) - 1:
        raise TerrainNameError("terrain-name member range is invalid")

    inventory = inventory_terrain_names(
        original_archive,
        offsets,
        table,
        first_member=first_member,
        last_member=last_member,
    )
    if (
        len(inventory) != expected.get("occurrence_count")
        or _inventory_sha256(inventory) != expected.get("inventory_sha256")
    ):
        raise TerrainNameError("terrain-name inventory drift")
    corpus = json.loads(corpus_data.decode("utf-8"))
    entries = corpus.get("entries")
    if corpus.get("editorial_status") != "reviewed" or not isinstance(entries, list):
        raise TerrainNameError("terrain-name corpus policy drift")
    translations = {}
    expected_counts = {}
    for item in entries:
        if (
            not isinstance(item, dict)
            or item.get("editorial_status") != "reviewed"
            or not isinstance(item.get("source"), str)
            or not item["source"]
            or not isinstance(item.get("translation"), str)
            or not item["translation"]
            or not isinstance(item.get("occurrence_count"), int)
            or item["source"] in translations
        ):
            raise TerrainNameError("terrain-name corpus entry is invalid")
        translations[item["source"]] = item["translation"]
        expected_counts[item["source"]] = item["occurrence_count"]
    actual_counts = Counter(row["source"] for row in inventory)
    if (
        len(entries) != expected.get("unique_source_count")
        or dict(actual_counts) != expected_counts
    ):
        raise TerrainNameError("terrain-name corpus coverage drift")
    if codec.get("strategy") != "rust-fit":
        raise TerrainNameError("terrain-name codec must be rust-fit")

    rows_by_member: dict[int, list[dict]] = {}
    for row in inventory:
        rows_by_member.setdefault(row["member"], []).append(row)
    output = bytearray(archive_payload)
    output_table = _output_table(table, encoding_overrides)
    member_reports = []
    for member, rows in sorted(rows_by_member.items()):
        start, end = offsets[member : member + 2]
        source_stored = original_archive[start:end]
        current_stored = archive_payload[start:end]
        if current_stored != source_stored:
            raise TerrainNameError(
                f"terrain-name member {member} changed before text writeback"
            )
        decoded = decode(current_stored)
        modified = bytearray(decoded.output)
        for row in rows:
            position = row["decoded_offset"]
            source = decode_text(decoded.output, position, table)
            if (
                source.text != row["source"]
                or source.consumed != row["source_consumed"]
            ):
                raise TerrainNameError(
                    f"terrain-name source drift in member {member} at 0x{position:X}"
                )
            encoded = encode_text(
                translations[source.text],
                table,
                overrides=encoding_overrides,
                terminate=True,
            )
            if len(encoded) > source.consumed:
                raise TerrainNameError(
                    f"terrain-name overflow in member {member} at 0x{position:X}"
                )
            modified[position : position + source.consumed] = (
                encoded + bytes(source.consumed - len(encoded))
            )
            reread = decode_text(bytes(modified), position, output_table)
            if reread.text != translations[source.text]:
                raise TerrainNameError(
                    f"terrain-name reread mismatch in member {member} at 0x{position:X}"
                )
        encoded_stored = reencode_changed_suffix(
            current_stored[: decoded.consumed],
            bytes(modified),
            strategy="rust-fit",
            min_match_length=_integer(
                codec.get("min_match_length"), label="minimum match length"
            ),
            max_match_chain=_integer(
                codec.get("max_match_chain"), label="maximum match chain"
            ),
            lazy_matching=False,
            max_output_size=len(current_stored),
        )
        rebuilt = encoded_stored + bytes(len(current_stored) - len(encoded_stored))
        round_trip = decode(rebuilt)
        if (
            round_trip.output != bytes(modified)
            or round_trip.consumed != len(encoded_stored)
            or any(rebuilt[len(encoded_stored) :])
        ):
            raise TerrainNameError(f"terrain-name member {member} round-trip failed")
        output[start:end] = rebuilt
        member_reports.append(
            {
                "member": member,
                "occurrence_count": len(rows),
                "stored_size": len(current_stored),
                "source_encoded_size": decoded.consumed,
                "output_encoded_size": len(encoded_stored),
                "compressed_headroom": len(current_stored) - len(encoded_stored),
                "output_stored_sha256": sha256_bytes(rebuilt),
                "reread_exact": True,
            }
        )

    rebuilt_archive = bytes(output)
    if (
        len(rebuilt_archive) != len(archive_payload)
        or rebuilt_archive[: offsets[first_member]]
        != archive_payload[: offsets[first_member]]
        or rebuilt_archive[offsets[last_member + 1] :]
        != archive_payload[offsets[last_member + 1] :]
    ):
        raise TerrainNameError("terrain-name non-target archive bytes changed")
    report = {
        "unique_source_count": len(translations),
        "occurrence_count": len(inventory),
        "inventory_sha256": _inventory_sha256(inventory),
        "member_range": [first_member, last_member],
        "changed_member_count": len(member_reports),
        "changed_members": [item["member"] for item in member_reports],
        "member_reports": member_reports,
        "fixed_decoded_spans_preserved": True,
        "archive_size_preserved": True,
        "offset_table_preserved": True,
        "codec_round_trip_exact": True,
        "reread_exact": True,
    }
    return rebuilt_archive, report, (
        corpus_path,
        original_slps_path,
        original_archive_path,
    )


__all__ = [
    "TerrainNameError",
    "build_terrain_names",
    "inventory_terrain_names",
]
