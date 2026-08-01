#!/usr/bin/env python3
"""Bind the integrated P2 UI and first-five component to static ISO evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    from srwz.diagnostics import require_work_output
except ModuleNotFoundError:
    from tools.srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "config/iso/ui-p2-first-five-atlas-test-build.json"
)
DEFAULT_COMPONENT_MANIFEST = (
    PROJECT_ROOT
    / "manifests/ui-p2-first-five-atlas-test-validation.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "manifests/ui-p2-first-five-atlas-test-runtime-validation.json"
)
DEFAULT_REPORT = (
    WORK_ROOT
    / "review/ui-p2-first-five-atlas-test/iso-validation.json"
)


class UiTestCandidateIsoError(RuntimeError):
    """The integrated UI test ISO does not match its component evidence."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UiTestCandidateIsoError(
            f"JSON root must be an object: {path}"
        )
    return value


def file_lock(path: Path) -> dict:
    return {
        "path": str(path.resolve().relative_to(PROJECT_ROOT)),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_runtime_projection(
    config: dict,
    actual_output: dict,
    component: dict,
) -> dict:
    required_scene_families = component["runtime"][
        "required_scene_families"
    ]
    evidence = config.get("runtime_evidence")
    if evidence is None:
        return {
            "status": "not_tested",
            "required_iso_sha256": actual_output["sha256"],
            "required_emulator": "PCSX2 v2.6.3",
            "required_scene_families": required_scene_families,
            "isolated_atlas_mapping_profiles_remain_required": True,
            "pending_gates": [
                "fresh_process_boot_exact_iso",
                "pine_running_and_decoded_font_exact",
                "all_required_scene_families_visited",
                "no_clipping_overlap_or_missing_glyphs",
                "zero_tlb_miss",
                "five_isolated_atlas_scene_mapping_receipts",
            ],
        }
    if not isinstance(evidence, dict):
        raise UiTestCandidateIsoError("runtime_evidence must be an object")
    raw_path = evidence.get("boot_smoke_report")
    if not isinstance(raw_path, str) or not raw_path:
        raise UiTestCandidateIsoError(
            "runtime_evidence needs boot_smoke_report"
        )
    receipt_path = (PROJECT_ROOT / raw_path).resolve()
    try:
        receipt_path.relative_to(
            PROJECT_ROOT / "work/runtime/iso-incremental"
        )
    except ValueError as error:
        raise UiTestCandidateIsoError(
            "boot-smoke receipt leaves work/runtime/iso-incremental"
        ) from error
    if not receipt_path.is_file():
        raise UiTestCandidateIsoError("boot-smoke receipt is missing")
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
        raise UiTestCandidateIsoError(
            "boot-smoke receipt does not prove the exact integrated ISO"
        )
    prior_failure = evidence.get("prior_failure")
    prior_failure_projection = None
    if prior_failure is not None:
        if not isinstance(prior_failure, dict):
            raise UiTestCandidateIsoError("prior_failure must be an object")
        raw_failure_log = prior_failure.get("log")
        expected_failure_sha256 = prior_failure.get("log_sha256")
        first_tlb_miss = prior_failure.get("first_tlb_miss")
        if (
            not isinstance(raw_failure_log, str)
            or not raw_failure_log
            or not isinstance(expected_failure_sha256, str)
            or len(expected_failure_sha256) != 64
            or not isinstance(first_tlb_miss, str)
            or not first_tlb_miss
        ):
            raise UiTestCandidateIsoError(
                "prior_failure needs a locked log and first TLB miss"
            )
        failure_log_path = (PROJECT_ROOT / raw_failure_log).resolve()
        try:
            failure_log_path.relative_to(
                PROJECT_ROOT / "work/runtime/iso-incremental"
            )
        except ValueError as error:
            raise UiTestCandidateIsoError(
                "prior-failure log leaves work/runtime/iso-incremental"
            ) from error
        if (
            not failure_log_path.is_file()
            or sha256_file(failure_log_path) != expected_failure_sha256
            or first_tlb_miss
            not in failure_log_path.read_text(
                encoding="utf-8", errors="replace"
            )
        ):
            raise UiTestCandidateIsoError(
                "prior-failure log does not match its locked TLB evidence"
            )
        prior_failure_projection = {
            "iso_sha256": prior_failure["iso_sha256"],
            "trigger": prior_failure["trigger"],
            "log": file_lock(failure_log_path),
            "first_tlb_miss": first_tlb_miss,
            "disposition": (
                "replaced_by_zero_lba_shift_candidate_runtime_retest_pending"
            ),
        }
    post_confirmation = evidence.get("post_confirmation")
    post_confirmation_projection = None
    if post_confirmation is not None:
        if not isinstance(post_confirmation, dict):
            raise UiTestCandidateIsoError(
                "post_confirmation must be an object"
            )
        raw_log = post_confirmation.get("log")
        expected_log_sha256 = post_confirmation.get("log_sha256")
        minimum_play_seconds = post_confirmation.get(
            "minimum_play_seconds"
        )
        trigger = post_confirmation.get("trigger")
        raw_screenshots = post_confirmation.get("screenshots")
        if (
            not isinstance(raw_log, str)
            or not raw_log
            or not isinstance(expected_log_sha256, str)
            or len(expected_log_sha256) != 64
            or not isinstance(minimum_play_seconds, int)
            or isinstance(minimum_play_seconds, bool)
            or minimum_play_seconds <= 0
            or not isinstance(trigger, str)
            or not trigger
            or not isinstance(raw_screenshots, list)
            or not raw_screenshots
        ):
            raise UiTestCandidateIsoError(
                "post_confirmation evidence contract is invalid"
            )
        log_path = (PROJECT_ROOT / raw_log).resolve()
        try:
            log_path.relative_to(
                PROJECT_ROOT / "work/runtime/iso-incremental"
            )
        except ValueError as error:
            raise UiTestCandidateIsoError(
                "post-confirmation log leaves work/runtime/iso-incremental"
            ) from error
        if (
            not log_path.is_file()
            or sha256_file(log_path) != expected_log_sha256
        ):
            raise UiTestCandidateIsoError(
                "post-confirmation log does not match its lock"
            )
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        exact_iso_path = str(
            (PROJECT_ROOT / config["output"]["path"]).resolve()
        )
        play_seconds = [
            int(value)
            for value in re.findall(
                r"Add (\d+) seconds play time to SLPS-25887",
                log_text,
            )
        ]
        if (
            exact_iso_path not in log_text
            or "Image type  = DVD" not in log_text
            or "ELF cdrom0:\\SLPS_258.87;1 with entry point" not in log_text
            or " is executing." not in log_text
            or "TLB Miss" in log_text
            or not play_seconds
            or max(play_seconds) < minimum_play_seconds
        ):
            raise UiTestCandidateIsoError(
                "post-confirmation log does not prove the exact ISO runtime"
            )
        screenshot_projection = []
        seen_scene_ids = set()
        for raw in raw_screenshots:
            if not isinstance(raw, dict):
                raise UiTestCandidateIsoError(
                    "post-confirmation screenshot entry is malformed"
                )
            scene_id = raw.get("scene_id")
            raw_screenshot_path = raw.get("path")
            expected_screenshot_sha256 = raw.get("sha256")
            verdict = raw.get("verdict")
            if (
                not isinstance(scene_id, str)
                or not scene_id
                or scene_id in seen_scene_ids
                or not isinstance(raw_screenshot_path, str)
                or not raw_screenshot_path.endswith(".png")
                or not isinstance(expected_screenshot_sha256, str)
                or len(expected_screenshot_sha256) != 64
                or not isinstance(verdict, str)
                or not verdict
            ):
                raise UiTestCandidateIsoError(
                    "post-confirmation screenshot contract is invalid"
                )
            screenshot_path = (
                PROJECT_ROOT / raw_screenshot_path
            ).resolve()
            try:
                screenshot_path.relative_to(
                    PROJECT_ROOT / "work/runtime/iso-incremental"
                )
            except ValueError as error:
                raise UiTestCandidateIsoError(
                    "post-confirmation screenshot leaves runtime evidence"
                ) from error
            if (
                not screenshot_path.is_file()
                or sha256_file(screenshot_path)
                != expected_screenshot_sha256
            ):
                raise UiTestCandidateIsoError(
                    "post-confirmation screenshot does not match its lock"
                )
            seen_scene_ids.add(scene_id)
            screenshot_projection.append(
                {
                    "scene_id": scene_id,
                    "file": file_lock(screenshot_path),
                    "verdict": verdict,
                }
            )
        post_confirmation_projection = {
            "trigger": trigger,
            "log": file_lock(log_path),
            "exact_iso_path_in_log": True,
            "dvd_recognized": True,
            "elf_executing": True,
            "tlb_miss_count": 0,
            "play_seconds": max(play_seconds),
            "screenshots": screenshot_projection,
        }
        if prior_failure_projection is not None:
            prior_failure_projection["disposition"] = (
                "reproduced_then_fixed_by_zero_lba_shift_candidate_"
                "verified_past_trigger"
            )
    runtime = {
        "status": (
            "post_confirmation_runtime_passed_visual_partial"
            if post_confirmation_projection is not None
            else "boot_smoke_passed_visual_not_tested"
        ),
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
        "required_scene_families": required_scene_families,
        "isolated_atlas_mapping_profiles_remain_required": True,
        "pending_gates": [
            "pine_decoded_font_exact",
            "all_required_scene_families_visited",
            "no_clipping_overlap_or_missing_glyphs",
            "five_isolated_atlas_scene_mapping_receipts",
        ],
        "boundary": (
            (
                "The exact ISO was observed past protagonist confirmation "
                "into stage 001 with zero logged TLB misses. Four hash-locked "
                "screenshots sample the first-stage conditions, system "
                "settings, leader-effect search and special-skill search "
                "surfaces. This is partial visual evidence, not acceptance of "
                "every required scene family or all remaining Japanese text."
            )
            if post_confirmation_projection is not None
            else (
                "Fresh-process boot proves DVD, ELF, PINE and zero logged TLB "
                "misses before protagonist confirmation only; the transition "
                "from confirmation into stage 001 still requires an exact-ISO "
                "runtime retest, and no visual acceptance is claimed."
            )
        ),
    }
    if post_confirmation_projection is None:
        runtime["pending_gates"].insert(
            0,
            "post_protagonist_confirmation_stage_load_without_tlb",
        )
    if prior_failure_projection is not None:
        runtime["prior_failure"] = prior_failure_projection
    if post_confirmation_projection is not None:
        runtime["post_confirmation"] = post_confirmation_projection
    return runtime


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
    if (
        not isinstance(profile_id, str)
        or not profile_id
        or component.get("profile_id") != profile_id
    ):
        raise UiTestCandidateIsoError("UI test ISO/component profile drift")
    configured_component = config.get("component_validation_manifest")
    if (
        not isinstance(configured_component, str)
        or (PROJECT_ROOT / configured_component).resolve()
        != component_manifest_path.resolve()
    ):
        raise UiTestCandidateIsoError(
            "component manifest does not match the ISO profile"
        )
    required_component_status = config.get(
        "component_required_status",
        (
            "integrated_ui_p2_first_five_atlas_test_component_"
            "validated_runtime_pending"
        ),
    )
    if component.get("status") != required_component_status:
        raise UiTestCandidateIsoError(
            "integrated UI test component is not validated"
        )

    iso_report_path = PROJECT_ROOT / config["output"]["report"]
    iso_path = PROJECT_ROOT / config["output"]["path"]
    if not iso_report_path.is_file() or not iso_path.is_file():
        raise UiTestCandidateIsoError(
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
        raise UiTestCandidateIsoError(
            "integrated ISO bytes do not match the pinned lock"
        )
    if {
        "size": output_iso["size"],
        "sha256": output_iso["sha256"],
    } != expected_lock:
        raise UiTestCandidateIsoError("integrated ISO report lock drift")
    if layout["member_manifest_sha256"] != expected_output[
        "expected_member_manifest_sha256"
    ]:
        raise UiTestCandidateIsoError("member-manifest lock drift")

    component_outputs = component.get("outputs")
    if not isinstance(component_outputs, dict):
        raise UiTestCandidateIsoError("component output map is missing")
    replacements = {}
    for replacement in config["replacements"]:
        member = replacement["member"]
        component_output = component_outputs.get(member)
        if not isinstance(component_output, dict):
            raise UiTestCandidateIsoError(
                f"unexpected integrated ISO replacement: {member}"
            )
        actual = {
            "size": replacement["size"],
            "sha256": replacement["sha256"],
        }
        expected_component = {
            "size": component_output["size"],
            "sha256": component_output["sha256"],
        }
        if actual != expected_component:
            raise UiTestCandidateIsoError(
                f"{member} does not match integrated component"
            )
        if replacement["source"] != component_output["path"]:
            raise UiTestCandidateIsoError(
                f"{member} source path does not match integrated component"
            )
        if iso_report["independent_udf_reads"].get(member) != actual[
            "sha256"
        ]:
            raise UiTestCandidateIsoError(
                f"{member} independent UDF reread mismatch"
            )
        replacements[member] = {
            **actual,
            "owner": component_output["owner"],
            "independent_udf_reread_exact": True,
        }
    if set(replacements) != set(component_outputs):
        raise UiTestCandidateIsoError(
            "integrated replacement set is incomplete"
        )

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
        "shift_segments_exact": layout["shift_segments"]
        == config["layout"]["shift_segments"],
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
        "isolated_atlas_mapping_profiles_still_required": (
            component["runtime"][
                "isolated_atlas_mapping_profiles_remain_required"
            ]
            is True
        ),
    }
    if not all(acceptance.values()):
        raise UiTestCandidateIsoError(
            f"integrated static ISO acceptance failed: {acceptance}"
        )

    manifest_status = config.get(
        "runtime_manifest_status",
        (
            "static_integrated_ui_p2_first_five_atlas_test_iso_"
            "validated_runtime_pending"
        ),
    )
    if not isinstance(manifest_status, str) or not manifest_status:
        raise UiTestCandidateIsoError("integrated runtime manifest status is invalid")
    runtime = build_runtime_projection(config, actual_output, component)
    return {
        "schema_version": 1,
        "status": manifest_status,
        "content_policy": (
            "Hashes, counts, paths and runtime gates only; no game bytes "
            "or localized text are embedded."
        ),
        "profile_id": config["profile_id"],
        "component": {
            "manifest": file_lock(component_manifest_path),
            "profile_id": component["profile_id"],
            "composition": component["composition"],
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
    except (KeyError, OSError, UiTestCandidateIsoError) as error:
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
        "Integrated UI test ISO verified:",
        f"members={report['iso_build']['member_count']}",
        f"sha256={report['iso_build']['output']['sha256']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
