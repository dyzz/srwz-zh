#!/usr/bin/env python3
"""Prepare one flattened global Chinese release-font proposal."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from srwz.font_rasterizer import rasterize_character, rasterizer_point_size
from srwz.diagnostics import require_work_output
from srwz.font import (
    GLYPH_SIZE,
    decode_vt1_font_segment,
    glyph_index_for_code,
    read_extended_glyph_table,
    sha256_bytes,
)
from srwz.font_profile import FontProfileError, load_font_profile
from srwz.font_source import (
    FontSourceError,
    font_source_metadata,
    load_font_lock,
    verify_font_fallbacks,
    verify_font_lock_files,
)
from srwz.release_font_policy import (
    DEFAULT_WIDTH_CLASS,
    ReleaseFontPolicyError,
    allocation_width_class,
    validate_new_character_allocations,
)
from srwz.release_font import (
    ReleaseFontError,
    audit_legacy_formation_glyph_compatibility,
    audit_runtime_generated_glyph_compatibility,
    audit_sound_select_title_glyph_compatibility,
    load_frozen_formation_compatibility,
    rendered_characters,
    selected_translation_tree_entries,
)
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"
LOW_STOCK_START = 0x8140
LOW_STOCK_END = 0x8491


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rasterize the canonical global mapping once for all Chinese "
            "localization surfaces."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--raster-output", type=Path,
                        help="Pass freshly rendered grayscale glyphs to the font component.")
    parser.add_argument(
        "--reuse-raster-cache",
        action="store_true",
        help=(
            "Reuse per-character raster hashes from the existing proposal "
            "only when the font source, flavor, fallbacks, rasterizer, and "
            "allocation snapshot still match. Text selection is rescanned."
        ),
    )
    return parser.parse_args()


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SystemExit(f"unsupported JSON document: {path}")
    return document


def _project_path(reference: str) -> Path:
    path = (PROJECT_ROOT / reference).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise SystemExit(f"path escapes project root: {reference}") from error
    return path


def _mapping_sha256(rows: list[dict]) -> str:
    return sha256_bytes(
        json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _reusable_rasters(
    prior_proposal: dict | None,
    *,
    expected_metadata: dict,
    allocation_sha256: str,
) -> tuple[dict[str, dict], str]:
    if prior_proposal is None:
        return {}, "no reusable proposal"
    metadata_matches = all(
        prior_proposal.get(key) == value
        for key, value in expected_metadata.items()
    ) and prior_proposal.get("allocation_registry", {}).get(
        "sha256"
    ) == allocation_sha256
    if not metadata_matches:
        return {}, "font or allocation identity changed"

    groups = tuple(
        prior_proposal.get(key)
        for key in (
            "assignments",
            "surface_alias_assignments",
            "source_compatibility_assignments",
        )
    )
    if any(not isinstance(group, list) for group in groups):
        return {}, "cached character rasters are malformed"
    rasters = {}
    for item in (item for group in groups for item in group):
        if not isinstance(item, dict):
            return {}, "cached character rasters are malformed"
        character = item.get("character")
        raster = item.get("raster")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(raster, dict)
            or raster.get("mode") == "preserve_original_iso_glyph"
        ):
            continue
        prior = rasters.setdefault(character, raster)
        if prior != raster:
            return {}, "cached character rasters conflict"
    return rasters, "font and allocation identities match"


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = _load(config_path)
    outputs = config.get("outputs")
    if not isinstance(outputs, dict):
        raise SystemExit("release font config has no outputs")
    proposal_path = require_work_output(
        PROJECT_ROOT / outputs["proposal"], WORK_ROOT
    )
    readiness_path = require_work_output(
        PROJECT_ROOT / outputs["readiness"], WORK_ROOT
    )
    prior_proposal = None
    if args.reuse_raster_cache and proposal_path.is_file():
        try:
            prior_proposal = _load(proposal_path)
        except (OSError, json.JSONDecodeError, SystemExit):
            prior_proposal = None
    for output in (proposal_path, readiness_path):
        if output.exists() and not args.force:
            raise SystemExit(f"output exists; use --force: {output}")

    snapshot_reference = config.get("allocation_snapshot")
    if not isinstance(snapshot_reference, dict):
        raise SystemExit("release font config has no allocation snapshot")
    snapshot_path = _project_path(snapshot_reference.get("path"))
    snapshot_bytes = snapshot_path.read_bytes()
    if sha256_bytes(snapshot_bytes) != snapshot_reference.get("sha256"):
        raise SystemExit("release font allocation snapshot SHA-256 drift")
    snapshot = json.loads(snapshot_bytes.decode("utf-8"))
    if snapshot.get("snapshot_id") != snapshot_reference.get("snapshot_id"):
        raise SystemExit("release font allocation snapshot identity drift")
    primary_rows = snapshot.get("primary_assignments")
    alias_rows = snapshot.get("surface_alias_assignments")
    compatibility_rows = snapshot.get(
        "source_compatibility_assignments", []
    )
    remaining_candidates = snapshot.get("remaining_allocation_candidates")
    if (
        not isinstance(primary_rows, list)
        or not isinstance(alias_rows, list)
        or not isinstance(compatibility_rows, list)
        or not isinstance(remaining_candidates, list)
    ):
        raise SystemExit("release font allocation snapshot is malformed")
    if _mapping_sha256(primary_rows) != snapshot.get(
        "primary_mapping_sha256"
    ) or _mapping_sha256(alias_rows) != snapshot.get(
        "surface_alias_mapping_sha256"
    ):
        raise SystemExit("release font mapping digest drift")
    if _mapping_sha256(remaining_candidates) != snapshot.get(
        "remaining_allocation_candidates_sha256"
    ):
        raise SystemExit("release font remaining-candidate digest drift")
    if _mapping_sha256(compatibility_rows) != snapshot.get(
        "source_compatibility_mapping_sha256"
    ):
        raise SystemExit("release font source-compatibility digest drift")
    try:
        validate_new_character_allocations(
            config,
            snapshot,
            primary_rows,
            remaining_candidates,
            surface_alias_rows=alias_rows,
            source_compatibility_rows=compatibility_rows,
        )
    except ReleaseFontPolicyError as error:
        raise SystemExit(str(error)) from error

    expected = config.get("expected")
    if not isinstance(expected, dict) or (
        len(primary_rows) != expected.get("primary_assignment_count")
        or len(alias_rows) != expected.get("surface_alias_assignment_count")
        or len(compatibility_rows)
        != expected.get("source_compatibility_assignment_count")
        or snapshot.get("allocation_assignment_count")
        != expected.get("allocation_assignment_count")
        or snapshot.get("reraster_existing_assignment_count")
        != expected.get("reraster_existing_assignment_count")
        or snapshot.get("migration", {}).get(
            "preserved_historical_primary_assignment_count"
        )
        != expected.get("historical_primary_assignment_count")
        or snapshot.get("migration", {}).get("added_global_assignment_count")
        != expected.get("added_global_assignment_count")
        or len(remaining_candidates)
        != expected.get("remaining_candidate_slot_count")
    ):
        raise SystemExit("release font assignment-count ratchet drift")

    try:
        base_config_path = _project_path(config["base_font_config"]["path"])
        base_config = _load(base_config_path)
        encoding_baseline = base_config.get("encoding_baseline")
        if not isinstance(encoding_baseline, dict):
            raise ReleaseFontError("global font base has no encoding baseline")
        table_path = _project_path(encoding_baseline["text_table"]["path"])
        if sha256_bytes(table_path.read_bytes()) != encoding_baseline[
            "text_table"
        ]["sha256"]:
            raise ReleaseFontError("global font text table SHA-256 drift")
        text_table = load_text_table(table_path)
        legacy_formation_compatibility = (
            audit_legacy_formation_glyph_compatibility(
                snapshot,
                text_table,
                project_root=PROJECT_ROOT,
            )
        )
        runtime_generated_compatibility = (
            audit_runtime_generated_glyph_compatibility(
                snapshot,
                text_table,
                project_root=PROJECT_ROOT,
            )
        )
        sound_select_title_compatibility = (
            audit_sound_select_title_glyph_compatibility(
                snapshot,
                text_table,
                project_root=PROJECT_ROOT,
            )
        )
        frozen_formation_assignments = (
            load_frozen_formation_compatibility(
                PROJECT_ROOT,
                config,
                snapshot,
            )
        )
        profile = load_font_profile(PROJECT_ROOT, config_path)
        font_lock = load_font_lock(PROJECT_ROOT / profile["font_lock"])
        locked_paths = verify_font_lock_files(
            PROJECT_ROOT, WORK_ROOT, font_lock
        )
        fallback_paths, fallback_reports = verify_font_fallbacks(
            PROJECT_ROOT,
            WORK_ROOT,
            profile["unsupported_character_fallbacks"],
        )
        entries, _entry_scenes, selection = (
            selected_translation_tree_entries(PROJECT_ROOT, config)
        )
    except (FontProfileError, FontSourceError, ReleaseFontError) as error:
        raise SystemExit(str(error)) from error

    source_slps = (WORK_ROOT / "disc/SLPS_258.87").read_bytes()
    source_vt1 = (WORK_ROOT / "disc/DATA/VT1.BIN").read_bytes()
    original_font = decode_vt1_font_segment(source_slps, source_vt1).decoded
    extended_entries = read_extended_glyph_table(source_slps)
    rasterizer = profile["rasterizer"]
    font_path = locked_paths["font"]

    characters = sorted(
        {
            row.get("character")
            for row in (*primary_rows, *alias_rows, *compatibility_rows)
            if isinstance(row, dict)
        }
    )
    if any(not isinstance(character, str) or len(character) != 1 for character in characters):
        raise SystemExit("release font mapping contains an invalid character")

    raster_grays = {}

    def rasterize(character: str) -> tuple[str, dict]:
        gray, pixels, packed = rasterize_character(
            rasterizer["executable"],
            fallback_paths.get(character, font_path),
            character,
            rasterizer,
        )
        if args.raster_output is not None:
            raster_grays[character] = gray.hex()
        if not character.isspace() and not any(packed):
            raise SystemExit(
                "visible glyph raster is empty; add an explicit global "
                f"fallback for {character!r}"
            )
        return character, {
            "point_size": rasterizer_point_size(character, rasterizer),
            "raw_gray_sha256": sha256_bytes(gray),
            "pixels_4bpp_sha256": sha256_bytes(pixels),
            "packed_glyph_sha256": sha256_bytes(packed),
        }

    rasters, raster_cache_reason = _reusable_rasters(
        prior_proposal,
        expected_metadata={
            "font_source": font_source_metadata(font_lock),
            "font_flavor": profile["font_flavor"],
            "unsupported_character_fallbacks": list(fallback_reports),
            "rasterizer": rasterizer,
        },
        allocation_sha256=sha256_bytes(snapshot_bytes),
    )

    required_raster_characters = {
        row["character"]
        for row in primary_rows
        if not (
            LOW_STOCK_START <= int(row["code"], 16) <= LOW_STOCK_END
            and text_table.characters.get(int(row["code"], 16))
            == row["character"]
        )
    } | {row["character"] for row in alias_rows}
    if not required_raster_characters <= set(rasters):
        with ThreadPoolExecutor(max_workers=8) as executor:
            rasters = dict(executor.map(rasterize, characters))
        print(f"[cache] release font rasters rebuilt: {raster_cache_reason}")
    else:
        print(
            "[cache] release font rasters reused: "
            f"characters={len(required_raster_characters)}; {raster_cache_reason}"
        )

    def expand(
        row: dict,
        *,
        alias: bool = False,
        source_compatibility: bool = False,
    ) -> dict:
        character = row.get("character")
        code_text = row.get("code")
        glyph_index = row.get("glyph_index")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code_text, str)
            or not isinstance(glyph_index, int)
        ):
            raise SystemExit("release font mapping row is malformed")
        if row.get("mapping") == "extended_shared_glyph_alias":
            if not alias:
                raise SystemExit("extended shared glyph mapping must be an alias")
            table_offset = row.get("extended_table_offset")
            source_code = row.get("extended_table_source_code")
            source_entry = next(
                (
                    entry
                    for entry in extended_entries
                    if entry.table_offset == table_offset
                ),
                None,
            )
            if (
                not isinstance(table_offset, int)
                or not isinstance(source_code, str)
                or source_entry is None
                or source_entry.code != int(source_code, 16)
                or source_entry.code >= 0x989F
            ):
                raise SystemExit(
                    f"extended shared alias table preimage drift: {character!r}"
                )
            resolved = glyph_index
        else:
            try:
                resolved = glyph_index_for_code(int(code_text, 16), extended_entries)
            except ValueError as error:
                raise SystemExit(
                    f"release font code is not renderer-addressable: {character!r}"
                ) from error
        if resolved != glyph_index:
            raise SystemExit(f"release font glyph mapping drift: {character!r}")
        start = glyph_index * GLYPH_SIZE
        preimage = original_font[start : start + GLYPH_SIZE]
        code = int(code_text, 16)
        preserve_stock_primary = (
            not alias
            and not source_compatibility
            and LOW_STOCK_START <= code <= LOW_STOCK_END
            and text_table.characters.get(code) == character
        )
        preserve_original_glyph = (
            source_compatibility or preserve_stock_primary
        )
        assignment = {
            "id": (
                f"zh-release-alias-u{ord(character):04x}"
                if alias
                else f"zh-release-source-compat-u{ord(character):04x}"
                if source_compatibility
                else f"zh-release-u{ord(character):04x}"
            ),
            **row,
            "status": (
                "canonical_surface_safe_alias"
                if alias
                else "canonical_raw_source_compatibility"
                if source_compatibility
                else "canonical_global_release_assignment"
            ),
            "allocation": {
                "owner": "global/zh-release",
                "basis": (
                    "flattened canonical surface-safe alias"
                    if alias
                    else (
                        "raw source glyph compatibility for untranslated "
                        "structural text"
                    )
                    if source_compatibility
                    else "flattened canonical mapping shared by every Chinese localization surface"
                ),
                "glyph_preimage_sha256": sha256_bytes(preimage),
                "glyph_preimage_all_zero": not any(preimage),
            },
            **(
                {
                    "preserve_source_glyph": True,
                    **(
                        {"preserve_original_stock_primary": True}
                        if preserve_stock_primary
                        else {}
                    ),
                }
                if preserve_original_glyph
                else {}
            ),
            "raster": (
                {
                    "mode": "preserve_original_iso_glyph",
                    "packed_glyph_sha256": sha256_bytes(preimage),
                }
                if preserve_original_glyph
                else rasters[character]
            ),
        }
        return assignment

    assignments = [expand(row, alias=False) for row in primary_rows]
    aliases = [expand(row, alias=True) for row in alias_rows]
    compatibility = [
        expand(row, source_compatibility=True)
        for row in compatibility_rows
    ]
    all_codes = [
        item["code"] for item in (*assignments, *aliases, *compatibility)
    ]
    glyph_owners = {}
    invalid_shared_glyph = False
    for item in (*assignments, *aliases, *compatibility):
        owner = glyph_owners.get(item["glyph_index"])
        if owner is None:
            glyph_owners[item["glyph_index"]] = item
        elif not (
            item.get("mapping") == "extended_shared_glyph_alias"
            and item["character"] == owner["character"]
        ):
            invalid_shared_glyph = True
    if len(all_codes) != len(set(all_codes)) or invalid_shared_glyph:
        raise SystemExit("release font proposal has a code/glyph collision")

    demand = Counter(
        character
        for entry in entries.values()
        for character in rendered_characters(entry["translation"])
    )
    proposal = {
        "schema_version": 1,
        "proposal_id": profile["profile_id"],
        "status": "static_proposal_not_runtime_verified",
        "stage_indices": [],
        "ui_selection": selection,
        "font_source": font_source_metadata(font_lock),
        "font_flavor": profile["font_flavor"],
        "unsupported_character_fallbacks": list(fallback_reports),
        "selection_policy": profile["scope"],
        "visible_ascii_policy": config["visible_ascii_policy"],
        "new_character_allocation_policy": config[
            "new_character_allocation_policy"
        ],
        "rasterizer": rasterizer,
        "allocation_registry": {
            "id": snapshot["snapshot_id"],
            "sha256": sha256_bytes(snapshot_bytes),
            "registered_character_count": len(primary_rows),
            "active_character_count": len(primary_rows),
            "retired_characters": [],
        },
        "allocation_assignment_count": snapshot[
            "allocation_assignment_count"
        ],
        "reraster_existing_assignment_count": snapshot[
            "reraster_existing_assignment_count"
        ],
        "assignments": assignments,
        "surface_safe_aliases": {
            "mode": "flattened_global_snapshot",
            "surface_id": "global/all-localized-text-surfaces",
            "assignment_count": len(aliases),
            "alias_codes_default_width_only": True,
            "primary_codes_preserved": True,
            "all_selected_assignments": False,
            "conditional_primary_assignment_count": sum(
                0x8140 <= int(assignment["code"], 16) < 0x889F
                for assignment in assignments
            ),
            "unaliased_conditional_assignment_count": (
                sum(
                    0x8140 <= int(assignment["code"], 16) < 0x889F
                    for assignment in assignments
                )
                - sum(
                    0x8140
                    <= int(assignment["primary_code"], 16)
                    < 0x889F
                    for assignment in aliases
                )
            ),
            "special_primary_assignment_count": sum(
                allocation_width_class(int(assignment["code"], 16))
                != DEFAULT_WIDTH_CLASS
                for assignment in assignments
            ),
            "unaliased_special_assignment_count": (
                sum(
                    allocation_width_class(int(assignment["code"], 16))
                    != DEFAULT_WIDTH_CLASS
                    for assignment in assignments
                )
                - len(aliases)
            ),
            "source_glyph_reuse_characters": "".join(
                assignment.get("source_character", "")
                for assignment in aliases
            ),
        },
        "surface_alias_assignments": aliases,
        "source_compatibility_assignments": compatibility,
    }
    readiness = {
        "schema_version": 1,
        "status": "global_release_mapping_prepared_runtime_not_tested",
        "font_profile_id": profile["profile_id"],
        "translation_selection": selection,
        "translation_entry_count": len(entries),
        "unique_rendered_character_count": len(demand),
        "primary_assignment_count": len(assignments),
        "surface_alias_assignment_count": len(aliases),
        "source_compatibility_assignment_count": len(compatibility),
        "allocation_assignment_count": proposal[
            "allocation_assignment_count"
        ],
        "reraster_existing_assignment_count": proposal[
            "reraster_existing_assignment_count"
        ],
        "remaining_candidate_slot_count": expected[
            "remaining_candidate_slot_count"
        ],
        "legacy_formation_compatibility": legacy_formation_compatibility,
        "runtime_generated_glyph_compatibility": (
            runtime_generated_compatibility
        ),
        "sound_select_title_glyph_compatibility": (
            sound_select_title_compatibility
        ),
        "formation_affected_character_freeze": (
            frozen_formation_assignments
        ),
        "new_character_allocation_policy": config[
            "new_character_allocation_policy"
        ],
        "allocation_snapshot": {
            "path": str(snapshot_path.relative_to(PROJECT_ROOT)),
            "sha256": sha256_bytes(snapshot_bytes),
            "primary_mapping_sha256": snapshot[
                "primary_mapping_sha256"
            ],
            "surface_alias_mapping_sha256": snapshot[
                "surface_alias_mapping_sha256"
            ],
            "source_compatibility_mapping_sha256": snapshot[
                "source_compatibility_mapping_sha256"
            ],
            "remaining_allocation_candidates_sha256": snapshot[
                "remaining_allocation_candidates_sha256"
            ],
        },
        "migration": snapshot["migration"],
        "font_source": proposal["font_source"],
        "font_flavor": proposal["font_flavor"],
        "runtime_acceptance": "not tested",
    }
    for path, document in (
        (proposal_path, proposal),
        (readiness_path, readiness),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        "global release font proposal:",
        f"entries={len(entries)}",
        f"primary={len(assignments)}",
        f"aliases={len(aliases)}",
        "runtime=pending",
    )
    if args.raster_output is not None:
        raster_output = require_work_output(args.raster_output, WORK_ROOT)
        raster_output.parent.mkdir(parents=True, exist_ok=True)
        raster_output.write_text(json.dumps({
            "schema_version": 1,
            "proposal_sha256": sha256_bytes(proposal_path.read_bytes()),
            "gray_by_character": raster_grays,
        }, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"proposal: {proposal_path}")
    print(f"readiness: {readiness_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
