"""Audit the causal COMPDATA allocation and boot-control experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .iso_config import load_config
from .pcsx2_boot_smoke import analyze_boot_log, sha256_file


class CompdataIncrementalError(ValueError):
    """The COMPDATA causal experiment is incomplete or has drifted."""


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompdataIncrementalError(
            f"cannot load JSON object {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise CompdataIncrementalError(f"JSON root is not an object: {path}")
    return value


def _project_file(
    project_root: Path,
    raw: object,
    *,
    prefix: str,
) -> Path:
    if not isinstance(raw, str) or not raw:
        raise CompdataIncrementalError("project path must be non-empty")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise CompdataIncrementalError(f"unsafe project path: {raw}")
    try:
        relative.relative_to(prefix)
    except ValueError as error:
        raise CompdataIncrementalError(
            f"path must be under {prefix}/: {raw}"
        ) from error
    path = (project_root / relative).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as error:
        raise CompdataIncrementalError(
            f"path escapes project root: {raw}"
        ) from error
    if not path.is_file():
        raise CompdataIncrementalError(f"file not found: {raw}")
    return path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replacement_map(config: dict) -> dict[str, dict]:
    return {
        replacement["member"]: replacement
        for replacement in config["replacements"]
    }


def _audit_boot(
    project_root: Path,
    step: dict,
    *,
    expect_pass: bool,
) -> dict:
    smoke_path = _project_file(
        project_root,
        step["boot_smoke_report"],
        prefix="work/runtime/iso-incremental",
    )
    smoke = _json(smoke_path)
    if smoke.get("iso") != {
        "path": step["iso_path"],
        "size": step["iso_size"],
        "sha256": step["iso_sha256"],
    }:
        raise CompdataIncrementalError(
            f"{step['step_id']} boot receipt ISO drift"
        )
    log_path = _project_file(
        project_root,
        smoke.get("log", {}).get("path"),
        prefix="work/runtime/iso-incremental",
    )
    if (
        log_path.stat().st_size != smoke["log"].get("size")
        or sha256_file(log_path) != smoke["log"].get("sha256")
    ):
        raise CompdataIncrementalError(
            f"{step['step_id']} boot log drift"
        )
    checks = analyze_boot_log(
        log_path.read_text(encoding="utf-8", errors="replace")
    )
    for field in (
        "dvd_recognized",
        "elf_executing",
        "tlb_miss_count",
        "no_tlb_miss",
        "first_tlb_miss",
    ):
        if smoke["log"].get(field) != checks[field]:
            raise CompdataIncrementalError(
                f"{step['step_id']} boot analysis drift: {field}"
            )
    if expect_pass:
        passed = (
            smoke.get("status") == "passed"
            and smoke["emulator"].get("pine_status") == 0
            and checks["no_tlb_miss"]
            and step.get("runtime_status") == "passed"
        )
    else:
        passed = (
            smoke.get("status") == "failed"
            and smoke["emulator"].get("pine_status") == 1
            and checks["tlb_miss_count"] == 1
            and checks["first_tlb_miss"] is not None
            and "pc=0x1c6ea0" in checks["first_tlb_miss"].lower()
            and "addr=0x2000000" in checks["first_tlb_miss"].lower()
            and step.get("runtime_status") == "failed_tlb"
        )
    if not passed:
        raise CompdataIncrementalError(
            f"{step['step_id']} runtime verdict drift"
        )
    return {
        "path": step["boot_smoke_report"],
        "sha256": sha256_file(smoke_path),
        "status": smoke["status"],
        "pine_status": smoke["emulator"]["pine_status"],
        "tlb_miss_count": checks["tlb_miss_count"],
        "first_tlb_miss": checks["first_tlb_miss"],
    }


def audit_compdata_incremental_chain(
    project_root: Path,
    chain_path: Path,
) -> dict:
    """Verify two controls and the first overflowing production candidate."""

    project_root = project_root.resolve()
    chain_path = chain_path.resolve()
    chain = _json(chain_path)
    if chain.get("schema_version") != 1:
        raise CompdataIncrementalError("unsupported chain schema")

    baseline = chain.get("baseline")
    if not isinstance(baseline, dict):
        raise CompdataIncrementalError("baseline is missing")
    baseline_iso = _project_file(
        project_root,
        baseline.get("iso_path"),
        prefix="build/iso",
    )
    if (
        baseline_iso.stat().st_size != baseline.get("iso_size")
        or sha256_file(baseline_iso) != baseline.get("iso_sha256")
    ):
        raise CompdataIncrementalError("baseline ISO lock drift")
    baseline_boot = _audit_boot(
        project_root,
        {
            **baseline,
            "step_id": baseline["step_id"],
        },
        expect_pass=True,
    )
    baseline_config = load_config(
        project_root / "config/iso/ui-step-02-first-five-noncompdata-build.json"
    )
    baseline_replacements = _replacement_map(baseline_config)

    steps = chain.get("steps")
    if not isinstance(steps, list) or {
        step.get("step_id") for step in steps if isinstance(step, dict)
    } != {
        "lba-shift-control",
        "p0-buttons-inplace",
        "p0-menu",
    }:
        raise CompdataIncrementalError("causal step set drift")

    audited = {}
    for step in steps:
        config_path = _project_file(
            project_root,
            step.get("build_config"),
            prefix="config/iso",
        )
        config = load_config(config_path)
        replacements = _replacement_map(config)
        if set(replacements) != {
            *baseline_replacements,
            "DATA/COMPDATA.BN",
        }:
            raise CompdataIncrementalError(
                f"{step['step_id']} replacement set drift"
            )
        for member, baseline_replacement in baseline_replacements.items():
            if (
                replacements[member]["size"]
                != baseline_replacement["size"]
                or replacements[member]["sha256"]
                != baseline_replacement["sha256"]
            ):
                raise CompdataIncrementalError(
                    f"{step['step_id']} changed non-COMPDATA member {member}"
                )

        iso_path = _project_file(
            project_root,
            step.get("iso_path"),
            prefix="build/iso",
        )
        if (
            iso_path.stat().st_size != step.get("iso_size")
            or sha256_file(iso_path) != step.get("iso_sha256")
        ):
            raise CompdataIncrementalError(
                f"{step['step_id']} ISO lock drift"
            )
        build_report_path = _project_file(
            project_root,
            config["output"]["report"],
            prefix="build/iso",
        )
        build_report = _json(build_report_path)
        if build_report.get("output_iso", {}).get("sha256") != step["iso_sha256"]:
            raise CompdataIncrementalError(
                f"{step['step_id']} build report drift"
            )
        if not all(
            build_report["layout"].get(field) is True
            for field in (
                "member_paths_exact",
                "member_order_exact",
                "unchanged_member_bytes_exact",
                "replacement_bytes_exact",
                "system_cnf_exact",
                "semantic_reproducible",
            )
        ):
            raise CompdataIncrementalError(
                f"{step['step_id']} static ISO acceptance failed"
            )
        compdata = replacements["DATA/COMPDATA.BN"]
        compdata_sectors = (compdata["size"] + 2047) // 2048
        shifts = build_report["layout"]["shift_segments"]
        expect_pass = step["step_id"] == "p0-buttons-inplace"
        boot = _audit_boot(
            project_root,
            step,
            expect_pass=expect_pass,
        )
        audited[step["step_id"]] = {
            "purpose": step["purpose"],
            "build_config": step["build_config"],
            "build_config_sha256": sha256_file(config_path),
            "iso": {
                "path": step["iso_path"],
                "size": step["iso_size"],
                "sha256": step["iso_sha256"],
            },
            "compdata": {
                "size": compdata["size"],
                "sha256": compdata["sha256"],
                "sectors": compdata_sectors,
            },
            "shift_segments": shifts,
            "boot": boot,
        }

    lba_control_component = _json(
        _project_file(
            project_root,
            "work/build/compdata-step-00-lba-shift-control/components/component-validation.json",
            prefix="work/build",
        )
    )
    control = lba_control_component.get("control", {})
    if not (
        control.get("source_sectors") == 71
        and control.get("candidate_sectors") == 72
        and control.get("zero_tail_size") == 419
        and control.get("compressed_stream_bytes_exact") is True
        and control.get("decoded_bytes_exact") is True
    ):
        raise CompdataIncrementalError("LBA control component drift")

    button = audited["p0-buttons-inplace"]
    lba = audited["lba-shift-control"]
    full = audited["p0-menu"]
    if not (
        button["compdata"]["sectors"] == 71
        and button["boot"]["status"] == "passed"
        and lba["compdata"]["sectors"] == 72
        and lba["boot"]["status"] == "failed"
        and full["compdata"]["sectors"] == 72
        and full["boot"]["status"] == "failed"
    ):
        raise CompdataIncrementalError("causal allocation result drift")

    promotion = chain.get("promotion")
    if not isinstance(promotion, dict):
        raise CompdataIncrementalError("in-place promotion is missing")
    promotion_config_path = _project_file(
        project_root,
        promotion.get("build_config"),
        prefix="config/iso",
    )
    promotion_config = load_config(promotion_config_path)
    promotion_replacements = _replacement_map(promotion_config)
    promoted_compdata = promotion_replacements.get("DATA/COMPDATA.BN")
    if (
        not isinstance(promoted_compdata, dict)
        or promoted_compdata.get("size") != 145057
        or (promoted_compdata["size"] + 2047) // 2048 != 71
    ):
        raise CompdataIncrementalError("promoted COMPDATA budget drift")
    promotion_iso = _project_file(
        project_root,
        promotion.get("iso_path"),
        prefix="build/iso",
    )
    if (
        promotion_iso.stat().st_size != promotion.get("iso_size")
        or sha256_file(promotion_iso) != promotion.get("iso_sha256")
    ):
        raise CompdataIncrementalError("promoted ISO lock drift")
    promotion_report = _json(
        _project_file(
            project_root,
            promotion_config["output"]["report"],
            prefix="build/iso",
        )
    )
    promotion_layout = promotion_report.get("layout", {})
    if not (
        promotion_report.get("output_iso", {}).get("sha256")
        == promotion["iso_sha256"]
        and promotion_layout.get("shifted_member_count") == 0
        and promotion_layout.get("shift_sectors") == 0
        and promotion_layout.get("lba_prefix_preserved_through")
        == "DMY/DMY.BIN"
    ):
        raise CompdataIncrementalError("promoted ISO LBA drift")
    promotion_boot = _audit_boot(
        project_root,
        promotion,
        expect_pass=True,
    )
    promotion_component_path = _project_file(
        project_root,
        promotion.get("component_manifest"),
        prefix="manifests",
    )
    promotion_component = _json(promotion_component_path)
    if not (
        promotion_component.get("selection", {}).get(
            "fixed_covered_entry_count"
        )
        == 44
        and promotion_component.get("compressed_component", {}).get(
            "within_sector_budget"
        )
        is True
    ):
        raise CompdataIncrementalError("promoted component acceptance drift")

    return {
        "schema_version": 1,
        "status": "compdata_lba_dependency_causally_validated",
        "chain": {
            "path": str(chain_path.relative_to(project_root)),
            "sha256": sha256_file(chain_path),
            "chain_id": chain["chain_id"],
        },
        "baseline": {
            **baseline,
            "iso_verified": True,
            "boot": baseline_boot,
        },
        "experiments": audited,
        "promoted_result": {
            "step_id": promotion["step_id"],
            "purpose": promotion["purpose"],
            "build_config": promotion["build_config"],
            "build_config_sha256": sha256_file(promotion_config_path),
            "component_manifest": promotion["component_manifest"],
            "component_manifest_sha256": sha256_file(
                promotion_component_path
            ),
            "iso": {
                "path": promotion["iso_path"],
                "size": promotion["iso_size"],
                "sha256": promotion["iso_sha256"],
            },
            "compdata": {
                "size": promoted_compdata["size"],
                "sha256": promoted_compdata["sha256"],
                "sectors": 71,
                "maximum_in_place_size": 145408,
                "budget_headroom": 145408 - promoted_compdata["size"],
            },
            "layout": {
                "all_member_lba_unchanged": True,
                "nisvdata_and_later_lba_unchanged": True,
                "shifted_member_count": 0,
                "shift_sectors": 0,
            },
            "boot": promotion_boot,
            "visual_status": "not_tested",
        },
        "causal_findings": {
            "original_allocation_sectors": 71,
            "maximum_in_place_size": 145408,
            "first_shifted_member": "DATA/NISVDATA.BIN",
            "one_sector_shift_is_sufficient_to_fail_boot": True,
            "failure_signature": (
                "TLB Miss, pc=0x1c6ea0 addr=0x02000000 [store]"
            ),
            "reencoded_compdata_can_boot_when_kept_in_place": True,
            "clean_room_encoder_is_not_the_first_failure_cause": True,
            "production_rule": (
                "A promoted COMPDATA.BN must occupy at most 71 sectors "
                "unless every affected physical-LBA dependency is found "
                "and patched with independent runtime proof."
            ),
        },
        "maximum_fit_runtime_pending_layers": [
            {
                "layer": "opening-display-names",
                "entry_count": 45,
                "legacy_size": 156161,
                "maximum_size": 143493,
                "budget_headroom": 1915,
            },
            {
                "layer": "researched-display-names",
                "entry_count": 1262,
                "legacy_size": 159688,
                "maximum_size": 143973,
                "budget_headroom": 1435,
            },
            {
                "layer": "database-fixed-core",
                "entry_count": 170,
                "legacy_size": 160291,
                "maximum_size": 144700,
                "budget_headroom": 708,
            },
        ],
        "next_actions": [
            "Acquire the first-intermission native card and capture the complete P0 target surfaces.",
            "Keep rejecting every future production candidate above 145408 bytes before ISO build.",
            "Promote P1, P2 and P10 in order; each must independently keep all member LBAs and pass boot.",
        ],
        "boundary": (
            "Boot-smoke proves DVD/ELF/PINE/TLB behavior only. The passed "
            "button component still needs navigation and screenshot proof "
            "on its actual intermission surface."
        ),
        "report_sha256": None,
    }


def finalize_report(report: dict) -> dict:
    """Bind the report content without a self-referential hash field."""

    payload = json.dumps(
        {**report, "report_sha256": None},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {**report, "report_sha256": _sha256_bytes(payload)}


__all__ = [
    "CompdataIncrementalError",
    "audit_compdata_incremental_chain",
    "finalize_report",
]
