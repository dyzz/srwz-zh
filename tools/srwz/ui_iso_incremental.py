"""Audit the first-five-based incremental UI ISO promotion chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .iso_config import load_config
from .pcsx2_boot_smoke import analyze_boot_log, sha256_file


class UiIsoIncrementalError(ValueError):
    """The incremental ISO chain is incomplete or internally inconsistent."""


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiIsoIncrementalError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise UiIsoIncrementalError(f"JSON root must be an object: {path}")
    return value


def _config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_path(
    project_root: Path,
    raw: object,
    *,
    context: str,
    prefix: str,
) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiIsoIncrementalError(f"{context} must be a non-empty path")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise UiIsoIncrementalError(f"{context} must be project-relative")
    try:
        relative.relative_to(prefix)
    except ValueError as error:
        raise UiIsoIncrementalError(
            f"{context} must be under {prefix}/"
        ) from error
    path = (project_root / relative).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as error:
        raise UiIsoIncrementalError(
            f"{context} escapes the project root"
        ) from error
    if not path.is_file():
        raise UiIsoIncrementalError(f"{context} not found: {relative}")
    return path


def _replacement_hashes(build_config: dict) -> dict[str, str]:
    return {
        replacement["member"]: replacement["sha256"]
        for replacement in build_config["replacements"]
    }


def _delta(
    previous: dict[str, str],
    current: dict[str, str],
) -> set[str]:
    return {
        member
        for member in previous.keys() | current.keys()
        if previous.get(member) != current.get(member)
    }


def audit_ui_iso_incremental_chain(
    project_root: Path,
    chain_path: Path,
) -> dict:
    """Validate configs, built bytes and fresh-process boot receipts."""

    project_root = project_root.resolve()
    chain_path = chain_path.resolve()
    chain = _json(chain_path)
    if chain.get("schema_version") != 1:
        raise UiIsoIncrementalError("unsupported chain schema")
    steps = chain.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        raise UiIsoIncrementalError("incremental chain needs at least two steps")

    audited_steps = []
    previous_replacements: dict[str, str] = {}
    promoted = None
    blocker = None
    for expected_index, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("index") != expected_index:
            raise UiIsoIncrementalError("chain indices must be contiguous")
        build_config_path = _project_path(
            project_root,
            step.get("build_config"),
            context=f"step {expected_index} build config",
            prefix="config/iso",
        )
        build_config = load_config(build_config_path)
        replacements = _replacement_hashes(build_config)
        if set(step.get("changed_members", [])) != set(replacements):
            raise UiIsoIncrementalError(
                f"step {expected_index} changed member set drift"
            )
        expected_delta = set(step.get("delta_from_previous", []))
        actual_delta = (
            set(step["changed_members"])
            if expected_index == 0
            else _delta(previous_replacements, replacements)
        )
        if expected_index == 0:
            if expected_delta != {"first-five baseline"}:
                raise UiIsoIncrementalError("baseline delta label drift")
        elif expected_delta != actual_delta:
            raise UiIsoIncrementalError(
                f"step {expected_index} delta drift: "
                f"{sorted(actual_delta)}"
            )

        materialization = step.get("materialization")
        component_sources = step.get("component_sources")
        audited_sources = {}
        if materialization == "copy_locked_components":
            if (
                not isinstance(component_sources, dict)
                or set(component_sources) != set(replacements)
            ):
                raise UiIsoIncrementalError(
                    f"step {expected_index} component source set drift"
                )
            replacement_records = {
                item["member"]: item
                for item in build_config["replacements"]
            }
            for member, raw_path in component_sources.items():
                source_path = _project_path(
                    project_root,
                    raw_path,
                    context=(
                        f"step {expected_index} source component {member}"
                    ),
                    prefix="work/build",
                )
                record = replacement_records[member]
                if (
                    source_path.stat().st_size != record["size"]
                    or sha256_file(source_path) != record["sha256"]
                ):
                    raise UiIsoIncrementalError(
                        f"step {expected_index} source component drift: "
                        f"{member}"
                    )
                audited_sources[member] = {
                    "path": raw_path,
                    "size": record["size"],
                    "sha256": record["sha256"],
                }
        elif materialization == "existing_profile":
            if component_sources is not None:
                raise UiIsoIncrementalError(
                    f"step {expected_index} unexpected component sources"
                )
        else:
            raise UiIsoIncrementalError(
                f"step {expected_index} materialization mode is invalid"
            )

        iso_path = _project_path(
            project_root,
            step.get("iso_path"),
            context=f"step {expected_index} ISO",
            prefix="build/iso",
        )
        iso_size = iso_path.stat().st_size
        iso_sha256 = sha256_file(iso_path)
        if (
            iso_size != step.get("iso_size")
            or iso_sha256 != step.get("iso_sha256")
        ):
            raise UiIsoIncrementalError(
                f"step {expected_index} ISO lock drift"
            )

        report_path = _project_path(
            project_root,
            build_config["output"]["report"],
            context=f"step {expected_index} ISO build report",
            prefix="build/iso",
        )
        build_report = _json(report_path)
        if build_report.get("output_iso", {}).get("size") != iso_size:
            raise UiIsoIncrementalError(
                f"step {expected_index} build report size drift"
            )
        if build_report["output_iso"].get("sha256") != iso_sha256:
            raise UiIsoIncrementalError(
                f"step {expected_index} build report hash drift"
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
            raise UiIsoIncrementalError(
                f"step {expected_index} static ISO acceptance failed"
            )

        smoke_path = _project_path(
            project_root,
            step.get("boot_smoke_report"),
            context=f"step {expected_index} boot smoke",
            prefix="work/runtime/iso-incremental",
        )
        smoke = _json(smoke_path)
        if smoke.get("iso") != {
            "path": step["iso_path"],
            "size": iso_size,
            "sha256": iso_sha256,
        }:
            raise UiIsoIncrementalError(
                f"step {expected_index} boot-smoke ISO drift"
            )
        log_path = _project_path(
            project_root,
            smoke.get("log", {}).get("path"),
            context=f"step {expected_index} emulator log",
            prefix="work/runtime/iso-incremental",
        )
        if (
            log_path.stat().st_size != smoke["log"].get("size")
            or sha256_file(log_path) != smoke["log"].get("sha256")
        ):
            raise UiIsoIncrementalError(
                f"step {expected_index} emulator log drift"
            )
        log_checks = analyze_boot_log(
            log_path.read_text(encoding="utf-8", errors="replace")
        )
        for field in (
            "dvd_recognized",
            "elf_executing",
            "tlb_miss_count",
            "no_tlb_miss",
            "first_tlb_miss",
        ):
            if smoke["log"].get(field) != log_checks[field]:
                raise UiIsoIncrementalError(
                    f"step {expected_index} log analysis drift: {field}"
                )

        expectation = step.get("runtime_expectation")
        if expectation == "must_boot_without_tlb":
            runtime_passed = (
                smoke.get("status") == "passed"
                and all(smoke.get("checks", {}).values())
                and step.get("runtime_status") == "passed"
            )
            if not runtime_passed:
                raise UiIsoIncrementalError(
                    f"step {expected_index} did not meet boot expectation"
                )
            promoted = step
        elif expectation == "known_tlb_failure_do_not_promote":
            runtime_passed = False
            if not (
                smoke.get("status") == "failed"
                and smoke["log"]["dvd_recognized"] is True
                and smoke["log"]["elf_executing"] is True
                and smoke["log"]["tlb_miss_count"] > 0
                and smoke["emulator"]["pine_status"] == 1
                and step.get("runtime_status") == "failed_tlb"
            ):
                raise UiIsoIncrementalError(
                    f"step {expected_index} blocker evidence drift"
                )
            if blocker is not None:
                raise UiIsoIncrementalError("chain has multiple blockers")
            blocker = step
        else:
            raise UiIsoIncrementalError(
                f"step {expected_index} runtime expectation is invalid"
            )

        audited_steps.append(
            {
                "index": expected_index,
                "step_id": step["step_id"],
                "purpose": step["purpose"],
                "delta_from_previous": step["delta_from_previous"],
                "build_config": {
                    "path": step["build_config"],
                    "sha256": _config_sha256(build_config_path),
                },
                "materialization": {
                    "mode": materialization,
                    "component_sources": audited_sources,
                },
                "iso": smoke["iso"],
                "iso_build_report": {
                    "path": build_config["output"]["report"],
                    "sha256": _config_sha256(report_path),
                    "member_manifest_sha256": (
                        build_report["layout"]["member_manifest_sha256"]
                    ),
                    "unchanged_member_count": (
                        build_report["layout"]["unchanged_member_count"]
                    ),
                    "shift_segments": build_report["layout"]["shift_segments"],
                },
                "boot_smoke": {
                    "path": step["boot_smoke_report"],
                    "sha256": _config_sha256(smoke_path),
                    "status": smoke["status"],
                    "pine_status": smoke["emulator"]["pine_status"],
                    "checks": smoke["checks"],
                    "log": smoke["log"],
                },
                "promotion_eligible": runtime_passed,
            }
        )
        previous_replacements = replacements

    if promoted is None or blocker is None:
        raise UiIsoIncrementalError(
            "chain must contain a promoted step and one explicit blocker"
        )
    return {
        "schema_version": 1,
        "status": "validated_with_known_compdata_runtime_blocker",
        "chain": {
            "chain_id": chain["chain_id"],
            "config_path": str(chain_path.relative_to(project_root)),
            "config_sha256": _config_sha256(chain_path),
            "step_count": len(steps),
        },
        "promoted_candidate": {
            "step_id": promoted["step_id"],
            "iso_path": promoted["iso_path"],
            "iso_size": promoted["iso_size"],
            "iso_sha256": promoted["iso_sha256"],
            "boundary": (
                "Fresh-process boot smoke passed. Navigation and visual "
                "acceptance remain separate runtime work."
            ),
        },
        "blocked_candidate": {
            "step_id": blocker["step_id"],
            "iso_path": blocker["iso_path"],
            "iso_size": blocker["iso_size"],
            "iso_sha256": blocker["iso_sha256"],
            "runtime_status": blocker["runtime_status"],
            "delta_from_promoted": blocker["delta_from_previous"],
            "reason": "modified COMPDATA.BN triggers a runtime TLB miss",
        },
        "steps": audited_steps,
    }


__all__ = [
    "UiIsoIncrementalError",
    "audit_ui_iso_incremental_chain",
]
