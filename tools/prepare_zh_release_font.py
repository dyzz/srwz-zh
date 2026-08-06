#!/usr/bin/env python3
"""Prepare one flattened global Chinese release-font proposal."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from srwz.canary import rasterize_character, rasterizer_point_size
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
    ReleaseFontPolicyError,
    validate_new_character_allocations,
)
from srwz.ui_font import UiFontError, _selected_translation_tree_entries
from srwz.ui_inventory import rendered_characters


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rasterize the canonical global mapping once for all Chinese "
            "localization surfaces."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
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
    remaining_candidates = snapshot.get("remaining_allocation_candidates")
    if (
        not isinstance(primary_rows, list)
        or not isinstance(alias_rows, list)
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
    try:
        validate_new_character_allocations(
            config,
            snapshot,
            primary_rows,
            remaining_candidates,
        )
    except ReleaseFontPolicyError as error:
        raise SystemExit(str(error)) from error

    expected = config.get("expected")
    if not isinstance(expected, dict) or (
        len(primary_rows) != expected.get("primary_assignment_count")
        or len(alias_rows) != expected.get("surface_alias_assignment_count")
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
            _selected_translation_tree_entries(PROJECT_ROOT, config)
        )
    except (FontProfileError, FontSourceError, UiFontError) as error:
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
            for row in (*primary_rows, *alias_rows)
            if isinstance(row, dict)
        }
    )
    if any(not isinstance(character, str) or len(character) != 1 for character in characters):
        raise SystemExit("release font mapping contains an invalid character")

    def rasterize(character: str) -> tuple[str, dict]:
        gray, pixels, packed = rasterize_character(
            rasterizer["executable"],
            fallback_paths.get(character, font_path),
            character,
            rasterizer,
        )
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

    with ThreadPoolExecutor(max_workers=8) as executor:
        rasters = dict(executor.map(rasterize, characters))

    def expand(row: dict, *, alias: bool) -> dict:
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
        assignment = {
            "id": (
                f"zh-release-alias-u{ord(character):04x}"
                if alias
                else f"zh-release-u{ord(character):04x}"
            ),
            **row,
            "status": (
                "canonical_surface_safe_alias"
                if alias
                else "canonical_global_release_assignment"
            ),
            "allocation": {
                "owner": "global/zh-release",
                "basis": (
                    "flattened canonical surface-safe alias"
                    if alias
                    else "flattened canonical mapping shared by every Chinese localization surface"
                ),
                "glyph_preimage_sha256": sha256_bytes(preimage),
                "glyph_preimage_all_zero": not any(preimage),
            },
            "raster": rasters[character],
        }
        return assignment

    assignments = [expand(row, alias=False) for row in primary_rows]
    aliases = [expand(row, alias=True) for row in alias_rows]
    all_codes = [item["code"] for item in (*assignments, *aliases)]
    all_glyphs = [item["glyph_index"] for item in (*assignments, *aliases)]
    if len(all_codes) != len(set(all_codes)) or len(all_glyphs) != len(
        set(all_glyphs)
    ):
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
                - len(aliases)
            ),
            "source_glyph_reuse_characters": "".join(
                assignment.get("source_character", "")
                for assignment in aliases
            ),
        },
        "surface_alias_assignments": aliases,
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
        "allocation_assignment_count": proposal[
            "allocation_assignment_count"
        ],
        "reraster_existing_assignment_count": proposal[
            "reraster_existing_assignment_count"
        ],
        "remaining_candidate_slot_count": expected[
            "remaining_candidate_slot_count"
        ],
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
    print(f"proposal: {proposal_path}")
    print(f"readiness: {readiness_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
