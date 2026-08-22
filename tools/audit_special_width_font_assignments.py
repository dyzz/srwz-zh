#!/usr/bin/env python3
"""Inventory every demanded release glyph using a renderer-special code."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

try:
    from srwz.font import (
        RAW_STANDARD_TRAILS,
        is_cjk_unified_ideograph,
        is_conditional_width_code,
        sha256_bytes,
    )
    from srwz.release_font import (
        rendered_characters,
        selected_translation_tree_entries,
    )
    from srwz.release_font_policy import (
        DEFAULT_WIDTH_CLASS,
        allocation_width_class,
    )
except ModuleNotFoundError:  # Imported as tools.* by the unit test suite.
    from tools.srwz.font import (
        RAW_STANDARD_TRAILS,
        is_cjk_unified_ideograph,
        is_conditional_width_code,
        sha256_bytes,
    )
    from tools.srwz.release_font import (
        rendered_characters,
        selected_translation_tree_entries,
    )
    from tools.srwz.release_font_policy import (
        DEFAULT_WIDTH_CLASS,
        allocation_width_class,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "manifests/zh-release-special-width-assignment-audit.json"
)

CONDITIONAL_SUBRANGES = (
    ("latin_upper", 0x8260, 0x8279),
    ("latin_lower", 0x8281, 0x829A),
    ("kana_a", 0x829F, 0x82F1),
    ("kana_b", 0x8340, 0x8491),
    ("broad", 0x8140, 0x889E),
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def domain_for_path(path: str) -> str:
    marker = "corpus/zh/"
    if marker not in path:
        return path.split("/", 1)[0]
    return path.split(marker, 1)[1].split("/", 1)[0]


def visible_characters(texts) -> set[str]:
    return {
        character
        for text in texts
        for character in rendered_characters(text)
    }


def protected_compact_name_groups() -> dict[str, set[str]]:
    units = load(PROJECT_ROOT / "corpus/zh/display-names/units-full.json")
    unit_characters = visible_characters(
        text
        for segment in units["segments"]
        for text in segment["translations"]
    )
    speakers = load(PROJECT_ROOT / "corpus/zh/story-speakers.json")
    pilot_characters = visible_characters(
        entry["translation"] for entry in speakers["entries"]
    )
    remaining_ui = load(PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json")
    pilot_characters.update(
        visible_characters(remaining_ui["display_names_by_source_text"].values())
    )
    parts = load(PROJECT_ROOT / "corpus/zh/menu/system-ui-parts.json")
    part_characters = visible_characters(
        entry["translation"]
        for entry in parts["entries"]
        if any(
            reference.startswith("part/")
            for reference in entry.get("glossary_refs", [])
        )
    )
    return {
        "unit_name": unit_characters,
        "pilot_or_speaker_name": pilot_characters,
        "part_name": part_characters,
    }


def build_report(config_path: Path) -> dict:
    config = load(config_path)
    snapshot_path = PROJECT_ROOT / config["allocation_snapshot"]["path"]
    snapshot = load(snapshot_path)
    entries, _entry_scenes, selection = selected_translation_tree_entries(
        PROJECT_ROOT,
        config,
    )

    primary = {row["character"]: row for row in snapshot["primary_assignments"]}
    aliases = {
        row["character"]: row for row in snapshot["surface_alias_assignments"]
    }
    compatibility = snapshot["source_compatibility_assignments"]
    occurrence_counts = Counter()
    entry_counts = Counter()
    domain_occurrences: dict[str, Counter[str]] = defaultdict(Counter)
    source_paths: dict[str, set[str]] = defaultdict(set)
    for entry in entries.values():
        path = str(entry["id"]).split("#", 1)[0]
        counts = Counter(rendered_characters(entry["translation"]))
        for character, count in counts.items():
            occurrence_counts[character] += count
            entry_counts[character] += 1
            domain_occurrences[character][domain_for_path(path)] += count
            source_paths[character].add(path)

    rows = []
    for character, count in sorted(occurrence_counts.items()):
        primary_row = primary.get(character)
        effective = aliases.get(character, primary_row)
        if effective is None:
            continue
        code = int(effective["code"], 16)
        conditional = is_conditional_width_code(code)
        raw_trail = (code & 0xFF) in RAW_STANDARD_TRAILS
        if not conditional and not raw_trail:
            continue
        rows.append(
            {
                "character": character,
                "unicode": f"U+{ord(character):04X}",
                "primary_code": primary_row["code"] if primary_row else None,
                "effective_code": effective["code"],
                "effective_mapping": effective["mapping"],
                "uses_surface_alias": character in aliases,
                "conditional_width": conditional,
                "conditional_subranges": [
                    name
                    for name, start, end in CONDITIONAL_SUBRANGES
                    if start <= code <= end
                ],
                "raw_trail_gap": raw_trail,
                "cjk_ideograph": is_cjk_unified_ideograph(character),
                "occurrence_count": count,
                "entry_count": entry_counts[character],
                "domain_occurrences": dict(
                    sorted(domain_occurrences[character].items())
                ),
                "source_path_count": len(source_paths[character]),
                "source_path_samples": sorted(source_paths[character])[:12],
            }
        )
    rows.sort(key=lambda row: (-row["occurrence_count"], row["character"]))

    protected_groups = protected_compact_name_groups()
    protected_characters = {
        character
        for character in set().union(*protected_groups.values())
        if is_cjk_unified_ideograph(character)
    }
    active = {**primary, **aliases}
    protected_violations = []
    for character in sorted(protected_characters):
        row = active.get(character)
        if row is None:
            continue
        code = int(row["code"], 16)
        if allocation_width_class(code) == DEFAULT_WIDTH_CLASS:
            continue
        protected_violations.append(
            {
                "character": character,
                "code": row["code"],
                "width_class": allocation_width_class(code),
                "name_classes": sorted(
                    name
                    for name, characters in protected_groups.items()
                    if character in characters
                ),
            }
        )

    safe_owners: dict[str, list[dict]] = defaultdict(list)
    for group, assignments in (
        ("primary", snapshot["primary_assignments"]),
        ("surface_alias", snapshot["surface_alias_assignments"]),
        ("source_compatibility", compatibility),
    ):
        for row in assignments:
            if (
                allocation_width_class(int(row["code"], 16))
                == DEFAULT_WIDTH_CLASS
            ):
                safe_owners[row["character"]].append(
                    {"group": group, "code": row["code"]}
                )
    safe_duplicates = [
        {"character": character, "owners": owners}
        for character, owners in sorted(safe_owners.items())
        if len(owners) > 1
    ]

    conditional_cjk = [
        row for row in rows if row["conditional_width"] and row["cjk_ideograph"]
    ]
    raw_default_cjk = [
        row
        for row in rows
        if row["raw_trail_gap"]
        and not row["conditional_width"]
        and row["cjk_ideograph"]
    ]
    observed = []
    for character in "伦尘":
        alias = aliases.get(character)
        source = primary[character]
        observed.append(
            {
                "character": character,
                "primary_code": source["code"],
                "effective_code": alias["code"] if alias else source["code"],
                "effective_mapping": (
                    alias["mapping"] if alias else source["mapping"]
                ),
                "glyph_index": alias["glyph_index"] if alias else source["glyph_index"],
                "effective_code_default_width": not is_conditional_width_code(
                    int((alias or source)["code"], 16)
                ),
                "effective_code_raw_trail_gap": (
                    int((alias or source)["code"], 16) & 0xFF
                )
                in RAW_STANDARD_TRAILS,
                "occurrence_count": occurrence_counts[character],
                "domain_occurrences": dict(
                    sorted(domain_occurrences[character].items())
                ),
            }
        )

    candidates = snapshot["remaining_allocation_candidates"]
    default_width_candidates = [
        row
        for row in candidates
        if not is_conditional_width_code(int(row["code"], 16))
        and (int(row["code"], 16) & 0xFF) not in RAW_STANDARD_TRAILS
    ]
    rows_digest = sha256_bytes(
        json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return {
        "schema_version": 2,
        "status": "static_inventory_runtime_validation_pending",
        "issue": "ISSUE-017",
        "scope": (
            "Every visible character demanded by the selected Chinese release "
            "tree whose effective mapping is in 0x8140..0x889E or uses a raw "
            "standard-trail gap. Runtime observation remains a separate gate."
        ),
        "inputs": {
            "allocation_snapshot": {
                "path": str(snapshot_path.relative_to(PROJECT_ROOT)),
                "sha256": sha256_bytes(snapshot_path.read_bytes()),
            },
            "translation_selection_id": selection["selection_id"],
            "translation_selection_sha256": selection["selection_sha256"],
            "translation_entry_count": selection["unique_entry_count"],
        },
        "renderer_classes": {
            "conditional_width_range": "8140-889E",
            "conditional_subranges": [
                {"name": name, "start": f"{start:04X}", "end": f"{end:04X}"}
                for name, start, end in CONDITIONAL_SUBRANGES
            ],
            "raw_standard_trails": [f"{trail:02X}" for trail in RAW_STANDARD_TRAILS],
        },
        "summary": {
            "special_effective_assignment_count": len(rows),
            "conditional_width_effective_assignment_count": sum(
                row["conditional_width"] for row in rows
            ),
            "raw_trail_effective_assignment_count": sum(
                row["raw_trail_gap"] for row in rows
            ),
            "conditional_width_cjk_assignment_count": len(conditional_cjk),
            "conditional_width_cjk_occurrence_count": sum(
                row["occurrence_count"] for row in conditional_cjk
            ),
            "raw_trail_default_width_cjk_assignment_count": len(raw_default_cjk),
            "raw_trail_default_width_cjk_occurrence_count": sum(
                row["occurrence_count"] for row in raw_default_cjk
            ),
            "remaining_allocation_candidate_count": len(candidates),
            "remaining_default_width_candidate_count": len(
                default_width_candidates
            ),
            "rows_sha256": rows_digest,
            "protected_compact_name_character_count": len(
                protected_characters
            ),
            "protected_compact_name_special_width_violation_count": len(
                protected_violations
            ),
            "safe_region_duplicate_character_count": len(safe_duplicates),
        },
        "surface_policy_audit": {
            "allowed_conditional_width_surfaces": [
                "story_dialogue",
                "battle_dialogue",
                "story_system_dialogue",
                "library",
            ],
            "protected_compact_name_groups": {
                name: sum(
                    is_cjk_unified_ideograph(character)
                    for character in characters
                )
                for name, characters in protected_groups.items()
            },
            "protected_compact_name_special_width_violations": (
                protected_violations
            ),
            "safe_region_duplicate_characters": safe_duplicates,
            "runtime_reference_character": "喂",
        },
        "observed_issue_characters": observed,
        "special_assignments": rows,
        "runtime_acceptance": {
            "status": "not_tested",
            "required": (
                "Exercise representative story, battle, speaker, library, and "
                "intermission surfaces in PCSX2; static code classification is "
                "not runtime proof."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build_report(args.config.resolve())
    output = args.output.resolve()
    if args.check:
        if not output.is_file() or load(output) != report:
            raise SystemExit("special-width font assignment audit drift")
    else:
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    summary = report["summary"]
    print(
        "special-width font audit:",
        f"effective={summary['special_effective_assignment_count']}",
        f"conditional_cjk={summary['conditional_width_cjk_assignment_count']}",
        f"raw_default_cjk={summary['raw_trail_default_width_cjk_assignment_count']}",
        f"default_candidates={summary['remaining_default_width_candidate_count']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
