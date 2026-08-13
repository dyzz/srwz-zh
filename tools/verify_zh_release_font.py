#!/usr/bin/env python3
"""Verify the flattened global Chinese release-font component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.font import (
    GLYPH_SIZE,
    decode_vt1_font_segment,
    read_extended_glyph_table,
    sha256_bytes,
)
from srwz.release_font_policy import (
    ReleaseFontPolicyError,
    validate_new_character_allocations,
)
from srwz.release_font import (
    ReleaseFontError,
    assignment_index,
    audit_entry_font,
    audit_legacy_formation_glyph_compatibility,
    audit_runtime_generated_glyph_compatibility,
    baseline_with_original_ascii,
    rendered_characters,
    selected_translation_tree_entries,
)
from srwz.text import encode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove mapping, glyph, archive and all-corpus renderer coverage "
            "for the single global release font."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SystemExit(f"unsupported JSON document: {path}")
    return document


def _lock(path: Path) -> dict:
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "size": path.stat().st_size,
        "sha256": sha256_bytes(path.read_bytes()),
    }


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = _load(config_path)
    outputs = config["outputs"]
    proposal_path = PROJECT_ROOT / outputs["proposal"]
    readiness_path = PROJECT_ROOT / outputs["readiness"]
    component_root = PROJECT_ROOT / outputs["component_root"]
    report_path = PROJECT_ROOT / outputs["validation"]
    manifest_path = PROJECT_ROOT / outputs["manifest"]
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")

    proposal = _load(proposal_path)
    readiness = _load(readiness_path)
    component_report_path = component_root / "font-validation.json"
    component_report = _load(component_report_path)
    snapshot_path = PROJECT_ROOT / config["allocation_snapshot"]["path"]
    snapshot = _load(snapshot_path)
    primary = proposal.get("assignments")
    aliases = proposal.get("surface_alias_assignments")
    compatibility = proposal.get("source_compatibility_assignments", [])
    if (
        proposal.get("proposal_id") != config.get("font_profile_id")
        or proposal.get("status") != "static_proposal_not_runtime_verified"
        or not isinstance(primary, list)
        or not isinstance(aliases, list)
        or not isinstance(compatibility, list)
        or len(primary) != config["expected"]["primary_assignment_count"]
        or len(aliases)
        != config["expected"]["surface_alias_assignment_count"]
        or len(compatibility)
        != config["expected"]["source_compatibility_assignment_count"]
        or readiness.get("font_profile_id") != config.get("font_profile_id")
        or component_report.get("status")
        != "offline_font_validated_runtime_not_tested"
        or component_report.get("primary_assignment_count") != len(primary)
        or component_report.get("surface_alias_assignment_count")
        != len(aliases)
        or component_report.get("source_compatibility_assignment_count")
        != len(compatibility)
    ):
        raise SystemExit("release font proposal/component identity drift")
    remaining_candidates = snapshot.get("remaining_allocation_candidates")
    if not isinstance(remaining_candidates, list):
        raise SystemExit("release allocation candidate pool is malformed")
    try:
        allocation_policy = validate_new_character_allocations(
            config,
            snapshot,
            primary,
            remaining_candidates,
        )
    except ReleaseFontPolicyError as error:
        raise SystemExit(str(error)) from error

    candidate_slps_path = component_root / "SLPS_258.87"
    candidate_vt1_path = component_root / "DATA/VT1.BIN"
    candidate_slps = candidate_slps_path.read_bytes()
    candidate_vt1 = candidate_vt1_path.read_bytes()
    for label, payload in (
        ("slps", candidate_slps),
        ("vt1", candidate_vt1),
    ):
        expected_output = component_report["outputs"][label]
        if len(payload) != expected_output["size"] or sha256_bytes(
            payload
        ) != expected_output["sha256"]:
            raise SystemExit(f"release font {label} output drift")
    candidate_font = decode_vt1_font_segment(
        candidate_slps, candidate_vt1
    ).decoded
    if sha256_bytes(candidate_font) != component_report["font"][
        "output_decoded_sha256"
    ]:
        raise SystemExit("release decoded font hash drift")

    source_slps = (WORK_ROOT / "disc/SLPS_258.87").read_bytes()
    source_vt1 = (WORK_ROOT / "disc/DATA/VT1.BIN").read_bytes()
    source_font = decode_vt1_font_segment(source_slps, source_vt1).decoded
    assignments = [*primary, *aliases, *compatibility]
    for assignment in assignments:
        glyph_index = assignment["glyph_index"]
        start = glyph_index * GLYPH_SIZE
        source_glyph = source_font[start : start + GLYPH_SIZE]
        candidate_glyph = candidate_font[start : start + GLYPH_SIZE]
        if sha256_bytes(source_glyph) != assignment["allocation"][
            "glyph_preimage_sha256"
        ]:
            raise SystemExit(
                f"release glyph preimage drift: {assignment['character']!r}"
            )
        if sha256_bytes(candidate_glyph) != assignment["raster"][
            "packed_glyph_sha256"
        ]:
            raise SystemExit(
                f"release glyph raster drift: {assignment['character']!r}"
            )

    try:
        entries, _entry_scenes, selection = (
            selected_translation_tree_entries(PROJECT_ROOT, config)
        )
    except ReleaseFontError as error:
        raise SystemExit(str(error)) from error
    base_config_path = PROJECT_ROOT / config["base_font_config"]["path"]
    base_config = _load(base_config_path)
    encoding_baseline = base_config.get("encoding_baseline")
    if not isinstance(encoding_baseline, dict):
        raise SystemExit("global font base has no encoding baseline")
    text_table_path = PROJECT_ROOT / encoding_baseline["text_table"]["path"]
    base_codebook_path = (
        PROJECT_ROOT / encoding_baseline["base_codebook"]["path"]
    )
    for label, path in (
        ("text table", text_table_path),
        ("base codebook", base_codebook_path),
    ):
        reference = encoding_baseline[label.replace(" ", "_")]
        if sha256_bytes(path.read_bytes()) != reference.get("sha256"):
            raise SystemExit(f"global font {label} SHA-256 drift")
    table = load_text_table(text_table_path)
    try:
        legacy_formation_compatibility = (
            audit_legacy_formation_glyph_compatibility(
                snapshot,
                table,
                project_root=PROJECT_ROOT,
            )
        )
        runtime_generated_compatibility = (
            audit_runtime_generated_glyph_compatibility(
                snapshot,
                table,
                project_root=PROJECT_ROOT,
            )
        )
    except ReleaseFontError as error:
        raise SystemExit(str(error)) from error
    baseline = {
        "table": table,
        "extended_entries": read_extended_glyph_table(candidate_slps),
        "font": candidate_font,
        "base_assignments": assignment_index(base_codebook_path),
        "proposal_assignments": assignment_index(proposal_path),
    }
    if proposal.get("visible_ascii_policy") is not None:
        baseline = baseline_with_original_ascii(
            baseline,
            preserve_raw_ascii_punctuation=proposal[
                "visible_ascii_policy"
            ].get("preserve_raw_ascii_punctuation", False),
        )
    coverage = audit_entry_font(entries.values(), baseline)
    control_token_report = selection.get("control_tokens")
    literal_percent_report = selection.get("literal_percent_signs")
    if (
        not isinstance(control_token_report, dict)
        or control_token_report.get("preservation")
        != "lossless_encoder_control_path"
        or control_token_report.get("excluded_from_font_glyph_demand")
        is not True
        or not isinstance(control_token_report.get("entry_count"), int)
        or not isinstance(control_token_report.get("occurrence_count"), int)
        or not isinstance(control_token_report.get("kinds"), dict)
        or not isinstance(literal_percent_report, dict)
        or not isinstance(literal_percent_report.get("entry_count"), int)
        or not isinstance(
            literal_percent_report.get("occurrence_count"), int
        )
    ):
        raise SystemExit("global control-token inventory is malformed")
    supported_control_kinds = {
        "runtime_format",
        "runtime_substitution",
        "raw_byte",
        "text_tag",
    }
    control_occurrence_count = 0
    runtime_placeholder_occurrence_count = 0
    runtime_placeholder_bytes_exact = True
    for kind, kind_report in control_token_report["kinds"].items():
        if (
            kind not in supported_control_kinds
            or not isinstance(kind_report, dict)
            or not isinstance(kind_report.get("occurrence_count"), int)
            or not isinstance(kind_report.get("forms"), dict)
            or any(
                not isinstance(token, str)
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
                for token, count in kind_report.get("forms", {}).items()
            )
            or sum(kind_report.get("forms", {}).values())
            != kind_report.get("occurrence_count")
        ):
            raise SystemExit("global control-token kind inventory is malformed")
        for token in kind_report["forms"]:
            if rendered_characters(token):
                raise SystemExit(
                    "control token leaked into font glyph demand: "
                    f"{token!r}"
                )
            if kind in {"runtime_format", "runtime_substitution"}:
                runtime_placeholder_occurrence_count += kind_report["forms"][
                    token
                ]
                if encode_text(token, baseline["table"]) != token.encode(
                    "ascii"
                ):
                    runtime_placeholder_bytes_exact = False
        control_occurrence_count += kind_report["occurrence_count"]
    if (
        control_occurrence_count
        != control_token_report["occurrence_count"]
        or not runtime_placeholder_bytes_exact
    ):
        raise SystemExit("global control-token preservation audit failed")
    preserved_raw_ascii = []
    if proposal.get("visible_ascii_policy", {}).get(
        "preserve_raw_ascii_punctuation"
    ):
        allowed = {
            chr(code)
            for code in range(0x21, 0x7F)
            if not chr(code).isalnum()
        }
        unresolved = [
            item
            for item in coverage["missing"]
            if item["character"] not in allowed
        ]
        preserved_raw_ascii = [
            item
            for item in coverage["missing"]
            if item["character"] in allowed
        ]
        coverage = {
            **coverage,
            "vt1_missing_character_count_before_raw_ascii_policy": coverage[
                "missing_character_count"
            ],
            "preserved_raw_ascii_punctuation_count": len(
                preserved_raw_ascii
            ),
            "preserved_raw_ascii_punctuation_characters": "".join(
                item["character"] for item in preserved_raw_ascii
            ),
            "missing_character_count": len(unresolved),
            "missing_character_occurrence_count": sum(
                item["occurrence_count"] for item in unresolved
            ),
            "missing_characters": "".join(
                item["character"] for item in unresolved
            ),
            "missing": unresolved,
        }
    preserved_raw_ascii_by_character = {
        item["character"]: item["occurrence_count"]
        for item in preserved_raw_ascii
    }
    if preserved_raw_ascii_by_character.get("%", 0) != (
        literal_percent_report["occurrence_count"]
    ):
        raise SystemExit(
            "literal percent coverage does not match the format-token-aware "
            "translation inventory"
        )
    coverage = {
        **coverage,
        "control_token_entry_count": control_token_report["entry_count"],
        "control_token_occurrence_count": control_token_report[
            "occurrence_count"
        ],
        "control_token_kinds": control_token_report["kinds"],
        "control_tokens_excluded_from_glyph_demand": True,
        "runtime_placeholder_occurrence_count": (
            runtime_placeholder_occurrence_count
        ),
        "runtime_placeholder_bytes_preserved_exactly": (
            runtime_placeholder_bytes_exact
        ),
        "literal_percent_entry_count": literal_percent_report["entry_count"],
        "literal_percent_occurrence_count": literal_percent_report[
            "occurrence_count"
        ],
    }
    if (
        coverage["missing_character_count"] != 0
        or coverage["original_font_han_count"] != 0
        or coverage["original_font_visible_character_count"] != 0
    ):
        raise SystemExit(
            "global translation tree is not fully covered by the release font"
        )

    migration = snapshot.get("migration", {})
    if (
        migration.get("active_build_dependency") is not False
        or migration.get("preserved_historical_primary_assignment_count")
        != config["expected"]["historical_primary_assignment_count"]
        or migration.get("added_global_assignment_count")
        != config["expected"]["added_global_assignment_count"]
    ):
        raise SystemExit("release font migration-equivalence ratchet drift")
    acceptance = {
        "flattened_snapshot_is_self_contained": True,
        "historical_primary_mapping_change_is_compatibility_scoped": (
            migration.get("mode")
            == "flattened_release_baseline_with_legacy_save_compatibility"
            and legacy_formation_compatibility[
                "all_observed_original_codes_preserved"
            ]
        ),
        "raw_source_structural_glyph_compatibility_preserved": (
            len(compatibility)
            == config["expected"]["source_compatibility_assignment_count"]
        ),
        "observed_legacy_formation_glyphs_preserved": (
            legacy_formation_compatibility[
                "all_observed_original_codes_preserved"
            ]
        ),
        "runtime_generated_glyphs_preserved": (
            runtime_generated_compatibility[
                "all_runtime_generated_original_codes_preserved"
            ]
        ),
        "proposal_and_component_assignment_counts_exact": True,
        "glyph_preimages_and_rasters_exact": True,
        "all_translation_fields_missing_character_count_zero": True,
        "literal_raw_ascii_punctuation_preserved_without_font_remap": (
            bool(preserved_raw_ascii)
        ),
        "all_control_tokens_excluded_from_font_coverage": (
            control_token_report["occurrence_count"] > 0
            and coverage["control_tokens_excluded_from_glyph_demand"]
        ),
        "runtime_placeholders_preserved_byte_for_byte": (
            runtime_placeholder_occurrence_count > 0
            and runtime_placeholder_bytes_exact
        ),
        "new_character_assignments_use_renderer_double_byte_codes": (
            allocation_policy[
                "remaining_renderer_double_byte_candidate_count"
            ]
            == config["expected"]["remaining_candidate_slot_count"]
        ),
        "all_translation_fields_original_han_count_zero": True,
        "all_translation_fields_original_visible_character_count_zero": True,
        "codec_round_trip_exact": component_report["font"][
            "codec_round_trip_exact"
        ],
        "archive_size_preserved": component_report["archive"]["source_size"]
        == component_report["archive"]["output_size"],
        "offset_reread_exact": component_report["archive"][
            "offset_reread_exact"
        ],
    }
    if not all(acceptance.values()):
        raise SystemExit(f"release font acceptance failed: {acceptance}")
    manifest = {
        "schema_version": 1,
        "status": config["manifest_contract"]["status"],
        "font_profile_id": config["font_profile_id"],
        "scope": config["manifest_contract"]["scope"],
        "inputs": {
            "config": _lock(config_path),
            "base_config": _lock(base_config_path),
            "text_table": _lock(text_table_path),
            "base_codebook": _lock(base_codebook_path),
            "allocation_snapshot": _lock(snapshot_path),
            "translation_selection": selection,
        },
        "mapping": {
            "primary_assignment_count": len(primary),
            "surface_alias_assignment_count": len(aliases),
            "source_compatibility_assignment_count": len(compatibility),
            "allocation_assignment_count": proposal[
                "allocation_assignment_count"
            ],
            "reraster_existing_assignment_count": proposal[
                "reraster_existing_assignment_count"
            ],
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
            "remaining_candidate_slot_count": config["expected"][
                "remaining_candidate_slot_count"
            ],
            "new_character_allocation_policy": config[
                "new_character_allocation_policy"
            ],
            "guarded_post_migration_assignment_count": (
                allocation_policy[
                    "guarded_post_migration_assignment_count"
                ]
            ),
            "guarded_extension_assignment_count": allocation_policy[
                "guarded_extension_assignment_count"
            ],
            "remaining_renderer_double_byte_candidate_count": (
                allocation_policy[
                    "remaining_renderer_double_byte_candidate_count"
                ]
            ),
            "conditional_width_assignment_count": allocation_policy[
                "conditional_width_assignment_count"
            ],
            "conditional_width_candidate_count": allocation_policy[
                "conditional_width_candidate_count"
            ],
        },
        "migration": {
            "mode": migration["mode"],
            "historical_primary_assignment_count": migration[
                "preserved_historical_primary_assignment_count"
            ],
            "historical_primary_mapping_sha256": migration[
                "preserved_historical_primary_mapping_sha256"
            ],
            "added_global_assignment_count": migration[
                "added_global_assignment_count"
            ],
            "historical_profiles_are_active_build_dependencies": False,
        },
        "coverage": coverage,
        "legacy_formation_compatibility": legacy_formation_compatibility,
        "runtime_generated_glyph_compatibility": (
            runtime_generated_compatibility
        ),
        "proposal": _lock(proposal_path),
        "readiness": _lock(readiness_path),
        "font_component": {
            "report": _lock(component_report_path),
            "slps": _lock(candidate_slps_path),
            "vt1": _lock(candidate_vt1_path),
            "assignment_count": component_report["assignment_count"],
            "changed_glyph_count": component_report[
                "changed_glyph_count"
            ],
            "decoded_font_sha256": component_report["font"][
                "output_decoded_sha256"
            ],
        },
        "acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "reason": config["manifest_contract"]["runtime_reason"],
        },
    }
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file() or _load(manifest_path) != manifest:
            raise SystemExit(
                "release font manifest drift; review and rerun with "
                "--refresh-manifest"
            )
        manifest_status = "verified"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "global release font:",
        f"entries={len(entries)}",
        f"missing={coverage['missing_character_count']}",
        f"primary={len(primary)}",
        f"aliases={len(aliases)}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
