"""Compose the P2 UI core, first-five story and localized atlas suite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .patch_audit import sha256_bytes


class UiTestCandidateError(ValueError):
    """Validated UI and story components cannot form the test candidate."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiTestCandidateError(
            f"cannot load JSON object {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise UiTestCandidateError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiTestCandidateError("project path must be a non-empty string")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiTestCandidateError(f"path escapes project root: {raw}") from error
    return path


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_lock(project_root: Path, path: Path) -> dict:
    return {
        "path": str(path.relative_to(project_root.resolve())),
        "size": path.stat().st_size,
        "sha256": _sha256_path(path),
    }


def _payload_lock(payload: bytes) -> dict:
    return {
        "size": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _manifest_field(
    manifest: Mapping[str, object],
    raw_field: object,
    *,
    label: str,
) -> object:
    if not isinstance(raw_field, str) or not raw_field:
        raise UiTestCandidateError(f"{label} manifest field is invalid")
    value: object = manifest
    for segment in raw_field.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            raise UiTestCandidateError(
                f"{label} manifest field is missing: {raw_field}"
            )
        value = value[segment]
    return value


def _verify_json_reference(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, dict]:
    path = _project_path(project_root, reference.get("path"))
    if not path.is_file():
        raise UiTestCandidateError(f"{label} is missing: {path}")
    if _sha256_path(path) != reference.get("sha256"):
        raise UiTestCandidateError(f"{label} SHA-256 drift")
    value = _json_object(path)
    required_status = reference.get("required_status")
    if required_status is not None and value.get("status") != required_status:
        raise UiTestCandidateError(f"{label} status drift")
    required_profile_id = reference.get("required_profile_id")
    if (
        required_profile_id is not None
        and value.get("profile_id") != required_profile_id
    ):
        raise UiTestCandidateError(f"{label} profile drift")
    runtime_status_field = reference.get("runtime_status_field")
    required_runtime_status = reference.get("required_runtime_status")
    if (runtime_status_field is None) != (
        required_runtime_status is None
    ):
        raise UiTestCandidateError(
            f"{label} runtime status lock is incomplete"
        )
    if runtime_status_field is not None and _manifest_field(
        value,
        runtime_status_field,
        label=label,
    ) != required_runtime_status:
        raise UiTestCandidateError(f"{label} runtime status drift")
    return path, value


def _verified_payload(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, bytes]:
    path = _project_path(project_root, reference.get("path"))
    if not path.is_file():
        raise UiTestCandidateError(f"{label} is missing: {path}")
    payload = path.read_bytes()
    expected = {
        "size": reference.get("size"),
        "sha256": reference.get("sha256"),
    }
    if _payload_lock(payload) != expected:
        raise UiTestCandidateError(f"{label} size or SHA-256 drift")
    return path, payload


def build_ui_test_candidate(
    project_root: Path,
    config_path: Path,
) -> tuple[dict[str, bytes], dict]:
    """Return the seven-member integrated UI and first-five test candidate."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiTestCandidateError("unsupported UI test candidate schema")
    profile_id = config.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise UiTestCandidateError("UI test candidate needs a profile_id")
    outputs_config = config.get("outputs")
    if not isinstance(outputs_config, dict):
        raise UiTestCandidateError("UI test candidate outputs are missing")
    component_root = _project_path(
        root,
        outputs_config.get("component_root"),
    )

    components = config.get("components")
    if not isinstance(components, dict):
        raise UiTestCandidateError("UI test candidate components are missing")
    p2_reference = components.get("ui_p2_core")
    atlas_reference = components.get("atlas_suite")
    story_reference = components.get("first_five_story")
    if not all(
        isinstance(reference, dict)
        for reference in (p2_reference, atlas_reference, story_reference)
    ):
        raise UiTestCandidateError("UI test candidate component references are incomplete")

    p2_manifest_path, p2_manifest = _verify_json_reference(
        root,
        p2_reference["manifest"],
        label="P2 UI core manifest",
    )
    atlas_manifest_path, atlas_manifest = _verify_json_reference(
        root,
        atlas_reference["manifest"],
        label="atlas suite manifest",
    )
    story_manifest_path, story_manifest = _verify_json_reference(
        root,
        story_reference["manifest"],
        label="first-five manifest",
    )

    output_payloads: dict[str, bytes] = {}
    output_reports = {}
    source_reports = []
    for component_id, reference, manifest, manifest_path in (
        ("ui-p2-core", p2_reference, p2_manifest, p2_manifest_path),
        ("ui-atlas-suite-zh", atlas_reference, atlas_manifest, atlas_manifest_path),
        ("first-five-story", story_reference, story_manifest, story_manifest_path),
    ):
        manifest_reference = reference["manifest"]
        runtime_status = _manifest_field(
            manifest,
            manifest_reference["runtime_status_field"],
            label=f"{component_id} runtime status",
        )
        raw_outputs = reference.get("outputs")
        if not isinstance(raw_outputs, list) or not raw_outputs:
            raise UiTestCandidateError(f"{component_id} outputs are missing")
        component_outputs = []
        for raw in raw_outputs:
            if not isinstance(raw, dict):
                raise UiTestCandidateError(f"{component_id} output is invalid")
            member = raw.get("member")
            if not isinstance(member, str) or not member:
                raise UiTestCandidateError(f"{component_id} output identity is invalid")
            if member in output_payloads:
                raise UiTestCandidateError(f"test candidate member ownership overlaps: {member}")
            path, payload = _verified_payload(
                root,
                raw,
                label=f"{component_id} {member}",
            )
            manifest_lock_field = raw.get("manifest_lock_field")
            manifest_sha256_field = raw.get("manifest_sha256_field")
            if (manifest_lock_field is None) == (
                manifest_sha256_field is None
            ):
                raise UiTestCandidateError(
                    f"{component_id} {member} needs exactly one manifest lock field"
                )
            if manifest_lock_field is not None:
                manifest_lock = _manifest_field(
                    manifest,
                    manifest_lock_field,
                    label=f"{component_id} {member}",
                )
                if not isinstance(manifest_lock, Mapping):
                    raise UiTestCandidateError(
                        f"{component_id} {member} manifest lock is invalid"
                    )
                expected_manifest_lock = {
                    "size": manifest_lock.get("size"),
                    "sha256": manifest_lock.get("sha256"),
                }
            else:
                manifest_sha256 = _manifest_field(
                    manifest,
                    manifest_sha256_field,
                    label=f"{component_id} {member}",
                )
                expected_manifest_lock = {
                    "size": raw.get("size"),
                    "sha256": manifest_sha256,
                }
            payload_lock = _payload_lock(payload)
            if payload_lock != expected_manifest_lock:
                raise UiTestCandidateError(
                    f"{component_id} {member} manifest output lock drift"
                )
            output_payloads[member] = payload
            candidate_path = component_root / member
            output_reports[member] = {
                "path": str(candidate_path.relative_to(root)),
                **payload_lock,
                "owner": component_id,
                "source": _file_lock(root, path),
                "manifest_output_lock_exact": True,
            }
            component_outputs.append(member)
        source_reports.append(
            {
                "component_id": component_id,
                "manifest": _file_lock(root, manifest_path),
                "profile_id": manifest["profile_id"],
                "status": manifest["status"],
                "members": component_outputs,
                "runtime_status": runtime_status,
            }
        )

    composition = config.get("composition")
    if not isinstance(composition, dict):
        raise UiTestCandidateError("UI test candidate composition is missing")
    actual_members = sorted(output_payloads)
    expected_members = composition.get("members")
    if (
        composition.get("mode") != "whole-member-composition"
        or composition.get("member_count") != len(output_payloads)
        or expected_members != actual_members
        or composition.get("member_owner_overlap_count") != 0
    ):
        raise UiTestCandidateError("UI test candidate composition ratchet drift")
    if composition.get("font_owner") != "ui-p2-core":
        raise UiTestCandidateError("P2 UI core must own the final font")
    if composition.get("story_data_owner") != "first-five-story":
        raise UiTestCandidateError("first-five story must own HB and STAGE")
    if composition.get("atlas_owner") != "ui-atlas-suite-zh":
        raise UiTestCandidateError("atlas suite must own KVMDATA")

    expected_outputs = config.get("expected_outputs")
    if not isinstance(expected_outputs, dict):
        raise UiTestCandidateError("UI test candidate expected outputs are missing")
    actual_outputs = {
        member: _payload_lock(payload)
        for member, payload in sorted(output_payloads.items())
    }
    if actual_outputs != expected_outputs:
        raise UiTestCandidateError("UI test candidate output lock drift")

    acceptance = {
        "component_manifests_locked": True,
        "component_statuses_validated": True,
        "component_payloads_match_manifest_locks": True,
        "member_ownership_disjoint": len(output_payloads) == len(actual_members),
        "p2_core_owns_final_font_and_ui_text": True,
        "first_five_owns_story_archives": True,
        "atlas_suite_owns_kvmdata": True,
        "all_output_locks_exact": actual_outputs == expected_outputs,
    }
    if not all(acceptance.values()):
        raise UiTestCandidateError(
            f"UI test candidate acceptance failed: {acceptance}"
        )

    report = {
        "schema_version": 1,
        "status": (
            "integrated_ui_p2_first_five_atlas_test_component_"
            "validated_runtime_pending"
        ),
        "content_policy": (
            "Hashes, counts, paths and runtime gates only; no game bytes or "
            "localized text are embedded."
        ),
        "profile_id": profile_id,
        "scope": config.get("scope"),
        "inputs": {
            "config": _file_lock(root, config_path),
            "components": source_reports,
        },
        "composition": {
            **composition,
            "members": actual_members,
        },
        "outputs": output_reports,
        "acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "purpose": (
                "Exercise the current P2 UI core, first-five story data and "
                "all five localized atlas candidates in one exact ISO."
            ),
            "isolated_atlas_mapping_profiles_remain_required": True,
            "required_scene_families": config.get("runtime", {}).get(
                "required_scene_families",
                [],
            ),
            "promotion_rule": (
                "This integrated candidate may prove combined boot and visual "
                "coverage, but isolated atlas receipts remain necessary for "
                "member/chunk scene attribution."
            ),
        },
    }
    return output_payloads, report


__all__ = [
    "UiTestCandidateError",
    "build_ui_test_candidate",
]
