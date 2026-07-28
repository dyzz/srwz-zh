#!/usr/bin/env python3
"""Bind the integrated P1 core UI component to its static ISO evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/iso/ui-p1-core-build.json"
DEFAULT_COMPONENT_MANIFEST = (
    PROJECT_ROOT / "manifests/ui-p1-core-validation.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "manifests/ui-p1-core-runtime-validation.json"
)
DEFAULT_REPORT = WORK_ROOT / "review/ui-p1-core-iso-validation.json"


class UiP1CoreIsoError(RuntimeError):
    """The integrated UI ISO does not match its component evidence."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UiP1CoreIsoError(f"JSON root must be an object: {path}")
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
    config = load_json(config_path)
    component = load_json(component_manifest_path)
    if config.get("profile_id") != "ui-p1-core":
        raise UiP1CoreIsoError("unexpected UI P1 core ISO profile")
    if component.get("status") != (
        "integrated_component_validated_iso_runtime_pending"
    ):
        raise UiP1CoreIsoError("integrated UI component is not validated")

    iso_report_path = PROJECT_ROOT / config["output"]["report"]
    iso_path = PROJECT_ROOT / config["output"]["path"]
    if not iso_report_path.is_file() or not iso_path.is_file():
        raise UiP1CoreIsoError(
            "integrated ISO or report is missing; run build_canary_iso.py"
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
        raise UiP1CoreIsoError("integrated ISO bytes do not match lock")
    if {
        "size": output_iso["size"],
        "sha256": output_iso["sha256"],
    } != expected_lock:
        raise UiP1CoreIsoError("integrated ISO report lock drift")
    if layout["member_manifest_sha256"] != expected_output[
        "expected_member_manifest_sha256"
    ]:
        raise UiP1CoreIsoError("member-manifest lock drift")

    member_to_output = {
        "SLPS_258.87": "slps",
        "DATA/COMPDATA.BN": "compdata",
        "DATA/MTV_PROS.BIN": "mtv_pros",
        "DATA/VT1.BIN": "vt1",
    }
    component_outputs = component["outputs"]
    replacements = {}
    for replacement in config["replacements"]:
        member = replacement["member"]
        output_name = member_to_output.get(member)
        if output_name is None:
            raise UiP1CoreIsoError(
                f"unexpected integrated ISO replacement: {member}"
            )
        actual = {
            "size": replacement["size"],
            "sha256": replacement["sha256"],
        }
        if actual != component_outputs[output_name]:
            raise UiP1CoreIsoError(
                f"{member} does not match integrated component"
            )
        if iso_report["independent_udf_reads"].get(member) != actual[
            "sha256"
        ]:
            raise UiP1CoreIsoError(
                f"{member} independent UDF reread mismatch"
            )
        replacements[member] = {
            **actual,
            "component_output": output_name,
            "independent_udf_reread_exact": True,
        }
    if set(replacements) != set(member_to_output):
        raise UiP1CoreIsoError("integrated replacement set is incomplete")

    acceptance = {
        "component_manifest_validated": True,
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
        "shift_segments_exact": layout["shift_segments"] == config[
            "layout"
        ]["shift_segments"],
        "pcsx2_media_type_dvd": (
            output_iso["pcsx2_v263_image_type"] == "DVD"
        ),
        "udf_nsr02": (
            output_iso["udf_volume_recognition_sequence"] == "NSR02"
        ),
        "all_replacements_independently_reread": all(
            item["independent_udf_reread_exact"]
            for item in replacements.values()
        ),
    }
    if not all(acceptance.values()):
        raise UiP1CoreIsoError(
            f"integrated static ISO acceptance failed: {acceptance}"
        )

    return {
        "schema_version": 1,
        "status": "static_integrated_iso_validated_runtime_pending",
        "content_policy": (
            "Hashes, counts, paths and runtime gates only; no game bytes "
            "or localized text are embedded."
        ),
        "profile_id": config["profile_id"],
        "component": {
            "manifest": file_lock(component_manifest_path),
            "profile_id": component["profile_id"],
            "outputs": component_outputs,
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
            "replacements": replacements,
        },
        "static_acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "required_iso_sha256": actual_output["sha256"],
            "required_emulator": "PCSX2 v2.6.3",
            "required_routes": [
                "title_all_four_selected_and_unselected_states",
                "opening_player_setup_default_and_edited_name",
                "first_intermission_core_menu_routes",
                "two_unit_information_page_matrix",
                "battle_command_and_conditions",
                "search_zero_and_multiple_results",
                "world_history_scroll_start_middle_end",
            ],
            "pending_gates": [
                "fresh_process_boot_exact_iso",
                "pine_running_and_decoded_font_exact",
                "new_raw_trail_glyph_classes_visible",
                "no_clipping_overlap_or_missing_glyphs",
                "zero_tlb_miss",
            ],
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
    except (KeyError, OSError, UiP1CoreIsoError) as error:
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
                "integrated runtime manifest missing; review and use "
                "--refresh-manifest"
            )
        if load_json(manifest_path) != report:
            raise SystemExit(
                "integrated runtime manifest drift; review and use "
                "--refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI P1 core ISO verified:",
        f"members={report['iso_build']['member_count']}",
        f"sha256={report['iso_build']['output']['sha256']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
