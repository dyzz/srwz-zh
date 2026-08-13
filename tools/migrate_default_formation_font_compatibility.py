#!/usr/bin/env python3
"""Protect every stock formation-name glyph from Chinese font reuse."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from srwz.font import glyph_index_for_code, read_extended_glyph_table, sha256_bytes
from srwz.release_font import rendered_characters, selected_translation_tree_entries
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"
DEFAULT_INVENTORY = PROJECT_ROOT / "config/stage-default-formation-inventory.json"


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate colliding Chinese mappings away from every original "
            "code used by the locked stock formation-name inventory."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    inventory_path = args.inventory.resolve()
    config = _load(config_path)
    snapshot_path = PROJECT_ROOT / config["allocation_snapshot"]["path"]
    snapshot = _load(snapshot_path)
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes.decode("utf-8"))
    names = inventory.get("sources")
    expected_name_count = inventory.get("expected", {}).get(
        "unique_source_count"
    )
    if (
        not isinstance(names, list)
        or len(names) != expected_name_count
        or len(set(names)) != len(names)
    ):
        raise SystemExit("stock formation-name inventory is malformed")
    existing_contracts = [
        extension["legacy_save_formation_compatibility"]
        for extension in snapshot.get("extensions", [])
        if "legacy_save_formation_compatibility" in extension
    ]
    if len(existing_contracts) != 1:
        raise SystemExit("legacy formation compatibility contract is missing")
    existing_observed_names = list(
        existing_contracts[0].get("observed_legacy_names", [])
    )

    base_path = PROJECT_ROOT / config["base_font_config"]["path"]
    base = _load(base_path)
    table_path = PROJECT_ROOT / base["encoding_baseline"]["text_table"]["path"]
    table = load_text_table(table_path)
    extended = read_extended_glyph_table(
        (PROJECT_ROOT / "work/disc/SLPS_258.87").read_bytes()
    )
    protected_names = list(dict.fromkeys([*names, *existing_observed_names]))
    protected_characters = set("".join(protected_names))
    inventory_characters = set("".join(names))
    missing_table_characters = sorted(
        protected_characters - set(table.inverse_characters)
    )
    if missing_table_characters:
        raise SystemExit(
            "stock formation characters are absent from the text table: "
            + "".join(missing_table_characters)
        )
    protected_codes = {
        table.inverse_characters[character]: character
        for character in protected_characters
    }

    primary = snapshot["primary_assignments"]
    aliases = snapshot["surface_alias_assignments"]
    compatibility = snapshot["source_compatibility_assignments"]
    candidates = snapshot["remaining_allocation_candidates"]
    active_by_code = {
        int(row["code"], 16): (bucket, row)
        for bucket, rows in (
            ("primary", primary),
            ("alias", aliases),
            ("compatibility", compatibility),
        )
        for row in rows
    }
    primary_conflicts = []
    alias_conflicts = []
    for code, source_character in sorted(protected_codes.items()):
        active = active_by_code.get(code)
        if active is None or active[1]["character"] == source_character:
            continue
        (primary_conflicts if active[0] == "primary" else alias_conflicts).append(
            (code, source_character, active[1])
        )
    unexpected = [
        row for row in (*primary_conflicts, *alias_conflicts) if row[2].get("mapping")
        == "legacy_save_formation_source_compatibility"
    ]
    if unexpected:
        raise SystemExit("existing source-compatibility mapping is inconsistent")

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

    moved_characters = {row[2]["character"] for row in primary_conflicts}
    donor_aliases = sorted(
        (
            row
            for row in aliases
            if int(row["code"], 16) not in protected_codes
            and row.get("source_character") not in protected_characters
            and row["character"] not in moved_characters
        ),
        key=alias_priority,
    )[: len(primary_conflicts)]
    if len(donor_aliases) != len(primary_conflicts):
        raise SystemExit("not enough default-width alias slots for safe relocation")

    relocations = []
    retired_aliases = []
    donor_characters = {row["character"] for row in donor_aliases}
    restored_alias_characters = {row[2]["character"] for row in alias_conflicts}
    for (old_code, _source_character, row), donor in zip(
        primary_conflicts,
        donor_aliases,
    ):
        old_code_text = row["code"]
        row.update(
            {
                "code": donor["code"],
                "glyph_index": donor["glyph_index"],
                "mapping": "default_formation_compatibility_relocated_primary",
                "source_character": donor.get("source_character"),
            }
        )
        relocations.append(
            {
                "character": row["character"],
                "from_code": old_code_text,
                "to_code": donor["code"],
                "reused_alias_character": donor["character"],
            }
        )
        retired_aliases.append(
            {
                "character": donor["character"],
                "from_code": donor["code"],
                "reason": "default_width_slot_reused_for_primary_relocation",
            }
        )

    aliases[:] = [
        row
        for row in aliases
        if row["character"] not in donor_characters | restored_alias_characters
    ]
    for old_code, source_character, row in alias_conflicts:
        retired_aliases.append(
            {
                "character": row["character"],
                "from_code": f"{old_code:04X}",
                "reason": "original_default_formation_glyph_restored",
            }
        )

    primary_by_character = {row["character"]: row for row in primary}
    for extension in snapshot.get("extensions", []):
        for row in extension.get("assignments", []):
            current = primary_by_character.get(row.get("character"))
            if current is not None:
                row.clear()
                row.update(current)

    compatibility_by_character = {
        row["character"]: row for row in compatibility
    }
    for code, source_character, _row in (*primary_conflicts, *alias_conflicts):
        compatibility_by_character[source_character] = {
            "character": source_character,
            "code": f"{code:04X}",
            "glyph_index": glyph_index_for_code(code, extended),
            "mapping": "legacy_save_formation_source_compatibility",
            "source_character": source_character,
            "reason": (
                "Preserve the original CP932 glyph used by a stock formation "
                "name that may already be stored on a legacy memory card."
            ),
        }
    compatibility[:] = sorted(
        compatibility_by_character.values(),
        key=lambda row: (int(row["code"], 16), row["character"]),
    )
    protected_candidate_rows = [
        row for row in candidates if int(row["code"], 16) in protected_codes
    ]
    candidates[:] = [
        row for row in candidates if int(row["code"], 16) not in protected_codes
    ]

    contract = existing_contracts[0]
    existing_relocations = list(contract.get("relocations", []))
    existing_retired_aliases = list(contract.get("retired_aliases", []))
    existing_reserved = set(
        contract.get("reserved_unoccupied_source_characters", "")
    )
    preserved = {
        row["character"]
        for row in compatibility
        if row.get("mapping") == "legacy_save_formation_source_compatibility"
    }
    reserved = existing_reserved | {
        row["source_character"]
        for row in protected_candidate_rows
        if row.get("source_character") in protected_characters
    }
    contract.clear()
    contract.update(
        {
            "source_inventory": {
                "path": str(inventory_path.relative_to(PROJECT_ROOT)),
                "size": len(inventory_bytes),
                "sha256": sha256_bytes(inventory_bytes),
                "source_count": len(names),
            },
            "observed_legacy_names": existing_observed_names,
            "protected_source_character_count": len(inventory_characters),
            "preserved_source_characters": "".join(sorted(preserved)),
            "reserved_unoccupied_source_characters": "".join(sorted(reserved)),
            "relocations": [*existing_relocations, *relocations],
            "retired_aliases": [*existing_retired_aliases, *retired_aliases],
            "reason": (
                "Preserve every original glyph used by all locked stock "
                "formation names that may already be stored on legacy memory cards."
            ),
        }
    )

    historical_count = snapshot["migration"][
        "preserved_historical_primary_assignment_count"
    ]
    snapshot["primary_mapping_sha256"] = _rows_sha256(primary)
    snapshot["surface_alias_assignment_count"] = len(aliases)
    snapshot["surface_alias_mapping_sha256"] = _rows_sha256(aliases)
    snapshot["source_compatibility_assignment_count"] = len(compatibility)
    snapshot["source_compatibility_mapping_sha256"] = _rows_sha256(
        compatibility
    )
    snapshot["remaining_allocation_candidate_count"] = len(candidates)
    snapshot["remaining_allocation_candidates_sha256"] = _rows_sha256(
        candidates
    )
    snapshot["migration"]["preserved_historical_primary_mapping_sha256"] = (
        _rows_sha256(primary[:historical_count])
    )
    snapshot["migration"]["reason"] = (
        "The active release build consumes this self-contained snapshot. All "
        f"{len(inventory_characters)} original glyphs used by the {len(names)} "
        "locked stock formation names, plus confirmed legacy-only name glyphs, "
        "are protected from Chinese font reuse."
    )

    config["expected"]["surface_alias_assignment_count"] = len(aliases)
    config["expected"]["source_compatibility_assignment_count"] = len(
        compatibility
    )
    config["expected"]["remaining_candidate_slot_count"] = len(candidates)
    print(
        "default formation font migration:",
        f"names={len(names)}",
        f"characters={len(inventory_characters)}",
        f"characters_with_legacy_extras={len(protected_characters)}",
        f"primary_relocations={len(primary_conflicts)}",
        f"retired_aliases={len(retired_aliases)}",
        f"reserved_candidates={len(protected_candidate_rows)}",
        f"remaining={len(candidates)}",
    )
    if not args.apply:
        raise SystemExit("dry run only; review and rerun with --apply")
    _write(snapshot_path, snapshot)
    config["allocation_snapshot"]["sha256"] = sha256_bytes(
        snapshot_path.read_bytes()
    )
    _write(config_path, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
