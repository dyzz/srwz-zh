#!/usr/bin/env python3
"""Move Chinese assignments off stock codes used by sound-select titles."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from srwz.codec import decode_production
from srwz.font import sha256_bytes
from srwz.library import SoundTitleSpanLock, verify_sound_title_source
from srwz.release_font import rendered_characters, selected_translation_tree_entries
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"
LIBRARY_CONFIG = PROJECT_ROOT / "config/library/v0.2.0.json"
SOURCE_COMPDATA = PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN"


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"JSON root is not an object: {path}")
    return document


def _write(path: Path, document: dict) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _rows_sha256(rows: list[dict]) -> str:
    return sha256_bytes(
        json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _title_codes(decoded: bytes, titles: tuple[object, ...]) -> set[int]:
    codes: set[int] = set()
    for title in titles:
        raw = decoded[title.start:title.end]
        cursor = 0
        while cursor < len(raw):
            lead = raw[cursor]
            cursor += 1
            if lead == 0:
                break
            if 0x31 <= lead <= 0x35:
                if cursor >= len(raw):
                    raise SystemExit("sound title has a truncated text tag")
                cursor += 1
                continue
            if 0x80 <= lead <= 0x9F or 0xE0 <= lead <= 0xEA:
                if cursor >= len(raw):
                    raise SystemExit("sound title has a truncated two-byte code")
                codes.add((lead << 8) | raw[cursor])
                cursor += 1
    return codes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--expand-existing",
        action="store_true",
        help=(
            "Extend the existing sound-select glyph contract when the locked "
            "title span grows; existing relocations remain frozen."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = _load(config_path)
    snapshot_path = PROJECT_ROOT / config["allocation_snapshot"]["path"]
    snapshot = _load(snapshot_path)
    existing_extensions = [
        extension
        for extension in snapshot.get("extensions", [])
        if "sound_select_title_glyph_compatibility" in extension
    ]
    if len(existing_extensions) > 1:
        raise SystemExit("multiple sound-select glyph migrations exist")
    if existing_extensions and not args.expand_existing:
        raise SystemExit(
            "sound-select title glyph migration already exists; "
            "pass --expand-existing to extend its locked title span"
        )
    if args.expand_existing and not existing_extensions:
        raise SystemExit("no sound-select glyph migration exists to expand")

    base = _load(PROJECT_ROOT / config["base_font_config"]["path"])
    table = load_text_table(
        PROJECT_ROOT / base["encoding_baseline"]["text_table"]["path"]
    )
    library = _load(LIBRARY_CONFIG)
    span_raw = library["sound_select"]["decoded_compdata"]
    span = SoundTitleSpanLock.from_mapping(span_raw)
    source_bytes = SOURCE_COMPDATA.read_bytes()
    decoded_result = decode_production(source_bytes)
    if decoded_result.consumed != len(source_bytes):
        raise SystemExit("source COMPDATA has trailing compressed bytes")
    titles = verify_sound_title_source(decoded_result.output, table, span)
    protected_codes = _title_codes(decoded_result.output, titles)
    protected_characters = {
        table.characters[code] for code in protected_codes
    }

    primary = snapshot["primary_assignments"]
    aliases = snapshot["surface_alias_assignments"]
    compatibility = snapshot["source_compatibility_assignments"]
    candidates = snapshot["remaining_allocation_candidates"]
    conflicts: list[tuple[str, int, str, dict]] = []
    for bucket, rows in (("primary", primary), ("alias", aliases)):
        for row in rows:
            code = int(row["code"], 16)
            if (
                code in protected_codes
                and row["character"] != table.characters[code]
            ):
                conflicts.append(
                    (bucket, code, table.characters[code], row)
                )
    compatibility_conflicts = [
        row
        for row in compatibility
        if int(row["code"], 16) in protected_codes
        and row["character"] != table.characters[int(row["code"], 16)]
    ]
    if compatibility_conflicts:
        raise SystemExit("sound titles collide with a compatibility assignment")
    conflicts.sort(key=lambda item: (item[1], item[0], item[3]["character"]))

    entries, _entry_scenes, _selection = selected_translation_tree_entries(
        PROJECT_ROOT,
        config,
    )
    demand = Counter(
        character
        for entry in entries.values()
        for character in rendered_characters(entry["translation"])
    )
    demand_paths: dict[str, set[str]] = {}
    for entry in entries.values():
        entry_path = str(entry["id"]).split("#", 1)[0]
        for character in rendered_characters(entry["translation"]):
            demand_paths.setdefault(character, set()).add(entry_path)

    def alias_priority(row: dict) -> tuple:
        paths = demand_paths.get(row["character"], set())
        menu_or_library = any(
            "/menu/" in path or "/library/" in path for path in paths
        )
        return (
            menu_or_library,
            demand[row["character"]],
            row["character"],
            row["code"],
        )

    freeze = _load(
        PROJECT_ROOT / config["formation_compatibility_freeze"]["path"]
    )
    frozen_characters = {
        row["character"]
        for key in ("relocations", "retired_aliases")
        for row in freeze[key]
    }
    compatibility_sensitive_characters: set[str] = set()
    for extension in snapshot.get("extensions", []):
        for key, contract in extension.items():
            if not key.endswith("compatibility") or not isinstance(contract, dict):
                continue
            for rows_key in ("relocations", "retired_aliases"):
                for row in contract.get(rows_key, []):
                    character = row.get("character")
                    if isinstance(character, str):
                        compatibility_sensitive_characters.add(character)

    moved_characters = {row[3]["character"] for row in conflicts}
    donor_aliases = sorted(
        (
            row
            for row in aliases
            if int(row["code"], 16) > 0x889E
            and int(row["code"], 16) not in protected_codes
            and row.get("source_character") not in protected_characters
            and row["character"] not in moved_characters
            and row["character"] not in frozen_characters
            and row["character"] not in compatibility_sensitive_characters
        ),
        key=alias_priority,
    )[: len(conflicts)]
    if len(donor_aliases) != len(conflicts):
        raise SystemExit("not enough safe default-width alias donor slots")

    relocations = []
    retired_aliases = []
    donor_ids = {id(row) for row in donor_aliases}
    for (bucket, old_code, source_character, row), donor in zip(
        conflicts,
        donor_aliases,
    ):
        old_code_text = row["code"]
        row.update({
            "code": donor["code"],
            "glyph_index": donor["glyph_index"],
            "mapping": (
                "sound_select_title_compatibility_relocated_primary"
                if bucket == "primary"
                else "sound_select_title_compatibility_relocated_alias"
            ),
            "source_character": donor.get("source_character"),
        })
        relocations.append({
            "character": row["character"],
            "assignment_kind": bucket,
            "from_code": old_code_text,
            "from_source_character": source_character,
            "to_code": donor["code"],
            "reused_alias_character": donor["character"],
        })
        retired_aliases.append({
            "character": donor["character"],
            "from_code": donor["code"],
            "reason": "default_width_slot_reused_for_sound_title_relocation",
        })
    aliases[:] = [row for row in aliases if id(row) not in donor_ids]

    primary_by_character = {row["character"]: row for row in primary}
    for extension in snapshot.get("extensions", []):
        for row in extension.get("assignments", []):
            current = primary_by_character.get(row.get("character"))
            if current is not None:
                row.clear()
                row.update(current)

    candidate_count_before = len(candidates)
    candidates[:] = [
        row for row in candidates if int(row["code"], 16) not in protected_codes
    ]
    reserved_candidate_count = candidate_count_before - len(candidates)
    if existing_extensions:
        target_extension = existing_extensions[0]
        contract = target_extension["sound_select_title_glyph_compatibility"]
        if not isinstance(contract, dict):
            raise SystemExit("existing sound-select glyph contract is malformed")
        existing_relocations = contract.get("relocations")
        existing_retired_aliases = contract.get("retired_aliases")
        if not isinstance(existing_relocations, list) or not isinstance(
            existing_retired_aliases, list
        ):
            raise SystemExit("existing sound-select relocation rows are malformed")
        relocations = [*existing_relocations, *relocations]
        retired_aliases = [*existing_retired_aliases, *retired_aliases]
    else:
        target_extension = {
            "assignment_count": 0,
            "allocation_assignment_count": 0,
            "reraster_existing_assignment_count": 0,
            "assignments": [],
        }
        snapshot["extensions"].append(target_extension)
    target_extension["sound_select_title_glyph_compatibility"] = {
            "source_member": {
                "path": str(SOURCE_COMPDATA.relative_to(PROJECT_ROOT)),
                "size": len(source_bytes),
                "sha256": sha256_bytes(source_bytes),
                "decoded_size": len(decoded_result.output),
                "decoded_sha256": sha256_bytes(decoded_result.output),
            },
            "decoded_span": span_raw,
            "expected_title_count": len(titles),
            "expected_unique_two_byte_code_count": len(protected_codes),
            "protected_codes": [
                f"{code:04X}" for code in sorted(protected_codes)
            ],
            "relocations": relocations,
            "retired_aliases": retired_aliases,
            "reason": (
                "The 101 sound-select track titles remain byte-exact Japanese. "
                "Chinese assignments that changed those stock code meanings "
                "move to safe default-width alias slots, and every title code "
                "is removed from the future allocation candidate pool."
            ),
        }

    historical_count = snapshot["migration"][
        "preserved_historical_primary_assignment_count"
    ]
    snapshot["primary_mapping_sha256"] = _rows_sha256(primary)
    snapshot["surface_alias_assignment_count"] = len(aliases)
    snapshot["surface_alias_mapping_sha256"] = _rows_sha256(aliases)
    snapshot["remaining_allocation_candidate_count"] = len(candidates)
    snapshot["remaining_allocation_candidates_sha256"] = _rows_sha256(
        candidates
    )
    snapshot["migration"]["preserved_historical_primary_mapping_sha256"] = (
        _rows_sha256(primary[:historical_count])
    )
    config["expected"]["surface_alias_assignment_count"] = len(aliases)
    config["expected"]["remaining_candidate_slot_count"] = len(candidates)

    print(
        "sound-select title glyph migration:",
        f"titles={len(titles)}",
        f"protected_codes={len(protected_codes)}",
        f"primary_relocations={sum(row[0] == 'primary' for row in conflicts)}",
        f"alias_relocations={sum(row[0] == 'alias' for row in conflicts)}",
        f"reserved_candidates={reserved_candidate_count}",
        f"aliases={len(aliases)}",
        f"remaining={len(candidates)}",
    )
    if not args.apply:
        print("donors:")
        for relocation in relocations:
            print(
                f"  {relocation['from_code']} "
                f"{relocation['from_source_character']} -> "
                f"{relocation['character']} -> {relocation['to_code']} "
                f"(retire {relocation['reused_alias_character']})"
            )
        raise SystemExit("dry run only; review and rerun with --apply")
    _write(snapshot_path, snapshot)
    config["allocation_snapshot"]["sha256"] = sha256_bytes(
        snapshot_path.read_bytes()
    )
    _write(config_path, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
