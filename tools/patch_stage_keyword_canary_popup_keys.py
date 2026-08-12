#!/usr/bin/env python3
"""Patch the female Stage 1 glossary popup keys in the isolated canary ISO.

This intentionally touches only three fixed KYWD slots in the dedicated
keyword-link canary.  It does not read or write the concurrently edited
LIBRARY translation corpus.  The original Japanese source term is required
before a slot is changed, while an already localized slot is accepted so the
operation is idempotent.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

from srwz.codec import decode_production as decode, reencode_changed_suffix
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.library import (
    build_runtime_zkn_decoded_chunk,
    parse_runtime_zkn_decoded_chunk,
    parse_zkn_decoded_chunk,
)
from srwz.text import (
    TextTable,
    load_text_table,
    original_fullwidth_ascii_overrides,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = (
    PROJECT_ROOT
    / "build/iso/keyword-link-canary/srwz-zh-keyword-link-stage001.iso"
)
DEFAULT_ASSIGNMENTS = (
    PROJECT_ROOT / "config/encoding/zh-release-font-assignments.json"
)
DEFAULT_TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
KEYWORD_OFFSET_SPEC = ExecutableOffsetSpec(
    name="MTVZKNKW.BIN",
    member="DATA/MTVZKNKW.BIN",
    table_start=0x32B980,
    table_end=0x32BA4F,
)
STAGE001_POPUP_KEYS = (
    (7, "ティターンズ", "提坦斯"),
    (8, "エゥーゴ", "奥古"),
    (51, "グローリー・スター", "荣耀之星"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--assignments", type=Path, default=DEFAULT_ASSIGNMENTS)
    parser.add_argument("--text-table", type=Path, default=DEFAULT_TEXT_TABLE)
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _code(value: object, *, label: str) -> int:
    if not isinstance(value, str):
        raise SystemExit(f"{label} code is not a hexadecimal string")
    try:
        result = int(value, 16)
    except ValueError as exc:
        raise SystemExit(f"{label} code is not hexadecimal") from exc
    if not 0 <= result <= 0xFFFF:
        raise SystemExit(f"{label} code is outside two bytes")
    return result


def _tables_and_overrides(
    text_table_path: Path,
    assignments_path: Path,
) -> tuple[TextTable, TextTable, dict[str, int]]:
    source_table = load_text_table(text_table_path)
    document = json.loads(assignments_path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise SystemExit("unsupported release-font assignment schema")

    characters = dict(source_table.characters)
    overrides: dict[str, int] = {}
    used_codes: dict[int, str] = {}
    for group in ("primary_assignments", "surface_alias_assignments"):
        rows = document.get(group)
        if not isinstance(rows, list):
            raise SystemExit(f"font assignment group is malformed: {group}")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise SystemExit(f"font assignment row is malformed: {group}/{index}")
            character = row.get("character")
            if not isinstance(character, str) or len(character) != 1:
                raise SystemExit(
                    f"font assignment character is malformed: {group}/{index}"
                )
            code = _code(row.get("code"), label=f"{group}/{index}")
            previous = used_codes.setdefault(code, character)
            if previous != character:
                raise SystemExit(f"font assignment code collision at 0x{code:04X}")
            characters[code] = character
            # Surface aliases deliberately win, matching the production
            # LIBRARY writer's renderer-safe encoding policy.
            overrides[character] = code
    overrides.update(original_fullwidth_ascii_overrides(source_table))
    overrides[" "] = ord(" ")
    return (
        source_table,
        TextTable(characters=characters, tags=source_table.tags),
        overrides,
    )


def _read_member(iso_path: Path, member_name: str) -> tuple[object, bytes]:
    member = member_map(scan_iso9660(iso_path)).get(member_name)
    if member is None:
        raise SystemExit(f"keyword canary ISO has no {member_name}")
    with iso_path.open("rb") as source:
        source.seek(member.extent_lba * SECTOR_SIZE)
        payload = source.read(member.size)
    if len(payload) != member.size:
        raise SystemExit(f"short ISO member read: {member_name}")
    return member, payload


def main() -> None:
    args = parse_args()
    iso_path = args.iso.resolve()
    if not iso_path.is_file():
        raise SystemExit(f"keyword canary ISO does not exist: {iso_path}")
    source_table, runtime_table, overrides = _tables_and_overrides(
        args.text_table.resolve(),
        args.assignments.resolve(),
    )
    executable_member, executable = _read_member(iso_path, "SLPS_258.87")
    del executable_member
    archive_member, archive = _read_member(iso_path, "DATA/MTVZKNKW.BIN")
    offsets = read_executable_archive_offsets(
        executable,
        KEYWORD_OFFSET_SPEC,
        len(archive),
    )
    output = bytearray(archive)
    changes = []

    for entry_index, source_word, expected_word in STAGE001_POPUP_KEYS:
        start, end = offsets[entry_index : entry_index + 2]
        stored = archive[start:end]
        decoded = decode(stored)
        if any(stored[decoded.consumed :]):
            raise SystemExit(f"KYWD {entry_index:03d} has nonzero trailing bytes")
        runtime_document = parse_runtime_zkn_decoded_chunk(
            decoded.output,
            runtime_table,
        )
        current_word = runtime_document.field("WORD").text
        if current_word == expected_word:
            changes.append(
                {
                    "entry_index": entry_index,
                    "source_word": source_word,
                    "word": expected_word,
                    "status": "already_localized",
                    "slot_size": len(stored),
                    "encoded_size": decoded.consumed,
                }
            )
            continue

        source_document = parse_zkn_decoded_chunk(decoded.output)
        if source_document.kind != "KYWD":
            raise SystemExit(f"ZKAN {entry_index:03d} is not a KYWD entry")
        if source_document.field("WORD").text != source_word:
            raise SystemExit(
                f"KYWD {entry_index:03d} preimage drift: "
                f"{source_document.field('WORD').text!r}"
            )
        # Only WORD participates in the runtime lookup key.  Re-encoding the
        # unchanged Japanese SRCE/DSCR/DSC2 fields through the localized font
        # map could reinterpret reused glyph slots, so preserve those fields'
        # original bytes verbatim.
        word_only_document = replace(
            source_document,
            fields=tuple(
                field
                if field.tag == "WORD" or field.text is None
                else replace(field, text=None)
                for field in source_document.fields
            ),
        )
        rebuilt = build_runtime_zkn_decoded_chunk(
            word_only_document,
            source_table,
            {"WORD": expected_word},
            overrides=overrides,
            alignment=16,
        )
        encoded = reencode_changed_suffix(
            stored,
            rebuilt,
            strategy="rust-maximum",
            min_match_length=2,
            max_match_chain=16384,
            lazy_matching=False,
            max_output_size=len(stored),
            original_result=decoded,
        )
        localized_slot = encoded + bytes(len(stored) - len(encoded))
        reread = decode(localized_slot)
        if any(localized_slot[reread.consumed :]):
            raise SystemExit(f"KYWD {entry_index:03d} output padding is not zero")
        localized_document = parse_runtime_zkn_decoded_chunk(
            reread.output,
            runtime_table,
        )
        if localized_document.field("WORD").text != expected_word:
            raise SystemExit(f"KYWD {entry_index:03d} localized WORD reread failed")
        source_fields = {field.tag: field.data for field in source_document.fields}
        localized_fields = {
            field.tag: field.data for field in localized_document.fields
        }
        for tag in source_fields.keys() - {"WORD"}:
            if localized_fields[tag] != source_fields[tag]:
                raise SystemExit(
                    f"KYWD {entry_index:03d} unexpectedly changed {tag} bytes"
                )
        output[start:end] = localized_slot
        changes.append(
            {
                "entry_index": entry_index,
                "source_word": source_word,
                "word": expected_word,
                "status": "localized",
                "slot_size": len(stored),
                "source_encoded_size": decoded.consumed,
                "output_encoded_size": len(encoded),
                "headroom": len(stored) - len(encoded),
            }
        )

    before_sha256 = _sha256_file(iso_path)
    changed = bytes(output) != archive
    if changed:
        member_offset = archive_member.extent_lba * SECTOR_SIZE
        with iso_path.open("r+b") as target:
            target.seek(member_offset)
            if target.read(archive_member.size) != archive:
                raise SystemExit("keyword canary archive changed during patch preparation")
            target.seek(member_offset)
            target.write(output)
            target.flush()
            os.fsync(target.fileno())
    after_sha256 = _sha256_file(iso_path)
    print(
        json.dumps(
            {
                "schema_version": 1,
                "iso": str(iso_path.relative_to(PROJECT_ROOT)),
                "changed": changed,
                "before_sha256": before_sha256,
                "after_sha256": after_sha256,
                "popup_keys": changes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
