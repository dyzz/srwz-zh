#!/usr/bin/env python3
"""Bind the complete P1 world-history component to its static ISO evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config/iso/ui-p1-world-history-build.json"
)
DEFAULT_COMPONENT_MANIFEST = (
    PROJECT_ROOT / "manifests/ui-p1-world-history-validation.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "manifests/ui-p1-world-history-runtime-validation.json"
)
DEFAULT_REPORT = (
    WORK_ROOT / "review/ui-p1-world-history-iso-validation.json"
)


class WorldHistoryIsoError(RuntimeError):
    """Static ISO evidence does not match the pinned P1 component."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise WorldHistoryIsoError(f"JSON root must be an object: {path}")
    return value


def file_lock(path: Path) -> dict:
    payload = path.read_bytes()
    return {
        "path": str(path.resolve().relative_to(PROJECT_ROOT)),
        "size": len(payload),
        "sha256": sha256_bytes(payload),
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
    if profile_id != "ui-p1-world-history":
        raise WorldHistoryIsoError(
            f"unexpected ISO profile_id: {profile_id!r}"
        )
    if component.get("status") != (
        "offline_component_validated_runtime_not_tested"
    ):
        raise WorldHistoryIsoError("P1 component manifest is not validated")

    iso_report_path = PROJECT_ROOT / config["output"]["report"]
    iso_path = PROJECT_ROOT / config["output"]["path"]
    if not iso_report_path.is_file():
        raise WorldHistoryIsoError(
            "ISO report is missing; run build_canary_iso.py first"
        )
    if not iso_path.is_file():
        raise WorldHistoryIsoError(
            "ISO is missing; run build_canary_iso.py first"
        )
    iso_report = load_json(iso_report_path)
    output_iso = iso_report.get("output_iso", {})
    layout = iso_report.get("layout", {})
    expected_output = config["output"]
    expected_iso = {
        "size": expected_output["expected_size"],
        "sha256": expected_output["expected_sha256"],
    }
    actual_iso = {
        "size": iso_path.stat().st_size,
        "sha256": sha256_file(iso_path),
    }
    if actual_iso != expected_iso:
        raise WorldHistoryIsoError(
            f"ISO bytes do not match pinned output: {actual_iso}"
        )
    if {
        "size": output_iso.get("size"),
        "sha256": output_iso.get("sha256"),
    } != expected_iso:
        raise WorldHistoryIsoError("ISO report output lock drift")
    if layout.get("member_manifest_sha256") != expected_output[
        "expected_member_manifest_sha256"
    ]:
        raise WorldHistoryIsoError("ISO member-manifest lock drift")

    member_to_component = {
        "SLPS_258.87": "slps",
        "DATA/MTV_PROS.BIN": "mtv_pros",
        "DATA/VT1.BIN": "vt1",
    }
    component_outputs = component.get("outputs", {})
    replacement_checks = {}
    for replacement in config["replacements"]:
        member = replacement["member"]
        output_name = member_to_component.get(member)
        if output_name is None:
            raise WorldHistoryIsoError(
                f"unexpected ISO replacement: {member}"
            )
        expected = component_outputs.get(output_name)
        actual = {
            "size": replacement["size"],
            "sha256": replacement["sha256"],
        }
        if actual != expected:
            raise WorldHistoryIsoError(
                f"{member} does not match component manifest"
            )
        if iso_report["independent_udf_reads"].get(member) != actual[
            "sha256"
        ]:
            raise WorldHistoryIsoError(
                f"{member} independent UDF reread mismatch"
            )
        replacement_checks[member] = {
            **actual,
            "component_output": output_name,
            "independent_udf_reread_exact": True,
        }

    acceptance = {
        "component_manifest_validated": True,
        "iso_size_and_sha256_pinned": actual_iso == expected_iso,
        "member_paths_exact": layout.get("member_paths_exact") is True,
        "member_order_exact": layout.get("member_order_exact") is True,
        "unchanged_member_bytes_exact": (
            layout.get("unchanged_member_bytes_exact") is True
        ),
        "replacement_bytes_exact": (
            layout.get("replacement_bytes_exact") is True
        ),
        "system_cnf_exact": layout.get("system_cnf_exact") is True,
        "pcsx2_media_type_dvd": (
            output_iso.get("pcsx2_v263_image_type") == "DVD"
        ),
        "udf_nsr02": (
            output_iso.get("udf_volume_recognition_sequence") == "NSR02"
        ),
        "all_replacements_independently_reread": all(
            item["independent_udf_reread_exact"]
            for item in replacement_checks.values()
        ),
    }
    if not all(acceptance.values()):
        raise WorldHistoryIsoError(
            f"static ISO acceptance failed: {acceptance}"
        )

    return {
        "schema_version": 1,
        "status": "static_iso_validated_runtime_pending",
        "content_policy": (
            "Hashes, counts, paths and runtime gates only; no game bytes "
            "are embedded."
        ),
        "profile_id": profile_id,
        "component": {
            "manifest": file_lock(component_manifest_path),
            "profile_id": component["profile_id"],
            "entry_count": component["selection"][
                "translation_entry_count"
            ],
            "archive_chunk_count": component["archive"]["chunk_count"],
            "outputs": component_outputs,
        },
        "iso_build": {
            "config": file_lock(config_path),
            "report": file_lock(iso_report_path),
            "output": actual_iso,
            "path": config["output"]["path"],
            "member_count": output_iso["member_count"],
            "unchanged_member_count": layout["unchanged_member_count"],
            "member_manifest_sha256": layout[
                "member_manifest_sha256"
            ],
            "pcsx2_v263_image_type": output_iso[
                "pcsx2_v263_image_type"
            ],
            "udf_volume_recognition_sequence": output_iso[
                "udf_volume_recognition_sequence"
            ],
            "replacements": replacement_checks,
        },
        "static_acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "required_iso_sha256": actual_iso["sha256"],
            "required_emulator": "PCSX2 v2.6.3",
            "pending_gates": [
                "fresh_process_boot_exact_iso",
                "pine_running_and_decoded_font_exact",
                "world_history_scroll_first_segment_visible",
                "world_history_scroll_middle_segment_visible",
                "world_history_scroll_final_segment_visible",
                "new_0x7f_and_0xfd_raw_trail_classes_visible",
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
    except (KeyError, OSError, WorldHistoryIsoError) as error:
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
                "runtime manifest missing; review and use --refresh-manifest"
            )
        if load_json(manifest_path) != report:
            raise SystemExit(
                "runtime manifest drift; review and use --refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI P1 world-history ISO verified:",
        f"entries={report['component']['entry_count']}",
        f"members={report['iso_build']['member_count']}",
        f"sha256={report['iso_build']['output']['sha256']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
