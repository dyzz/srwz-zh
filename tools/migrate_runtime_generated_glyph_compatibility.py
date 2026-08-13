#!/usr/bin/env python3
"""Reserve stock glyphs emitted by runtime-only text construction paths."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from srwz.font import sha256_bytes
from srwz.release_font import rendered_characters, selected_translation_tree_entries
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = _load(config_path)
    snapshot_path = PROJECT_ROOT / config["allocation_snapshot"]["path"]
    snapshot = _load(snapshot_path)
    contracts = [
        extension["runtime_generated_glyph_compatibility"]
        for extension in snapshot.get("extensions", [])
        if "runtime_generated_glyph_compatibility" in extension
    ]
    if len(contracts) != 1:
        raise SystemExit("runtime-generated glyph contract is missing")
    contract = contracts[0]
    literal_outputs = [
        {
            "source_character": "「",
            "code": "8175",
            "producer": "keyword_popup_title_wrapper",
            "role": "opening_quote",
        },
        {
            "source_character": "」",
            "code": "8176",
            "producer": "keyword_popup_title_wrapper",
            "role": "closing_quote",
        },
    ]
    existing_literals = contract.get("literal_outputs", [])
    if existing_literals not in ([], literal_outputs):
        raise SystemExit("runtime literal-output contract is inconsistent")

    base = _load(PROJECT_ROOT / config["base_font_config"]["path"])
    table = load_text_table(
        PROJECT_ROOT / base["encoding_baseline"]["text_table"]["path"]
    )
    protected_outputs = [*contract["conversion_outputs"], *literal_outputs]
    protected_codes = {int(row["code"], 16) for row in protected_outputs}
    protected_characters = {
        row["source_character"] for row in protected_outputs
    }
    for row in literal_outputs:
        code = int(row["code"], 16)
        if table.characters.get(code) != row["source_character"]:
            raise SystemExit("runtime literal-output text-table drift")

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
    for row in literal_outputs:
        code = int(row["code"], 16)
        active = active_by_code.get(code)
        if active is None or active[1]["character"] == row["source_character"]:
            continue
        if active[0] not in {"primary", "alias"}:
            raise SystemExit("runtime literal output has an incompatible owner")
        (primary_conflicts if active[0] == "primary" else alias_conflicts).append(
            (code, row["source_character"], active[1])
        )

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
        raise SystemExit("not enough default-width aliases for runtime relocation")

    existing_relocations = list(contract.get("relocations", []))
    existing_keys = {
        (row["character"], row["from_code"]) for row in existing_relocations
    }
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
                "mapping": "runtime_generated_glyph_compatibility_relocated_primary",
                "source_character": donor.get("source_character"),
            }
        )
        relocation = {
            "character": row["character"],
            "from_code": old_code_text,
            "to_code": donor["code"],
            "reused_alias_character": donor["character"],
        }
        if (row["character"], old_code_text) not in existing_keys:
            relocations.append(relocation)
        retired_aliases.append(
            {
                "character": donor["character"],
                "from_code": donor["code"],
                "reason": "default_width_slot_reused_for_runtime_glyph_relocation",
            }
        )

    aliases[:] = [
        row
        for row in aliases
        if row["character"] not in donor_characters | restored_alias_characters
    ]
    for old_code, _source_character, row in alias_conflicts:
        retired_aliases.append(
            {
                "character": row["character"],
                "from_code": f"{old_code:04X}",
                "reason": "runtime_generated_stock_glyph_restored",
            }
        )

    primary_by_character = {row["character"]: row for row in primary}
    for extension in snapshot.get("extensions", []):
        for row in extension.get("assignments", []):
            current = primary_by_character.get(row.get("character"))
            if current is not None:
                row.clear()
                row.update(current)

    # Runtime-emitted literal slots are deliberately absent from every active
    # assignment bucket.  That makes the font builder leave their retail VT1
    # glyph bytes untouched instead of re-rasterizing the same Unicode
    # character with the Chinese release font.
    compatibility[:] = sorted(
        (
            row
            for row in compatibility
            if int(row["code"], 16) not in protected_codes
        ),
        key=lambda row: (int(row["code"], 16), row["character"]),
    )
    candidates[:] = [
        row for row in candidates if int(row["code"], 16) not in protected_codes
    ]

    contract["literal_outputs"] = literal_outputs
    contract["relocations"] = [*existing_relocations, *relocations]
    contract["retired_aliases"] = [
        *contract.get("retired_aliases", []),
        *retired_aliases,
    ]
    contract["reason"] = (
        "The executable can synthesize punctuation codes after text loading, "
        "including direct keyword-popup title wrappers. Static corpus scans "
        "cannot prove these stock glyph slots unused, so colliding Chinese "
        "assignments move to safe default-width aliases."
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
    config["expected"]["surface_alias_assignment_count"] = len(aliases)
    config["expected"]["source_compatibility_assignment_count"] = len(
        compatibility
    )
    config["expected"]["remaining_candidate_slot_count"] = len(candidates)

    print(
        "runtime glyph migration:",
        f"primary_relocations={len(primary_conflicts)}",
        f"alias_restorations={len(alias_conflicts)}",
        f"protected_outputs={len(protected_outputs)}",
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
