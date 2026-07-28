#!/usr/bin/env python3
"""Bind one UI-atlas mapping canary to its static ISO evidence."""

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


class UiAtlasMapCanaryIsoError(RuntimeError):
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
        raise UiAtlasMapCanaryIsoError(
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
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def build_report(config_path: Path, component_manifest_path: Path) -> dict:
    config = load_config(config_path)
    component = load_json(component_manifest_path)
    if component.get("status") != (
        "static_component_validated_runtime_mapping_pending"
    ):
        raise UiAtlasMapCanaryIsoError(
            "UI-atlas mapping-canary component is not validated"
        )
    if component.get("profile_id") != config["profile_id"]:
        raise UiAtlasMapCanaryIsoError(
            "component and ISO profile identifiers differ"
        )

    iso_report_path = PROJECT_ROOT / config["output"]["report"]
    iso_path = PROJECT_ROOT / config["output"]["path"]
    if not iso_report_path.is_file() or not iso_path.is_file():
        raise UiAtlasMapCanaryIsoError(
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
        raise UiAtlasMapCanaryIsoError(
            "mapping-canary ISO bytes do not match lock"
        )
    if {
        "size": output_iso["size"],
        "sha256": output_iso["sha256"],
    } != expected_lock:
        raise UiAtlasMapCanaryIsoError(
            "mapping-canary ISO report lock drift"
        )
    if layout["member_manifest_sha256"] != expected_output[
        "expected_member_manifest_sha256"
    ]:
        raise UiAtlasMapCanaryIsoError(
            "mapping-canary member-manifest lock drift"
        )

    replacements = config["replacements"]
    if len(replacements) != 1:
        raise UiAtlasMapCanaryIsoError(
            "mapping-canary ISO must replace exactly one member"
        )
    replacement = replacements[0]
    if replacement["member"] != component["target"]["member"]:
        raise UiAtlasMapCanaryIsoError(
            "mapping-canary target member differs from component"
        )
    replacement_lock = {
        "size": replacement["size"],
        "sha256": replacement["sha256"],
    }
    if replacement_lock != component["outputs"]["archive"]:
        raise UiAtlasMapCanaryIsoError(
            "mapping-canary replacement differs from component"
        )
    report_replacements = iso_report.get("replacements")
    if not isinstance(report_replacements, list) or len(
        report_replacements
    ) != 1:
        raise UiAtlasMapCanaryIsoError(
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
        raise UiAtlasMapCanaryIsoError(
            "mapping-canary ISO report replacement lock drift"
        )
    if iso_report["independent_udf_reads"].get(
        replacement["member"]
    ) != replacement_lock["sha256"]:
        raise UiAtlasMapCanaryIsoError(
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
        raise UiAtlasMapCanaryIsoError(
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
            "required_routes": component["runtime"]["required_routes"],
            "expected_visual_delta": {
                "semantic_locator": component["target"][
                    "semantic_locator"
                ],
                "effect": component["runtime"][
                    "expected_visual_effect"
                ],
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
            "promotion_rule": component["runtime"]["promotion_rule"],
        },
    }


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = load_config(config_path)
    component_manifest_path = (
        args.component_manifest
        or PROJECT_ROOT / config["component_validation_manifest"]
    ).resolve()
    manifest_path = (
        args.manifest
        or PROJECT_ROOT / config["runtime_evidence_manifest"]
    ).resolve()
    report_path = require_work_output(
        (
            args.report
            or WORK_ROOT
            / "review"
            / config["profile_id"]
            / "iso-validation.json"
        ).resolve(),
        WORK_ROOT,
    )
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        report = build_report(config_path, component_manifest_path)
    except (
        KeyError,
        OSError,
        RuntimeError,
        ValueError,
        UiAtlasMapCanaryIsoError,
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
        "UI atlas mapping-canary ISO verified:",
        f"profile={report['profile_id']}",
        f"members={report['iso_build']['member_count']}",
        f"sha256={report['iso_build']['output']['sha256']}",
        "runtime=not-tested",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
