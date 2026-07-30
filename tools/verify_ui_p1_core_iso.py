#!/usr/bin/env python3
"""Bind a configured integrated core UI component to static ISO evidence."""

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


def build_runtime_projection(config: dict, actual_output: dict) -> dict:
    evidence = config.get("runtime_evidence")
    if config.get("profile_id") == "ui-p2-default-names-first-five":
        required_routes = [
            "fresh_boot_default_name_is_chinese",
            "accept_default_name_flows_into_story_token",
            "edit_name_overrides_story_token",
            "stages_001_through_005_story_dialogue",
        ]
    else:
        required_routes = [
            "title_all_four_selected_and_unselected_states",
            "opening_player_setup_default_and_edited_name",
            "first_intermission_core_menu_routes",
            "two_unit_information_page_matrix",
            "battle_command_and_conditions",
            "search_zero_and_multiple_results",
            "world_history_scroll_start_middle_end",
        ]
    if evidence is None:
        pending_gates = (
            [
                "fresh_process_boot_exact_iso",
                "default_name_visual_acceptance",
                "edited_name_visual_acceptance",
                "stages_001_through_005_visual_acceptance",
                "zero_tlb_miss",
            ]
            if config.get("profile_id")
            == "ui-p2-default-names-first-five"
            else [
                "fresh_process_boot_exact_iso",
                "pine_running_and_decoded_font_exact",
                "new_raw_trail_glyph_classes_visible",
                "no_clipping_overlap_or_missing_glyphs",
                "zero_tlb_miss",
            ]
        )
        return {
            "status": "not_tested",
            "required_iso_sha256": actual_output["sha256"],
            "required_emulator": "PCSX2 v2.6.3",
            "required_routes": required_routes,
            "pending_gates": pending_gates,
        }
    if not isinstance(evidence, dict):
        raise UiP1CoreIsoError("runtime_evidence must be an object")
    raw_path = evidence.get("boot_smoke_report")
    if not isinstance(raw_path, str) or not raw_path:
        raise UiP1CoreIsoError("runtime_evidence needs boot_smoke_report")
    receipt_path = (PROJECT_ROOT / raw_path).resolve()
    try:
        receipt_path.relative_to(
            PROJECT_ROOT / "work/runtime/iso-incremental"
        )
    except ValueError as error:
        raise UiP1CoreIsoError(
            "boot-smoke receipt leaves work/runtime/iso-incremental"
        ) from error
    if not receipt_path.is_file():
        raise UiP1CoreIsoError("boot-smoke receipt is missing")
    receipt = load_json(receipt_path)
    emulator = receipt.get("emulator")
    log = receipt.get("log")
    checks = receipt.get("checks")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "passed"
        or receipt.get("iso")
        != {
            "path": config["output"]["path"],
            **actual_output,
        }
        or not isinstance(emulator, dict)
        or emulator.get("pine_version") != "PCSX2 v2.6.3"
        or emulator.get("game_id") != "SLPS-25887"
        or emulator.get("pine_status") != 0
        or emulator.get("fresh_process") is not True
        or emulator.get("process_exit_code_after_sigint") != 0
        or not isinstance(log, dict)
        or log.get("dvd_recognized") is not True
        or log.get("elf_executing") is not True
        or log.get("no_tlb_miss") is not True
        or log.get("tlb_miss_count") != 0
        or not isinstance(checks, dict)
        or not checks
        or not all(checks.values())
    ):
        raise UiP1CoreIsoError(
            "boot-smoke receipt does not prove the exact integrated ISO"
        )
    pending_gates = (
        [
            "default_name_visual_acceptance",
            "edited_name_visual_acceptance",
            "stages_001_through_005_visual_acceptance",
        ]
        if config.get("profile_id")
        == "ui-p2-default-names-first-five"
        else [
            "opening_player_setup_visual_acceptance",
            "pine_decoded_font_exact",
            "new_raw_trail_glyph_classes_visible",
            "no_clipping_overlap_or_missing_glyphs",
        ]
    )
    return {
        "status": "boot_smoke_passed_visual_not_tested",
        "required_iso_sha256": actual_output["sha256"],
        "required_emulator": "PCSX2 v2.6.3",
        "receipt": file_lock(receipt_path),
        "fresh_process": True,
        "game_id": "SLPS-25887",
        "pine_status": 0,
        "pine_state": "Running",
        "dvd_recognized": True,
        "elf_executing": True,
        "tlb_miss_count": 0,
        "required_routes": required_routes,
        "pending_gates": pending_gates,
        "boundary": (
            "Fresh-process boot proves DVD, ELF, PINE and zero logged TLB "
            "misses only; no route navigation or visual acceptance is claimed."
        ),
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
    profile_id = config.get("profile_id")
    if profile_id not in {
        "ui-p1-core",
        "ui-p2-core",
        "ui-p2-default-names-first-five",
    }:
        raise UiP1CoreIsoError("unexpected integrated UI core ISO profile")
    configured_component = config.get("component_validation_manifest")
    if configured_component is not None and (
        PROJECT_ROOT / configured_component
    ).resolve() != component_manifest_path.resolve():
        raise UiP1CoreIsoError(
            "component manifest does not match the ISO profile"
        )
    required_component_status = (
        "integrated_ui_p2_default_names_first_five_component_"
        "validated_runtime_pending"
        if profile_id == "ui-p2-default-names-first-five"
        else "integrated_component_validated_iso_runtime_pending"
    )
    if component.get("status") != required_component_status:
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

    if profile_id == "ui-p2-default-names-first-five":
        member_to_output = {
            member: member
            for member in component["composition"]["members"]
        }
    else:
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
        component_output = component_outputs[output_name]
        component_lock = {
            "size": component_output["size"],
            "sha256": component_output["sha256"],
        }
        if actual != component_lock:
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

    runtime = build_runtime_projection(config, actual_output)
    return {
        "schema_version": 1,
        "status": (
            "integrated_iso_boot_smoke_passed_visual_pending"
            if runtime["status"] == "boot_smoke_passed_visual_not_tested"
            else "static_integrated_iso_validated_runtime_pending"
        ),
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
        "runtime": runtime,
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
        "UI core ISO verified:",
        f"members={report['iso_build']['member_count']}",
        f"sha256={report['iso_build']['output']['sha256']}",
        f"runtime={report['runtime']['status']}",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
