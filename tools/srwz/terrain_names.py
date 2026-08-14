"""Inventory and localize MAPMODEL runtime terrain-name records."""

from __future__ import annotations

import json
import struct
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Mapping

from .codec import DecodeResult, decode_production as decode, reencode_changed_suffix
from .font import sha256_bytes
from .text import PreparedTextEncoder, TextTable, decode_text


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
    decoded_members: Mapping[int, DecodeResult] | None = None,
) -> tuple[dict, ...]:
    """Discover the fixed 0x1C records immediately before ``Frame``.

    The first 24 bytes of each record contain a NUL-terminated terrain label.
    Depending on the member header variant, 44, 48, 52, or 56 bytes separate
    the start of the final record from the first ``Frame`` marker.  Trying only
    those aligned structural positions and selecting the longest contiguous
    0x1C-record run avoids scanning unrelated Japanese strings while covering
    both short labels and composite names such as ``月面基地施設``.
    """

    record_size = 0x1C
    text_cell_size = 24
    final_record_frame_gaps = (44, 48, 52, 56)

    def decode_cell(payload: bytes, position: int):
        if (
            position < 0
            or position % 4
            or position + text_cell_size > len(payload)
            or payload[position] == 0
        ):
            return None
        try:
            source = decode_text(
                payload[position : position + text_cell_size],
                0,
                table,
            )
        except ValueError:
            return None
        if (
            source.terminator != "nul"
            or not source.text
            or source.consumed > text_cell_size
            or source.unknown_code_count
            or any(ord(character) < 0x3000 for character in source.text)
        ):
            return None
        return source

    rows: list[dict] = []
    for member in range(first_member, last_member + 1):
        stored = archive[offsets[member] : offsets[member + 1]]
        decoded = (
            decoded_members[member]
            if decoded_members is not None and member in decoded_members
            else decode(stored)
        )
        if decoded.consumed > len(stored) or any(stored[decoded.consumed :]):
            raise TerrainNameError(f"MAPMODEL member {member} padding drift")
        frame = decoded.output.find(b"Frame\0")
        if frame < record_size:
            continue
        candidates = []
        for gap in final_record_frame_gaps:
            position = frame - gap
            member_rows = []
            while (source := decode_cell(decoded.output, position)) is not None:
                member_rows.append(
                    {
                        "member": member,
                        "decoded_offset": position,
                        "source": source.text,
                        "source_consumed": source.consumed,
                    }
                )
                position -= record_size
            if member_rows:
                candidates.append((len(member_rows), gap, member_rows))
        if candidates:
            _count, _gap, member_rows = max(
                candidates,
                key=lambda item: (item[0], item[1]),
            )
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
    decoded_cache: dict[int, DecodeResult] | None = None,
) -> tuple[bytes, dict, tuple[Path, Path, Path, Path]]:
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
    inventory_path, inventory_data = _locked_file(
        project_root,
        reference.get("inventory"),
        label="terrain-name locked inventory",
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

    try:
        inventory_document = json.loads(inventory_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TerrainNameError("terrain-name locked inventory is invalid JSON") from error
    raw_inventory = inventory_document.get("occurrences")
    inventory = tuple(raw_inventory) if isinstance(raw_inventory, list) else ()
    inventory_expected = inventory_document.get("expected")
    inventory_source = inventory_document.get("source_archive")
    if (
        inventory_document.get("schema_version") != 1
        or inventory_document.get("status") != "reviewed_locked"
        or inventory_document.get("selection_authority")
        != "explicit_member_offsets"
        or inventory_document.get("scan_policy") != "explicit_refreeze_only"
        or not isinstance(inventory_expected, Mapping)
        or not isinstance(inventory_source, Mapping)
        or inventory_source.get("path")
        != reference.get("original_archive", {}).get("path")
        or inventory_source.get("size") != len(original_archive)
        or inventory_source.get("sha256") != sha256_bytes(original_archive)
        or len(inventory) != expected.get("occurrence_count")
        or _inventory_sha256(inventory) != expected.get("inventory_sha256")
        or len(inventory) != inventory_expected.get("occurrence_count")
        or _inventory_sha256(inventory)
        != inventory_expected.get("inventory_sha256")
        or any(
            not isinstance(row, dict)
            or set(row)
            != {"member", "decoded_offset", "source", "source_consumed"}
            or not isinstance(row.get("member"), int)
            or isinstance(row.get("member"), bool)
            or not first_member <= row["member"] <= last_member
            or not isinstance(row.get("decoded_offset"), int)
            or isinstance(row.get("decoded_offset"), bool)
            or row["decoded_offset"] < 0
            or not isinstance(row.get("source"), str)
            or not row["source"]
            or not isinstance(row.get("source_consumed"), int)
            or isinstance(row.get("source_consumed"), bool)
            or row["source_consumed"] <= 0
            for row in inventory
        )
        or list(inventory)
        != sorted(inventory, key=lambda row: (row["member"], row["decoded_offset"]))
        or len({(row["member"], row["decoded_offset"]) for row in inventory})
        != len(inventory)
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
    if (
        len(rows_by_member) != inventory_expected.get("member_count")
        or len(rows_by_member) != expected.get("changed_member_count")
    ):
        raise TerrainNameError("terrain-name locked member coverage drift")
    decoded_cache = decoded_cache if decoded_cache is not None else {}
    for member in rows_by_member:
        if member not in decoded_cache:
            start, end = offsets[member : member + 2]
            decoded_cache[member] = decode(original_archive[start:end])
    output = bytearray(archive_payload)
    output_table = _output_table(table, encoding_overrides)
    encoder = PreparedTextEncoder(table, encoding_overrides)
    member_reports = []

    def build_member(item: tuple[int, list[dict]]) -> tuple[int, int, bytes, dict]:
        member, rows = item
        start, end = offsets[member : member + 2]
        source_stored = original_archive[start:end]
        current_stored = archive_payload[start:end]
        if current_stored != source_stored:
            raise TerrainNameError(
                f"terrain-name member {member} changed before text writeback"
            )
        decoded = decoded_cache[member]
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
            encoded = encoder.encode(
                translations[source.text],
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
            original_result=decoded,
        )
        rebuilt = encoded_stored + bytes(len(current_stored) - len(encoded_stored))
        if any(rebuilt[len(encoded_stored) :]):
            raise TerrainNameError(f"terrain-name member {member} round-trip failed")
        return start, end, rebuilt, {
            "member": member,
            "occurrence_count": len(rows),
            "stored_size": len(current_stored),
            "source_encoded_size": decoded.consumed,
            "output_encoded_size": len(encoded_stored),
            "compressed_headroom": len(current_stored) - len(encoded_stored),
            "output_stored_sha256": sha256_bytes(rebuilt),
            "reread_exact": True,
        }

    ordered_members = sorted(rows_by_member.items())
    with ThreadPoolExecutor(
        max_workers=min(4, len(ordered_members)),
        thread_name_prefix="srwz-terrain",
    ) as executor:
        for start, end, rebuilt, member_report in executor.map(
            build_member,
            ordered_members,
        ):
            output[start:end] = rebuilt
            member_reports.append(member_report)

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
        "selection_authority": "locked_occurrence_inventory",
        "discovery_scan_used": False,
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
        inventory_path,
        original_slps_path,
        original_archive_path,
    )


__all__ = [
    "TerrainNameError",
    "build_terrain_names",
    "inventory_terrain_names",
]
