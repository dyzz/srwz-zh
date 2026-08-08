#!/usr/bin/env python3
"""Independently reread the remaining UI writeback from the final ISO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.archive import sha256_file
from srwz.font import sha256_bytes
from srwz.iso9660 import SECTOR_SIZE
from srwz.text import load_text_table, original_fullwidth_ascii_overrides
from srwz.text import project_runtime_text_table

from verify_full_story_iso_content import (
    FULL_COMPONENT_CONFIG,
    TEXT_TABLE,
    load_overrides,
    read_members,
    verify_final_compdata,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = (
    PROJECT_ROOT
    / "build/iso/zh-release-full-story/srwz-zh-release-full-story-r8.iso"
)
DEFAULT_COMPONENT_MANIFEST = (
    PROJECT_ROOT / "manifests/full-story-components-validation.json"
)
DEFAULT_ISO_CONFIG = (
    PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
)
DEFAULT_PROPOSAL = (
    PROJECT_ROOT / "work/writeback/zh-release-codebook-proposal.json"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "work/verification/zh-release-remaining-ui-content.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "manifests/zh-release-remaining-ui-iso-content-validation.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument(
        "--component-manifest", type=Path, default=DEFAULT_COMPONENT_MANIFEST
    )
    parser.add_argument("--iso-config", type=Path, default=DEFAULT_ISO_CONFIG)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    args = parse_args()
    iso_path = project_path(args.iso)
    component_path = project_path(args.component_manifest)
    iso_config_path = project_path(args.iso_config)
    proposal_path = project_path(args.proposal)
    report_path = project_path(args.report)
    manifest_path = project_path(args.manifest)
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")

    component = json.loads(component_path.read_text(encoding="utf-8"))
    iso_config = json.loads(iso_config_path.read_text(encoding="utf-8"))
    full_config = json.loads(FULL_COMPONENT_CONFIG.read_text(encoding="utf-8"))
    if component.get("status") != iso_config.get("component_required_status"):
        raise SystemExit("component manifest status mismatch")
    output_locks = component.get("outputs")
    if not isinstance(output_locks, dict):
        raise SystemExit("component output locks are missing")
    members = read_members(iso_path, tuple(output_locks))
    for member, data in members.items():
        lock = output_locks[member]
        if len(data) != lock["size"] or sha256_bytes(data) != lock["sha256"]:
            raise SystemExit(f"final ISO component mismatch: {member}")

    iso_size = iso_path.stat().st_size
    iso_sha256 = sha256_file(iso_path)
    if (
        iso_size != iso_config["output"]["expected_size"]
        or iso_sha256 != iso_config["output"]["expected_sha256"]
    ):
        raise SystemExit("final ISO lock mismatch")

    source_table = load_text_table(TEXT_TABLE)
    primary, aliases, _proposal = load_overrides(proposal_path)
    output_table = project_runtime_text_table(source_table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(source_table)
    )
    content = verify_final_compdata(
        members["DATA/COMPDATA.BN"],
        members["SLPS_258.87"],
        source_table,
        output_table,
        aliases,
    )

    remaining = component["remaining_ui"]
    atlas = remaining["atlas"]
    compdata_budget = full_config["full_pilot_names"]["codec"][
        "max_output_size"
    ]
    compdata_size = len(members["DATA/COMPDATA.BN"])
    checks = {
        "iso_hash_exact": True,
        "all_component_members_exact": True,
        "pilot_names_exact": content["readback_exact"],
        "remaining_ui_binary_text_exact": content["remaining_ui"][
            "readback_exact"
        ],
        "placeholder_control_tokens_preserved": all(
            content["remaining_ui"][group].get(
                "placeholder_control_tokens_preserved", True
            )
            for group in (
                "compdata_direct",
                "leadership_effects",
                "slps",
                "parts",
            )
        ),
        "compdata_within_fixed_sector_budget": compdata_size
        <= compdata_budget,
        "single_character_atlas_regions_untouched": atlas[
            "single_character_regions_untouched"
        ]
        and atlas["protected_single_character_sources"] == ["攻", "反"],
        "male_default_name_offsets_exact": content["new_game_regressions"][
            "male_default_name_readback_exact"
        ],
        "scenario_button_labels_exact": content["new_game_regressions"][
            "scenario_button_readback_exact"
        ],
        "male_profile_24x3_exact": (
            content["new_game_regressions"]["male_profile_readback_exact"]
            and content["new_game_regressions"]["male_profile_within_24x3"]
        ),
        "male_profile_default_width_codes_only": content[
            "new_game_regressions"
        ]["male_profile_default_width_codes_only"],
    }
    report = {
        "schema_version": 1,
        "status": "remaining_ui_final_iso_static_readback_passed",
        "scope": (
            "Independent final-ISO readback of remaining UI fixed spans, "
            "leadership effects, SLPS text, strengthening parts, and pilot "
            "display/family/given names; gameplay runtime is separate."
        ),
        "iso": {
            "path": str(iso_path.relative_to(PROJECT_ROOT)),
            "size": iso_size,
            "sha256": iso_sha256,
        },
        "component_manifest": str(component_path.relative_to(PROJECT_ROOT)),
        "component_members": {
            member: {
                "size": len(data),
                "sha256": sha256_bytes(data),
                "replacement_exact": True,
            }
            for member, data in members.items()
        },
        "pilot_names": {
            key: content[key]
            for key in (
                "story_unique_source_count",
                "residual_unique_source_count",
                "unique_source_count",
                "selected_entry_count",
                "field_entry_counts",
                "readback_exact",
            )
        },
        "remaining_ui": content["remaining_ui"],
        "new_game_regressions": content["new_game_regressions"],
        "atlas": atlas,
        "compdata_sector_budget": {
            "sector_size": SECTOR_SIZE,
            "maximum_size": compdata_budget,
            "output_size": compdata_size,
            "headroom": compdata_budget - compdata_size,
            "maximum_sector_count": (
                compdata_budget + SECTOR_SIZE - 1
            )
            // SECTOR_SIZE,
            "output_sector_count": (compdata_size + SECTOR_SIZE - 1)
            // SECTOR_SIZE,
            "within_budget": True,
        },
        "checks": checks,
        "runtime": {
            "status": "not_tested",
            "reason": (
                "Fresh new-game and load-game STAGE entry evidence has not "
                "been captured for this exact ISO."
            ),
        },
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise SystemExit(f"remaining UI ISO checks failed: {failed!r}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest != report:
            raise SystemExit("remaining UI ISO content manifest drift")
        manifest_status = "verified"
    print(
        "remaining UI final ISO readback:",
        f"pilot_names={content['selected_entry_count']}",
        f"direct={content['remaining_ui']['compdata_direct']['entry_count']}",
        f"leadership={content['remaining_ui']['leadership_effects']['entry_count']}",
        f"slps={content['remaining_ui']['slps']['entry_count']}",
        f"parts={content['remaining_ui']['parts']['written_entry_count']}",
        "status=passed",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
