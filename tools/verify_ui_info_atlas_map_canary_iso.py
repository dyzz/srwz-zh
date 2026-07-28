#!/usr/bin/env python3
"""Bind the information-atlas mapping canary to its static ISO evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.iso_config import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config/iso/ui-info-atlas-map-canary-build.json"
)
DEFAULT_COMPONENT_MANIFEST = (
    PROJECT_ROOT / "manifests/ui-info-atlas-map-canary-validation.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "manifests/ui-info-atlas-map-canary-runtime-validation.json"
)
DEFAULT_REPORT = (
    WORK_ROOT
    / "review/ui-info-atlas-map-canary/iso-validation.json"
)


class UiInfoAtlasMapCanaryIsoError(RuntimeError):
    """The mapping-canary ISO does not match its component evidence."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UiInfoAtlasMapCanaryIsoError(
            f"JSON root must be an object: {path}"
        )
    return value


def file_lock(path: Path) -> dict:
    return {
        "path": str(path.resolve().relative_to(PROJECT_ROOT)),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--component-manifest",
        type=Path,
        default=DEFAULT_COMPONENT_MANIFEST,
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def build_report(config_path: Path, component_manifest_path: Path) -> dict:
    config = load_config(config_path)
    component = load_json(component_manifest_path)
    if config.get("profile_id") != "ui-info-atlas-map-canary":
        raise UiInfoAtlasMapCanaryIsoError(
            "unexpected information-atlas mapping-canary ISO profile"
        )
    if component.get("status") != (
        "static_component_validated_runtime_mapping_pending"
    ):
        raise UiInfoAtlasMapCanaryIsoError(
            "information-atlas mapping-canary component is not validated"
        )
    if component.get("profile_id") != config["profile_id"]:
        raise UiInfoAtlasMapCanaryIsoError(
            "component and ISO profile identifiers differ"
        )

    iso_report_path = PROJECT_ROOT / config["output"]["report"]
    iso_path = PROJECT_ROOT / config["output"]["path"]
    if not iso_report_path.is_file() or not iso_path.is_file():
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary ISO or report is missing; run "
            "build_canary_iso.py"
        )
    iso_report = load_json(iso_report_path)
    output_iso = iso_report["output_iso"]
    layout = iso_report["layout"]
    expected_output = config["output"]
    actual_output = {
        "size": iso_path.stat().st_size,
        "sha256": sha256_file(iso_path),
    }
    expected_lock = {
        "size": expected_output["expected_size"],
        "sha256": expected_output["expected_sha256"],
    }
    if actual_output != expected_lock:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary ISO bytes do not match lock"
        )
    if {
        "size": output_iso["size"],
        "sha256": output_iso["sha256"],
    } != expected_lock:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary ISO report lock drift"
        )
    if layout["member_manifest_sha256"] != expected_output[
        "expected_member_manifest_sha256"
    ]:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary member-manifest lock drift"
        )

    replacements = config["replacements"]
    if len(replacements) != 1:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary ISO must replace exactly one member"
        )
    replacement = replacements[0]
    if replacement["member"] != component["target"]["member"]:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary target member differs from component"
        )
    replacement_lock = {
        "size": replacement["size"],
        "sha256": replacement["sha256"],
    }
    if replacement_lock != component["outputs"]["archive"]:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary replacement differs from component"
        )
    report_replacements = iso_report.get("replacements")
    if not isinstance(report_replacements, list) or len(
        report_replacements
    ) != 1:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary ISO report replacement set drift"
        )
    report_replacement = report_replacements[0]
    if {
        "member": report_replacement["member"],
        "size": report_replacement["size"],
        "sha256": report_replacement["sha256"],
    } != {
        "member": replacement["member"],
        **replacement_lock,
    }:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary ISO report replacement lock drift"
        )
    if iso_report["independent_udf_reads"].get(
        replacement["member"]
    ) != replacement_lock["sha256"]:
        raise UiInfoAtlasMapCanaryIsoError(
            "mapping-canary independent UDF reread mismatch"
        )

    expected_segments = [
        {
            "first_member": config["layout"]["first_shifted_member"],
            "shift_sectors": config["layout"]["expected_shift_sectors"],
        }
    ]
    acceptance = {
        "component_manifest_validated": True,
        "single_replacement_matches_component": True,
        "iso_size_and_sha256_pinned": True,
        "member_paths_exact": layout["member_paths_exact"] is True,
        "member_order_exact": layout["member_order_exact"] is True,
        "unchanged_member_bytes_exact": (
            layout["unchanged_member_bytes_exact"] is True
        ),
        "replacement_bytes_exact": (
            layout["replacement_bytes_exact"] is True
        ),
        "system_cnf_exact": layout["system_cnf_exact"] is True,
        "shift_segments_exact": (
            layout["shift_segments"] == expected_segments
        ),
        "zero_shifted_members": layout["shifted_member_count"] == 0,
        "replacement_independently_reread": True,
        "pcsx2_media_type_dvd": (
            output_iso["pcsx2_v263_image_type"] == "DVD"
        ),
        "udf_nsr02": (
            output_iso["udf_volume_recognition_sequence"] == "NSR02"
        ),
    }
    if not all(acceptance.values()):
        raise UiInfoAtlasMapCanaryIsoError(
            f"mapping-canary static ISO acceptance failed: {acceptance}"
        )

    return {
        "schema_version": 1,
        "status": "static_mapping_iso_validated_runtime_not_tested",
        "content_policy": (
            "Hashes, coordinates, counts, paths and runtime gates only; "
            "no game bytes, localized text or preview PNGs are embedded."
        ),
        "profile_id": config["profile_id"],
        "scope": component["scope"],
        "component": {
            "manifest": file_lock(component_manifest_path),
            "target": component["target"],
            "outputs": component["outputs"],
            "acceptance": component["acceptance"],
        },
        "iso_build": {
            "config": file_lock(config_path),
            "report": file_lock(iso_report_path),
            "path": config["output"]["path"],
            "output": actual_output,
            "member_count": output_iso["member_count"],
            "unchanged_member_count": layout["unchanged_member_count"],
            "shifted_member_count": layout["shifted_member_count"],
            "shift_segments": layout["shift_segments"],
            "member_manifest_sha256": layout[
                "member_manifest_sha256"
            ],
            "pcsx2_v263_image_type": output_iso[
                "pcsx2_v263_image_type"
            ],
            "udf_volume_recognition_sequence": output_iso[
                "udf_volume_recognition_sequence"
            ],
            "replacement": {
                "member": replacement["member"],
                **replacement_lock,
                "independent_udf_reread_exact": True,
            },
        },
        "static_acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "required_iso_sha256": actual_output["sha256"],
            "required_emulator": "PCSX2 v2.6.3",
            "required_routes": [
                "fresh_process_boot_exact_iso",
                "open_unit_information_for_two_units",
                "visit_pilot_weapon_parts_skill_and_spirit_subpages",
                "capture_visible_missing_ship_label_if_loaded",
                "capture_texture_dump_delta_for_the_same_mask",
            ],
            "expected_visual_delta": {
                "semantic_locator": "SHIP",
                "effect": "the top-row SHIP locator is absent",
            },
            "expected_texture_delta": {
                "chunk_index": component["target"]["chunk_index"],
                "mask": component["target"]["mask"],
                "changed_pixel_count": component["injection"][
                    "changed_pixel_count"
                ],
                "changed_pixel_indexes_sha256": component["target"][
                    "mask_audit"
                ]["changed_pixel_indexes_sha256"],
            },
            "promotion_rule": (
                "Promote KVMDATA chunk 2 to a runtime information-page "
                "mapping only when a matching screenshot and texture-dump "
                "delta satisfy both expected deltas."
            ),
        },
    }


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    component_manifest_path = args.component_manifest.resolve()
    manifest_path = args.manifest.resolve()
    report_path = require_work_output(args.report.resolve(), WORK_ROOT)
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        report = build_report(config_path, component_manifest_path)
    except (
        KeyError,
        OSError,
        RuntimeError,
        ValueError,
        UiInfoAtlasMapCanaryIsoError,
    ) as error:
        raise SystemExit(str(error)) from error

    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file():
            raise SystemExit(
                "mapping-canary runtime manifest is missing; review and "
                "use --refresh-manifest"
            )
        if load_json(manifest_path) != report:
            raise SystemExit(
                "mapping-canary runtime manifest drift; review and use "
                "--refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI information-atlas mapping-canary ISO verified:",
        f"members={report['iso_build']['member_count']}",
        f"sha256={report['iso_build']['output']['sha256']}",
        "runtime=not-tested",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
