"""Machine-checkable runtime test planning for selected SRWZ UI scenes."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Mapping, TextIO

from .ui_inventory import load_scene_config


class UiRuntimeMatrixError(ValueError):
    """The UI runtime matrix or one of its locked inputs is inconsistent."""


_CAPTURE_KINDS = {
    "screenshot",
    "screenshot_sequence",
    "texture_delta",
}
_FIXTURE_KINDS = {"fresh_boot", "memory_card"}
_FIXTURE_STATUSES = {"ready", "not_acquired"}
_PURPOSES = {
    "localization_acceptance",
    "story_sequence_acceptance",
    "asset_mapping",
}
_RUNTIME_STATUSES = {"not_tested", "passed"}
_COMMON_EVIDENCE = {
    "artifact_manifest_sha256",
    "iso_sha256",
    "pcsx2_version",
    "game_id",
    "fresh_process",
    "reached_state_proof",
    "emulator_log_sha256",
    "screenshot_sha256",
    "verdict",
}
_MAPPING_EVIDENCE = {
    "texture_dump_sha256",
    "texture_delta_pixel_count",
    "texture_delta_index_sha256",
}


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiRuntimeMatrixError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise UiRuntimeMatrixError(f"JSON root must be an object: {path}")
    return value


def _project_path(
    project_root: Path,
    raw: object,
    *,
    context: str,
    prefix: str | None = None,
) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiRuntimeMatrixError(f"{context} must be a non-empty path")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise UiRuntimeMatrixError(f"{context} must be project-relative")
    if prefix is not None:
        try:
            relative.relative_to(prefix)
        except ValueError as error:
            raise UiRuntimeMatrixError(
                f"{context} must be under {prefix}/"
            ) from error
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiRuntimeMatrixError(f"{context} escapes the project root") from error
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha256(raw: object, *, context: str) -> str:
    if (
        not isinstance(raw, str)
        or len(raw) != 64
        or any(character not in "0123456789abcdef" for character in raw)
    ):
        raise UiRuntimeMatrixError(f"{context} must be a lowercase SHA-256")
    return raw


def _field(document: Mapping[str, object], raw_path: object, *, context: str) -> object:
    if not isinstance(raw_path, str) or not raw_path:
        raise UiRuntimeMatrixError(f"{context} field path must be a non-empty string")
    value: object = document
    for part in raw_path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise UiRuntimeMatrixError(
                f"{context} field path does not exist: {raw_path}"
            )
        value = value[part]
    return value


def _string_list(raw: object, *, context: str) -> tuple[str, ...]:
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(value, str) or not value for value in raw)
    ):
        raise UiRuntimeMatrixError(f"{context} must be a non-empty string array")
    return tuple(raw)


def _locked_artifacts(
    project_root: Path,
    raw_artifacts: object,
) -> tuple[dict, ...]:
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise UiRuntimeMatrixError("runtime matrix needs artifact profiles")
    artifacts = []
    seen = set()
    for raw in raw_artifacts:
        if not isinstance(raw, dict):
            raise UiRuntimeMatrixError("artifact profile must be an object")
        artifact_id = raw.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise UiRuntimeMatrixError("artifact profile needs artifact_id")
        if artifact_id in seen:
            raise UiRuntimeMatrixError(f"duplicate artifact_id: {artifact_id}")
        seen.add(artifact_id)

        manifest_path = _project_path(
            project_root,
            raw.get("manifest"),
            context=f"artifact {artifact_id} manifest",
            prefix="manifests",
        )
        manifest_sha256 = _require_sha256(
            raw.get("manifest_sha256"),
            context=f"artifact {artifact_id} manifest hash",
        )
        actual_manifest_sha256 = _sha256(manifest_path)
        if actual_manifest_sha256 != manifest_sha256:
            raise UiRuntimeMatrixError(
                f"artifact {artifact_id} manifest hash drift: "
                f"{actual_manifest_sha256} != {manifest_sha256}"
            )
        manifest = _json_object(manifest_path)

        status_lock = raw.get("status_lock")
        runtime_lock = raw.get("runtime_lock")
        iso_lock = raw.get("iso_lock")
        if not isinstance(status_lock, dict) or not isinstance(runtime_lock, dict):
            raise UiRuntimeMatrixError(f"artifact {artifact_id} status locks are invalid")
        if not isinstance(iso_lock, dict):
            raise UiRuntimeMatrixError(f"artifact {artifact_id} ISO lock is invalid")
        status = _field(
            manifest,
            status_lock.get("field"),
            context=f"artifact {artifact_id} status",
        )
        runtime_status = _field(
            manifest,
            runtime_lock.get("field"),
            context=f"artifact {artifact_id} runtime status",
        )
        if status != status_lock.get("equals"):
            raise UiRuntimeMatrixError(
                f"artifact {artifact_id} status drift: {status!r}"
            )
        if runtime_status != runtime_lock.get("equals"):
            raise UiRuntimeMatrixError(
                f"artifact {artifact_id} runtime status drift: "
                f"{runtime_status!r}"
            )

        actual_iso_path = _field(
            manifest,
            iso_lock.get("path_field"),
            context=f"artifact {artifact_id} ISO path",
        )
        actual_iso_size = _field(
            manifest,
            iso_lock.get("size_field"),
            context=f"artifact {artifact_id} ISO size",
        )
        actual_iso_sha256 = _field(
            manifest,
            iso_lock.get("sha256_field"),
            context=f"artifact {artifact_id} ISO hash",
        )
        expected_iso_path = iso_lock.get("expected_path")
        expected_iso_size = iso_lock.get("expected_size")
        expected_iso_sha256 = _require_sha256(
            iso_lock.get("expected_sha256"),
            context=f"artifact {artifact_id} expected ISO hash",
        )
        _project_path(
            project_root,
            expected_iso_path,
            context=f"artifact {artifact_id} expected ISO path",
            prefix="build/iso",
        )
        if (
            actual_iso_path != expected_iso_path
            or actual_iso_size != expected_iso_size
            or actual_iso_sha256 != expected_iso_sha256
        ):
            raise UiRuntimeMatrixError(
                f"artifact {artifact_id} ISO lock drift"
            )
        if (
            not isinstance(actual_iso_size, int)
            or isinstance(actual_iso_size, bool)
            or actual_iso_size <= 0
        ):
            raise UiRuntimeMatrixError(f"artifact {artifact_id} ISO size is invalid")

        mapping = raw.get("mapping")
        mapping_projection = None
        if mapping is not None:
            if not isinstance(mapping, dict):
                raise UiRuntimeMatrixError(
                    f"artifact {artifact_id} mapping lock is invalid"
                )
            texture_delta = _field(
                manifest,
                mapping.get("field"),
                context=f"artifact {artifact_id} texture delta",
            )
            if not isinstance(texture_delta, dict):
                raise UiRuntimeMatrixError(
                    f"artifact {artifact_id} texture delta is invalid"
                )
            expected_pixels = mapping.get("expected_changed_pixel_count")
            if texture_delta.get("changed_pixel_count") != expected_pixels:
                raise UiRuntimeMatrixError(
                    f"artifact {artifact_id} texture pixel lock drift"
                )
            index_hash = _require_sha256(
                texture_delta.get("changed_pixel_indexes_sha256"),
                context=f"artifact {artifact_id} texture index hash",
            )
            chunk_index = texture_delta.get("chunk_index")
            if (
                not isinstance(chunk_index, int)
                or isinstance(chunk_index, bool)
                or chunk_index < 0
            ):
                raise UiRuntimeMatrixError(
                    f"artifact {artifact_id} texture chunk index is invalid"
                )
            mapping_projection = {
                "chunk_index": chunk_index,
                "changed_pixel_count": expected_pixels,
                "changed_pixel_indexes_sha256": index_hash,
            }

        artifacts.append(
            {
                "artifact_id": artifact_id,
                "manifest": str(manifest_path.relative_to(project_root.resolve())),
                "manifest_sha256": manifest_sha256,
                "status": status,
                "runtime_status": runtime_status,
                "iso_path": actual_iso_path,
                "iso_size": actual_iso_size,
                "iso_sha256": actual_iso_sha256,
                "mapping": mapping_projection,
            }
        )
    return tuple(artifacts)


def _fixtures(project_root: Path, raw_fixtures: object) -> tuple[dict, ...]:
    if not isinstance(raw_fixtures, list) or not raw_fixtures:
        raise UiRuntimeMatrixError("runtime matrix needs fixtures")
    fixtures = []
    seen = set()
    for raw in raw_fixtures:
        if not isinstance(raw, dict):
            raise UiRuntimeMatrixError("runtime fixture must be an object")
        fixture_id = raw.get("fixture_id")
        if not isinstance(fixture_id, str) or not fixture_id:
            raise UiRuntimeMatrixError("runtime fixture needs fixture_id")
        if fixture_id in seen:
            raise UiRuntimeMatrixError(f"duplicate fixture_id: {fixture_id}")
        seen.add(fixture_id)
        kind = raw.get("kind")
        status = raw.get("status")
        if kind not in _FIXTURE_KINDS:
            raise UiRuntimeMatrixError(f"fixture {fixture_id} has invalid kind")
        if status not in _FIXTURE_STATUSES:
            raise UiRuntimeMatrixError(f"fixture {fixture_id} has invalid status")
        requirements = _string_list(
            raw.get("requirements"),
            context=f"fixture {fixture_id} requirements",
        )
        workspace_path = raw.get("workspace_path")
        sha256 = raw.get("sha256")
        if kind == "fresh_boot":
            if status != "ready" or workspace_path is not None or sha256 is not None:
                raise UiRuntimeMatrixError(
                    f"fresh-boot fixture {fixture_id} contract is invalid"
                )
        else:
            _project_path(
                project_root,
                workspace_path,
                context=f"fixture {fixture_id} workspace path",
                prefix="work/runtime/ui-fixtures",
            )
            if Path(workspace_path).suffix.lower() != ".ps2":
                raise UiRuntimeMatrixError(
                    f"fixture {fixture_id} must be a memory-card .ps2 file"
                )
            if status == "ready":
                _require_sha256(
                    sha256,
                    context=f"fixture {fixture_id} memory-card hash",
                )
            elif sha256 is not None:
                raise UiRuntimeMatrixError(
                    f"fixture {fixture_id} cannot pin a hash before acquisition"
                )
        fixtures.append(
            {
                "fixture_id": fixture_id,
                "kind": kind,
                "status": status,
                "workspace_path": workspace_path,
                "sha256": sha256,
                "requirement_count": len(requirements),
            }
        )
    return tuple(fixtures)


def _cases(
    raw_cases: object,
    *,
    scenes: Mapping[str, Mapping[str, object]],
    artifacts: Mapping[str, Mapping[str, object]],
    fixtures: Mapping[str, Mapping[str, object]],
) -> tuple[dict, ...]:
    if not isinstance(raw_cases, list) or not raw_cases:
        raise UiRuntimeMatrixError("runtime matrix needs test cases")
    cases = []
    seen_cases = set()
    seen_captures = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise UiRuntimeMatrixError("runtime test case must be an object")
        case_id = raw.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise UiRuntimeMatrixError("runtime test case needs case_id")
        if case_id in seen_cases:
            raise UiRuntimeMatrixError(f"duplicate case_id: {case_id}")
        seen_cases.add(case_id)
        purpose = raw.get("purpose")
        priority = raw.get("priority")
        runtime_status = raw.get("runtime_status")
        if purpose not in _PURPOSES:
            raise UiRuntimeMatrixError(f"case {case_id} has invalid purpose")
        if priority not in {"P0", "P1", "P2"}:
            raise UiRuntimeMatrixError(f"case {case_id} has invalid priority")
        if runtime_status not in _RUNTIME_STATUSES:
            raise UiRuntimeMatrixError(f"case {case_id} has invalid runtime status")
        scene_ids = _string_list(
            raw.get("scene_ids"),
            context=f"case {case_id} scene_ids",
        )
        unknown_scenes = sorted(set(scene_ids) - set(scenes))
        if unknown_scenes:
            raise UiRuntimeMatrixError(
                f"case {case_id} references unknown scenes: {unknown_scenes!r}"
            )
        if any(scenes[scene_id]["priority"] != priority for scene_id in scene_ids):
            raise UiRuntimeMatrixError(
                f"case {case_id} priority does not match its scenes"
            )
        artifact_id = raw.get("artifact_id")
        fixture_id = raw.get("fixture_id")
        if artifact_id not in artifacts:
            raise UiRuntimeMatrixError(
                f"case {case_id} references unknown artifact {artifact_id!r}"
            )
        if fixture_id not in fixtures:
            raise UiRuntimeMatrixError(
                f"case {case_id} references unknown fixture {fixture_id!r}"
            )
        route = _string_list(raw.get("route"), context=f"case {case_id} route")
        assertions = _string_list(
            raw.get("assertions"),
            context=f"case {case_id} assertions",
        )
        raw_captures = raw.get("capture_points")
        if not isinstance(raw_captures, list) or not raw_captures:
            raise UiRuntimeMatrixError(f"case {case_id} needs capture_points")
        captures = []
        kinds = Counter()
        phases = set()
        for capture in raw_captures:
            if not isinstance(capture, dict):
                raise UiRuntimeMatrixError(
                    f"case {case_id} capture point must be an object"
                )
            capture_id = capture.get("capture_id")
            kind = capture.get("kind")
            state = capture.get("state")
            if (
                not isinstance(capture_id, str)
                or not capture_id
                or capture_id in seen_captures
            ):
                raise UiRuntimeMatrixError(
                    f"case {case_id} capture ID is invalid or duplicated"
                )
            if kind not in _CAPTURE_KINDS:
                raise UiRuntimeMatrixError(
                    f"case {case_id} capture {capture_id} has invalid kind"
                )
            if not isinstance(state, str) or not state:
                raise UiRuntimeMatrixError(
                    f"case {case_id} capture {capture_id} needs a state"
                )
            seen_captures.add(capture_id)
            kinds[kind] += 1
            phase = capture.get("phase")
            if phase is not None:
                if phase not in {"start", "middle", "end"}:
                    raise UiRuntimeMatrixError(
                        f"case {case_id} capture {capture_id} has invalid phase"
                    )
                phases.add(phase)
            captures.append(
                {
                    "capture_id": capture_id,
                    "kind": kind,
                    "state": state,
                    "phase": phase,
                }
            )
        if not kinds["screenshot"] and not kinds["screenshot_sequence"]:
            raise UiRuntimeMatrixError(f"case {case_id} has no visual capture")
        mapping = artifacts[artifact_id].get("mapping")
        if purpose == "asset_mapping":
            if mapping is None or kinds["texture_delta"] != 1:
                raise UiRuntimeMatrixError(
                    f"mapping case {case_id} needs one locked texture delta"
                )
        elif kinds["texture_delta"]:
            raise UiRuntimeMatrixError(
                f"non-mapping case {case_id} cannot claim a texture delta"
            )
        if "opening/world-history-scroll" in scene_ids and phases != {
            "start",
            "middle",
            "end",
        }:
            raise UiRuntimeMatrixError(
                f"world-history case {case_id} must capture start, middle and end"
            )
        cases.append(
            {
                "case_id": case_id,
                "purpose": purpose,
                "priority": priority,
                "scene_ids": list(scene_ids),
                "artifact_id": artifact_id,
                "fixture_id": fixture_id,
                "fixture_status": fixtures[fixture_id]["status"],
                "variant": raw.get("variant"),
                "route_step_count": len(route),
                "assertion_count": len(assertions),
                "capture_counts": dict(sorted(kinds.items())),
                "capture_points": captures,
                "runtime_status": runtime_status,
                "execution_readiness": (
                    "route_ready_runtime_not_tested"
                    if fixtures[fixture_id]["status"] == "ready"
                    else "blocked_by_missing_fixture"
                ),
                "texture_delta": mapping,
            }
        )
    return tuple(cases)


def _scene_dispositions(
    raw_dispositions: object,
    *,
    scenes: Mapping[str, Mapping[str, object]],
    cases: Mapping[str, Mapping[str, object]],
) -> tuple[dict, ...]:
    if not isinstance(raw_dispositions, list):
        raise UiRuntimeMatrixError("scene_dispositions must be an array")
    dispositions = []
    seen = set()
    for raw in raw_dispositions:
        if not isinstance(raw, dict):
            raise UiRuntimeMatrixError("scene disposition must be an object")
        scene_id = raw.get("scene_id")
        disposition = raw.get("disposition")
        if scene_id not in scenes or scene_id in seen:
            raise UiRuntimeMatrixError(
                f"scene disposition is unknown or duplicated: {scene_id!r}"
            )
        seen.add(scene_id)
        if disposition == "selected":
            case_ids = _string_list(
                raw.get("case_ids"),
                context=f"scene {scene_id} case_ids",
            )
            for case_id in case_ids:
                if case_id not in cases:
                    raise UiRuntimeMatrixError(
                        f"scene {scene_id} references unknown case {case_id}"
                    )
                if scene_id not in cases[case_id]["scene_ids"]:
                    raise UiRuntimeMatrixError(
                        f"scene {scene_id} is not owned by case {case_id}"
                    )
            reason = None
            exit_gate = None
        elif disposition == "deferred":
            if scenes[scene_id]["priority"] == "P0":
                raise UiRuntimeMatrixError(f"P0 scene {scene_id} cannot be deferred")
            if raw.get("case_ids") not in (None, []):
                raise UiRuntimeMatrixError(
                    f"deferred scene {scene_id} cannot reference cases"
                )
            reason = raw.get("reason")
            exit_gate = raw.get("exit_gate")
            if (
                not isinstance(reason, str)
                or not reason
                or not isinstance(exit_gate, str)
                or not exit_gate
            ):
                raise UiRuntimeMatrixError(
                    f"deferred scene {scene_id} needs reason and exit_gate"
                )
            case_ids = ()
        else:
            raise UiRuntimeMatrixError(
                f"scene {scene_id} has invalid disposition {disposition!r}"
            )
        dispositions.append(
            {
                "scene_id": scene_id,
                "priority": scenes[scene_id]["priority"],
                "disposition": disposition,
                "case_ids": list(case_ids),
                "reason": reason,
                "exit_gate": exit_gate,
            }
        )
    if seen != set(scenes):
        missing = sorted(set(scenes) - seen)
        raise UiRuntimeMatrixError(f"scene dispositions are incomplete: {missing!r}")
    return tuple(dispositions)


def audit_ui_runtime_matrix(project_root: Path, config_path: Path) -> dict:
    """Validate the runtime matrix and return a bounded evidence projection."""

    project_root = project_root.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiRuntimeMatrixError("unsupported UI runtime matrix schema")
    matrix_id = config.get("matrix_id")
    if not isinstance(matrix_id, str) or not matrix_id:
        raise UiRuntimeMatrixError("UI runtime matrix needs matrix_id")
    scope = config.get("scope")
    if not isinstance(scope, str) or not scope:
        raise UiRuntimeMatrixError("UI runtime matrix needs scope")

    scene_lock = config.get("scene_inventory")
    if not isinstance(scene_lock, dict):
        raise UiRuntimeMatrixError("UI runtime matrix needs scene_inventory")
    scene_path = _project_path(
        project_root,
        scene_lock.get("path"),
        context="scene inventory",
        prefix="config",
    )
    scene_sha256 = _require_sha256(
        scene_lock.get("sha256"),
        context="scene inventory hash",
    )
    if _sha256(scene_path) != scene_sha256:
        raise UiRuntimeMatrixError("scene inventory SHA-256 drift")
    scene_config = load_scene_config(scene_path)
    if scene_config["inventory_id"] != scene_lock.get("inventory_id"):
        raise UiRuntimeMatrixError("scene inventory ID drift")
    scenes = {scene["scene_id"]: scene for scene in scene_config["scenes"]}

    evidence_policy = config.get("evidence_policy")
    if not isinstance(evidence_policy, dict):
        raise UiRuntimeMatrixError("runtime matrix needs evidence_policy")
    common = set(
        _string_list(
            evidence_policy.get("required_common"),
            context="common evidence policy",
        )
    )
    mapping = set(
        _string_list(
            evidence_policy.get("required_for_asset_mapping"),
            context="mapping evidence policy",
        )
    )
    if not _COMMON_EVIDENCE <= common:
        raise UiRuntimeMatrixError("common runtime evidence policy is incomplete")
    if not _MAPPING_EVIDENCE <= mapping:
        raise UiRuntimeMatrixError("asset mapping evidence policy is incomplete")

    artifacts = _locked_artifacts(project_root, config.get("artifact_profiles"))
    artifacts_by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    fixtures = _fixtures(project_root, config.get("fixtures"))
    fixtures_by_id = {fixture["fixture_id"]: fixture for fixture in fixtures}
    cases = _cases(
        config.get("cases"),
        scenes=scenes,
        artifacts=artifacts_by_id,
        fixtures=fixtures_by_id,
    )
    cases_by_id = {case["case_id"]: case for case in cases}
    dispositions = _scene_dispositions(
        config.get("scene_dispositions"),
        scenes=scenes,
        cases=cases_by_id,
    )

    story_variants = {
        case["variant"]
        for case in cases
        if "story/first-five-opening-sequences" in case["scene_ids"]
    }
    if story_variants != {"001", "002", "003", "004", "005"}:
        raise UiRuntimeMatrixError(
            "first-five opening cases must cover variants 001 through 005"
        )
    if any(case["runtime_status"] != "not_tested" for case in cases):
        raise UiRuntimeMatrixError(
            "committed runtime matrix cannot claim unreviewed passed cases"
        )

    purpose_counts = Counter(case["purpose"] for case in cases)
    priority_counts = Counter(case["priority"] for case in cases)
    capture_counts = Counter()
    for case in cases:
        capture_counts.update(case["capture_counts"])
    fixture_status_counts = Counter(
        fixture["status"] for fixture in fixtures
    )
    selected = [
        disposition
        for disposition in dispositions
        if disposition["disposition"] == "selected"
    ]
    deferred = [
        disposition
        for disposition in dispositions
        if disposition["disposition"] == "deferred"
    ]
    ready_cases = [
        case
        for case in cases
        if case["execution_readiness"] == "route_ready_runtime_not_tested"
    ]
    blocked_cases = [
        case
        for case in cases
        if case["execution_readiness"] == "blocked_by_missing_fixture"
    ]

    return {
        "schema_version": 1,
        "status": "runtime_matrix_validated_execution_pending",
        "matrix_id": matrix_id,
        "scope": scope,
        "scene_inventory": {
            "path": str(scene_path.relative_to(project_root)),
            "sha256": scene_sha256,
            "inventory_id": scene_config["inventory_id"],
            "scene_count": len(scenes),
        },
        "evidence_policy": {
            "required_common": sorted(common),
            "required_for_asset_mapping": sorted(mapping),
        },
        "summary": {
            "scene_count": len(scenes),
            "selected_scene_count": len(selected),
            "deferred_scene_count": len(deferred),
            "case_count": len(cases),
            "purpose_case_counts": dict(sorted(purpose_counts.items())),
            "priority_case_counts": dict(sorted(priority_counts.items())),
            "artifact_count": len(artifacts),
            "fixture_count": len(fixtures),
            "fixture_status_counts": dict(sorted(fixture_status_counts.items())),
            "route_ready_case_count": len(ready_cases),
            "missing_fixture_case_count": len(blocked_cases),
            "capture_counts": dict(sorted(capture_counts.items())),
            "runtime_passed_case_count": 0,
            "runtime_not_tested_case_count": len(cases),
        },
        "artifacts": list(artifacts),
        "fixtures": list(fixtures),
        "cases": list(cases),
        "scene_dispositions": list(dispositions),
    }


def build_runtime_matrix_manifest(report: Mapping[str, object]) -> dict:
    """Project a report to the committed byte-free runtime planning manifest."""

    return {
        "schema_version": report["schema_version"],
        "status": report["status"],
        "matrix_id": report["matrix_id"],
        "scope": report["scope"],
        "scene_inventory": report["scene_inventory"],
        "evidence_policy": report["evidence_policy"],
        "summary": report["summary"],
        "artifacts": report["artifacts"],
        "fixtures": report["fixtures"],
        "cases": [
            {
                key: case[key]
                for key in (
                    "case_id",
                    "purpose",
                    "priority",
                    "scene_ids",
                    "artifact_id",
                    "fixture_id",
                    "fixture_status",
                    "variant",
                    "route_step_count",
                    "assertion_count",
                    "capture_counts",
                    "runtime_status",
                    "execution_readiness",
                    "texture_delta",
                )
            }
            for case in report["cases"]
        ],
        "scene_dispositions": report["scene_dispositions"],
    }


def write_runtime_matrix_tsv(
    report: Mapping[str, object],
    stream: TextIO,
) -> None:
    """Write one compact row per planned runtime case."""

    artifact_hashes = {
        artifact["artifact_id"]: artifact["iso_sha256"]
        for artifact in report["artifacts"]
    }
    fieldnames = (
        "case_id",
        "purpose",
        "priority",
        "scene_ids",
        "artifact_id",
        "iso_sha256",
        "fixture_id",
        "fixture_status",
        "execution_readiness",
        "route_steps",
        "screenshots",
        "screenshot_sequences",
        "texture_deltas",
        "texture_delta_pixels",
        "runtime_status",
    )
    writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    for case in report["cases"]:
        counts = case["capture_counts"]
        delta = case["texture_delta"] or {}
        writer.writerow(
            {
                "case_id": case["case_id"],
                "purpose": case["purpose"],
                "priority": case["priority"],
                "scene_ids": ",".join(case["scene_ids"]),
                "artifact_id": case["artifact_id"],
                "iso_sha256": artifact_hashes[case["artifact_id"]],
                "fixture_id": case["fixture_id"],
                "fixture_status": case["fixture_status"],
                "execution_readiness": case["execution_readiness"],
                "route_steps": case["route_step_count"],
                "screenshots": counts.get("screenshot", 0),
                "screenshot_sequences": counts.get("screenshot_sequence", 0),
                "texture_deltas": counts.get("texture_delta", 0),
                "texture_delta_pixels": delta.get("changed_pixel_count", 0),
                "runtime_status": case["runtime_status"],
            }
        )


__all__ = [
    "UiRuntimeMatrixError",
    "audit_ui_runtime_matrix",
    "build_runtime_matrix_manifest",
    "write_runtime_matrix_tsv",
]
