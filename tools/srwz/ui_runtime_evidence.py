"""Prepare and validate exact-candidate SRWZ UI runtime evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from .imagemagick import (
    identify_dimensions,
    read_rgba8,
    require_imagemagick,
)
from .ui_atlas_canary import AtlasMask, verify_masked_rgba


class UiRuntimeEvidenceError(ValueError):
    """A runtime case plan, session probe or visual receipt is invalid."""


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_TYPE_DVD = re.compile(r"Image type\s*=\s*DVD")
_ELF_EXECUTING = re.compile(r"ELF .*SLPS_258\.87.* is executing\.")
_TLB_MISS = re.compile(r"TLB Miss", re.IGNORECASE)
_SESSION_CHECKS = {
    "iso_size",
    "iso_sha256",
    "pcsx2_version",
    "game_id",
    "running_before",
    "running_after",
    "fresh_process",
    "dvd_recognized",
    "elf_executing",
    "no_tlb_miss",
}


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiRuntimeEvidenceError(
            f"cannot load JSON object {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise UiRuntimeEvidenceError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha256(raw: object, *, context: str) -> str:
    if not isinstance(raw, str) or _SHA256.fullmatch(raw) is None:
        raise UiRuntimeEvidenceError(f"{context} must be a lowercase SHA-256")
    return raw


def _project_path(
    project_root: Path,
    raw: object,
    *,
    context: str,
    prefix: str | None = None,
    require_file: bool = False,
) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiRuntimeEvidenceError(f"{context} must be a non-empty path")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise UiRuntimeEvidenceError(f"{context} must be project-relative")
    if prefix is not None:
        try:
            relative.relative_to(prefix)
        except ValueError as error:
            raise UiRuntimeEvidenceError(
                f"{context} must be under {prefix}/"
            ) from error
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiRuntimeEvidenceError(f"{context} escapes the project root") from error
    if require_file and not path.is_file():
        raise UiRuntimeEvidenceError(f"{context} was not found: {relative}")
    return path


def _relative(project_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError as error:
        raise UiRuntimeEvidenceError(
            f"path is outside the project root: {path}"
        ) from error


def _safe_case_parts(case_id: object) -> tuple[str, ...]:
    if not isinstance(case_id, str) or not case_id:
        raise UiRuntimeEvidenceError("runtime case_id must be a non-empty string")
    parts = tuple(case_id.split("/"))
    if any(
        not part
        or part in {".", ".."}
        or _SAFE_SEGMENT.fullmatch(part) is None
        for part in parts
    ):
        raise UiRuntimeEvidenceError(f"runtime case_id is path-unsafe: {case_id!r}")
    return parts


def case_workspace(project_root: Path, case_id: str) -> Path:
    """Return the ignored, case-owned runtime evidence directory."""

    parts = _safe_case_parts(case_id)
    root = project_root.resolve()
    return root.joinpath("work", "runtime", "ui-cases", *parts)


def build_case_plan(
    project_root: Path,
    matrix_config_path: Path,
    case_id: str,
) -> tuple[dict, dict]:
    """Build a reviewed plan and an untrusted evidence draft for one case."""

    from .ui_runtime_matrix import audit_ui_runtime_matrix

    project_root = project_root.resolve()
    report = audit_ui_runtime_matrix(project_root, matrix_config_path.resolve())
    try:
        case = next(
            candidate
            for candidate in report["cases"]
            if candidate["case_id"] == case_id
        )
    except StopIteration as error:
        raise UiRuntimeEvidenceError(f"unknown runtime case: {case_id}") from error
    artifact = next(
        item
        for item in report["artifacts"]
        if item["artifact_id"] == case["artifact_id"]
    )
    fixture = next(
        item
        for item in report["fixtures"]
        if item["fixture_id"] == case["fixture_id"]
    )
    workspace = case_workspace(project_root, case_id)
    workspace_relative = _relative(project_root, workspace)
    config_relative = _relative(project_root, matrix_config_path)

    capture_plan = []
    capture_draft = []
    for capture in case["capture_points"]:
        capture_id = capture["capture_id"]
        kind = capture["kind"]
        if kind == "screenshot":
            suggested = (
                f"{workspace_relative}/screenshots/{capture_id}.png"
            )
        elif kind == "screenshot_sequence":
            suggested = (
                f"{workspace_relative}/sequences/{capture_id}/"
            )
        else:
            suggested = (
                f"{workspace_relative}/textures/{capture_id}.png"
            )
        capture_plan.append(
            {
                **capture,
                "suggested_workspace_path": suggested,
            }
        )
        capture_draft.append(
            {
                "capture_id": capture_id,
                "kind": kind,
                "workspace_paths": [],
                "passed": None,
                "notes": "",
            }
        )

    plan = {
        "schema_version": 1,
        "status": "prepared_runtime_not_executed",
        "matrix": {
            "matrix_id": report["matrix_id"],
            "config_path": config_relative,
            "config_sha256": report["matrix_config"]["sha256"],
            "plan_sha256": report["matrix_plan_sha256"],
            "scene_inventory": report["scene_inventory"],
        },
        "case": {
            "case_id": case["case_id"],
            "purpose": case["purpose"],
            "priority": case["priority"],
            "scene_ids": case["scene_ids"],
            "variant": case["variant"],
            "route": case["route"],
            "assertions": case["assertions"],
            "runtime_status": case["runtime_status"],
        },
        "artifact": artifact,
        "fixture": fixture,
        "emulator": report["evidence_policy"]["required_emulator"],
        "evidence_policy": report["evidence_policy"],
        "workspace": {
            "root": workspace_relative,
            "case_plan": f"{workspace_relative}/case-plan.json",
            "evidence_draft": f"{workspace_relative}/evidence-draft.json",
            "session_probe": f"{workspace_relative}/session-probe.json",
            "emulator_log": f"{workspace_relative}/logs/emulog.txt",
        },
        "capture_points": capture_plan,
        "execution_readiness": case["execution_readiness"],
    }
    draft = {
        "schema_version": 1,
        "status": "draft",
        "matrix_id": report["matrix_id"],
        "case_id": case["case_id"],
        "session_probe": plan["workspace"]["session_probe"],
        "captures": capture_draft,
        "assertions": [
            {
                "index": index,
                "text": assertion,
                "passed": None,
                "notes": "",
            }
            for index, assertion in enumerate(case["assertions"], start=1)
        ],
        "verdict": "not_tested",
        "known_limits": [],
    }
    return plan, draft


def prepare_case_workspace(
    project_root: Path,
    matrix_config_path: Path,
    case_id: str,
    *,
    force: bool,
) -> tuple[Path, Path]:
    """Create the ignored case directories, plan and evidence draft."""

    plan, draft = build_case_plan(project_root, matrix_config_path, case_id)
    workspace = case_workspace(project_root, case_id)
    paths = [
        workspace / "case-plan.json",
        workspace / "evidence-draft.json",
    ]
    if not force:
        existing = [path for path in paths if path.exists()]
        if existing:
            raise UiRuntimeEvidenceError(
                "runtime case output exists; use --force: "
                + ", ".join(str(path) for path in existing)
            )
    for directory in (
        workspace / "logs",
        workspace / "screenshots",
        workspace / "sequences",
        workspace / "textures",
        workspace / "pine",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    paths[0].write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths[1].write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return paths[0], paths[1]


def build_session_probe(
    project_root: Path,
    plan: Mapping[str, object],
    *,
    pine_version: str,
    game_title: str,
    game_id: str,
    status_before: int,
    status_after: int,
    fresh_process: bool,
    log_path: Path,
) -> dict:
    """Validate R0 inputs and build a hash-only PINE/log session report."""

    project_root = project_root.resolve()
    artifact = plan["artifact"]
    fixture = plan["fixture"]
    emulator = plan["emulator"]
    workspace_prefix = plan["workspace"]["root"]
    if fixture["status"] != "ready":
        raise UiRuntimeEvidenceError(
            f"fixture is not ready: {fixture['fixture_id']}"
        )
    if fixture["kind"] == "memory_card":
        fixture_path = _project_path(
            project_root,
            fixture["workspace_path"],
            context="runtime memory-card fixture",
            prefix="work/runtime/ui-fixtures",
            require_file=True,
        )
        if _sha256(fixture_path) != fixture["sha256"]:
            raise UiRuntimeEvidenceError("runtime memory-card SHA-256 drift")
    if pine_version != emulator["pine_version"]:
        raise UiRuntimeEvidenceError(
            f"PCSX2 version drift: {pine_version!r}"
        )
    if game_id != emulator["game_id"]:
        raise UiRuntimeEvidenceError(f"game ID drift: {game_id!r}")
    if not isinstance(game_title, str) or not game_title:
        raise UiRuntimeEvidenceError("PINE returned an empty game title")
    if status_before != 0 or status_after != 0:
        raise UiRuntimeEvidenceError("PCSX2 was not Running before and after probe")
    if fresh_process is not True:
        raise UiRuntimeEvidenceError("runtime session must declare a fresh process")

    iso_path = _project_path(
        project_root,
        artifact["iso_path"],
        context="runtime artifact ISO",
        prefix="build/iso",
        require_file=True,
    )
    if iso_path.stat().st_size != artifact["iso_size"]:
        raise UiRuntimeEvidenceError("runtime artifact ISO size drift")
    iso_sha256 = _sha256(iso_path)
    if iso_sha256 != artifact["iso_sha256"]:
        raise UiRuntimeEvidenceError("runtime artifact ISO SHA-256 drift")

    log_relative = _relative(project_root, log_path)
    log_file = _project_path(
        project_root,
        log_relative,
        context="PCSX2 emulator log",
        prefix=workspace_prefix,
        require_file=True,
    )
    try:
        log_text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise UiRuntimeEvidenceError(
            f"cannot read PCSX2 log {log_relative}: {error}"
        ) from error
    checks = {
        "iso_size": True,
        "iso_sha256": True,
        "pcsx2_version": True,
        "game_id": True,
        "running_before": True,
        "running_after": True,
        "fresh_process": True,
        "dvd_recognized": _IMAGE_TYPE_DVD.search(log_text) is not None,
        "elf_executing": _ELF_EXECUTING.search(log_text) is not None,
        "no_tlb_miss": _TLB_MISS.search(log_text) is None,
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    if failed:
        raise UiRuntimeEvidenceError(
            "PCSX2 session checks failed: " + ", ".join(failed)
        )
    return {
        "schema_version": 1,
        "status": "passed",
        "matrix_id": plan["matrix"]["matrix_id"],
        "case_id": plan["case"]["case_id"],
        "artifact": {
            "artifact_id": artifact["artifact_id"],
            "manifest_sha256": artifact["manifest_sha256"],
            "iso_path": artifact["iso_path"],
            "iso_size": artifact["iso_size"],
            "iso_sha256": iso_sha256,
        },
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "kind": fixture["kind"],
            "sha256": fixture["sha256"],
        },
        "emulator": {
            "name": emulator["name"],
            "version": pine_version,
            "architecture": emulator["architecture"],
            "launch_mode": emulator["launch_mode"],
            "game_title": game_title,
            "game_id": game_id,
            "status_before": status_before,
            "status_after": status_after,
            "fresh_process": True,
        },
        "log": {
            "workspace_path": log_relative,
            "size": log_file.stat().st_size,
            "sha256": _sha256(log_file),
        },
        "checks": checks,
    }


def _validated_session_probe(
    project_root: Path,
    plan: Mapping[str, object],
    raw_path: object,
) -> dict:
    workspace_prefix = plan["workspace"]["root"]
    path = _project_path(
        project_root,
        raw_path,
        context="runtime session probe",
        prefix=workspace_prefix,
        require_file=True,
    )
    probe = _json_object(path)
    artifact = plan["artifact"]
    fixture = plan["fixture"]
    expected = {
        "status": "passed",
        "matrix_id": plan["matrix"]["matrix_id"],
        "case_id": plan["case"]["case_id"],
    }
    for key, value in expected.items():
        if probe.get(key) != value:
            raise UiRuntimeEvidenceError(
                f"runtime session probe {key} drift"
            )
    probe_artifact = probe.get("artifact")
    probe_fixture = probe.get("fixture")
    probe_emulator = probe.get("emulator")
    probe_log = probe.get("log")
    if not all(
        isinstance(value, dict)
        for value in (
            probe_artifact,
            probe_fixture,
            probe_emulator,
            probe_log,
        )
    ):
        raise UiRuntimeEvidenceError("runtime session probe structure is invalid")
    if (
        probe_artifact.get("artifact_id") != artifact["artifact_id"]
        or probe_artifact.get("manifest_sha256") != artifact["manifest_sha256"]
        or probe_artifact.get("iso_path") != artifact["iso_path"]
        or probe_artifact.get("iso_size") != artifact["iso_size"]
        or probe_artifact.get("iso_sha256") != artifact["iso_sha256"]
    ):
        raise UiRuntimeEvidenceError("runtime session artifact lock drift")
    if (
        probe_fixture.get("fixture_id") != fixture["fixture_id"]
        or probe_fixture.get("kind") != fixture["kind"]
        or probe_fixture.get("sha256") != fixture["sha256"]
    ):
        raise UiRuntimeEvidenceError("runtime session fixture lock drift")
    emulator = plan["emulator"]
    if (
        probe_emulator.get("name") != emulator["name"]
        or probe_emulator.get("version") != emulator["pine_version"]
        or probe_emulator.get("architecture") != emulator["architecture"]
        or probe_emulator.get("launch_mode") != emulator["launch_mode"]
        or probe_emulator.get("game_id") != emulator["game_id"]
        or probe_emulator.get("status_before") != 0
        or probe_emulator.get("status_after") != 0
        or probe_emulator.get("fresh_process") is not True
        or not isinstance(probe_emulator.get("game_title"), str)
        or not probe_emulator["game_title"]
    ):
        raise UiRuntimeEvidenceError("runtime session emulator lock drift")
    checks = probe.get("checks")
    if (
        not isinstance(checks, dict)
        or set(checks) != _SESSION_CHECKS
        or not all(checks.values())
    ):
        raise UiRuntimeEvidenceError("runtime session checks are incomplete")
    log_path = _project_path(
        project_root,
        probe_log.get("workspace_path"),
        context="runtime session emulator log",
        prefix=plan["workspace"]["root"],
        require_file=True,
    )
    if (
        not isinstance(probe_log.get("size"), int)
        or isinstance(probe_log.get("size"), bool)
        or probe_log["size"] <= 0
        or log_path.stat().st_size != probe_log["size"]
        or _sha256(log_path) != probe_log.get("sha256")
    ):
        raise UiRuntimeEvidenceError("runtime session emulator log drift")
    return {
        "workspace_path": _relative(project_root, path),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "emulator": probe_emulator,
        "log": probe_log,
        "checks": checks,
    }


def _image_lock(
    project_root: Path,
    workspace_prefix: str,
    raw_path: object,
    *,
    imagemagick: str,
    context: str,
) -> tuple[dict, Path]:
    path = _project_path(
        project_root,
        raw_path,
        context=context,
        prefix=workspace_prefix,
        require_file=True,
    )
    if path.suffix.lower() != ".png":
        raise UiRuntimeEvidenceError(f"{context} must be a PNG")
    width, height = identify_dimensions(imagemagick, path)
    return (
        {
            "workspace_path": _relative(project_root, path),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
            "width": width,
            "height": height,
        },
        path,
    )


def _mapping_reference(
    project_root: Path,
    artifact: Mapping[str, object],
) -> tuple[Path, dict, dict]:
    runtime_manifest_path = _project_path(
        project_root,
        artifact["manifest"],
        context="mapping runtime manifest",
        prefix="manifests",
        require_file=True,
    )
    runtime_manifest = _json_object(runtime_manifest_path)
    component_lock = runtime_manifest.get("component", {}).get("manifest")
    if not isinstance(component_lock, dict):
        raise UiRuntimeEvidenceError("mapping component manifest lock is missing")
    component_path = _project_path(
        project_root,
        component_lock.get("path"),
        context="mapping component manifest",
        prefix="manifests",
        require_file=True,
    )
    if _sha256(component_path) != component_lock.get("sha256"):
        raise UiRuntimeEvidenceError("mapping component manifest hash drift")
    component = _json_object(component_path)
    config_lock = component.get("inputs", {}).get("config")
    if not isinstance(config_lock, dict):
        raise UiRuntimeEvidenceError("mapping component config lock is missing")
    config_path = _project_path(
        project_root,
        config_lock.get("path"),
        context="mapping canary config",
        prefix="config/canary",
        require_file=True,
    )
    if _sha256(config_path) != config_lock.get("sha256"):
        raise UiRuntimeEvidenceError("mapping canary config hash drift")
    config = _json_object(config_path)
    reference_path = _project_path(
        project_root,
        config.get("outputs", {}).get("reference_png"),
        context="mapping reference PNG",
        prefix="work/build",
        require_file=True,
    )
    expected_reference = component.get("outputs", {}).get("reference_png")
    if (
        not isinstance(expected_reference, dict)
        or reference_path.stat().st_size != expected_reference.get("size")
        or _sha256(reference_path) != expected_reference.get("sha256")
    ):
        raise UiRuntimeEvidenceError("mapping reference PNG lock drift")
    return reference_path, component["target"]["mask"], artifact["mapping"]


def _validate_texture_delta(
    project_root: Path,
    plan: Mapping[str, object],
    runtime_texture: Path,
    *,
    imagemagick: str,
) -> dict:
    reference_path, raw_mask, expected = _mapping_reference(
        project_root,
        plan["artifact"],
    )
    mask = AtlasMask.from_mapping(raw_mask)
    reference = read_rgba8(
        imagemagick,
        reference_path,
        expected_width=256,
        expected_height=256,
    )
    runtime = read_rgba8(
        imagemagick,
        runtime_texture,
        expected_width=256,
        expected_height=256,
    )
    delta = verify_masked_rgba(
        reference,
        runtime,
        mask,
        width=256,
        height=256,
    )
    if (
        delta["changed_pixel_count"] != expected["changed_pixel_count"]
        or delta["changed_pixel_indexes_sha256"]
        != expected["changed_pixel_indexes_sha256"]
    ):
        raise UiRuntimeEvidenceError("runtime texture delta lock drift")
    return {
        "reference_png_sha256": _sha256(reference_path),
        "changed_pixel_count": delta["changed_pixel_count"],
        "changed_pixel_indexes_sha256": delta[
            "changed_pixel_indexes_sha256"
        ],
        "outside_mask_rgba_exact": delta["outside_mask_rgba_exact"],
        "replacement_rgba_exact": delta["replacement_rgba_exact"],
        "preserved_rgba_exact": delta["preserved_rgba_exact"],
    }


def verify_runtime_evidence(
    project_root: Path,
    plan: Mapping[str, object],
    draft: Mapping[str, object],
    *,
    imagemagick: str | None = None,
) -> dict:
    """Verify actual files and produce a committed, hash-only case receipt."""

    project_root = project_root.resolve()
    if draft.get("schema_version") != 1 or draft.get("status") != "complete":
        raise UiRuntimeEvidenceError("runtime evidence draft is not complete")
    if (
        draft.get("matrix_id") != plan["matrix"]["matrix_id"]
        or draft.get("case_id") != plan["case"]["case_id"]
    ):
        raise UiRuntimeEvidenceError("runtime evidence draft identity drift")
    if draft.get("verdict") != "passed":
        raise UiRuntimeEvidenceError("runtime evidence verdict is not passed")
    session = _validated_session_probe(
        project_root,
        plan,
        draft.get("session_probe"),
    )

    raw_captures = draft.get("captures")
    if not isinstance(raw_captures, list):
        raise UiRuntimeEvidenceError("runtime captures must be an array")
    captures_by_id = {}
    for capture in raw_captures:
        if not isinstance(capture, dict):
            raise UiRuntimeEvidenceError("runtime capture must be an object")
        capture_id = capture.get("capture_id")
        if capture_id in captures_by_id:
            raise UiRuntimeEvidenceError(f"duplicate runtime capture: {capture_id}")
        captures_by_id[capture_id] = capture
    expected_ids = {
        capture["capture_id"] for capture in plan["capture_points"]
    }
    if set(captures_by_id) != expected_ids:
        raise UiRuntimeEvidenceError("runtime capture set drift")

    executable = imagemagick or require_imagemagick()
    workspace_prefix = plan["workspace"]["root"]
    receipt_captures = []
    for expected_capture in plan["capture_points"]:
        capture_id = expected_capture["capture_id"]
        raw = captures_by_id[capture_id]
        kind = expected_capture["kind"]
        if raw.get("kind") != kind or raw.get("passed") is not True:
            raise UiRuntimeEvidenceError(
                f"runtime capture {capture_id} did not pass"
            )
        raw_paths = raw.get("workspace_paths")
        if not isinstance(raw_paths, list):
            raise UiRuntimeEvidenceError(
                f"runtime capture {capture_id} paths are invalid"
            )
        minimum = 2 if kind == "screenshot_sequence" else 1
        maximum = None if kind == "screenshot_sequence" else 1
        if len(raw_paths) < minimum or (
            maximum is not None and len(raw_paths) != maximum
        ):
            raise UiRuntimeEvidenceError(
                f"runtime capture {capture_id} file count is invalid"
            )
        image_locks = []
        image_paths = []
        for index, raw_path in enumerate(raw_paths):
            lock, path = _image_lock(
                project_root,
                workspace_prefix,
                raw_path,
                imagemagick=executable,
                context=f"runtime capture {capture_id} image {index}",
            )
            image_locks.append(lock)
            image_paths.append(path)
        delta = None
        if kind == "texture_delta":
            delta = _validate_texture_delta(
                project_root,
                plan,
                image_paths[0],
                imagemagick=executable,
            )
        receipt_captures.append(
            {
                "capture_id": capture_id,
                "kind": kind,
                "state": expected_capture["state"],
                "phase": expected_capture["phase"],
                "images": image_locks,
                "texture_delta": delta,
                "passed": True,
            }
        )

    raw_assertions = draft.get("assertions")
    if not isinstance(raw_assertions, list):
        raise UiRuntimeEvidenceError("runtime assertions must be an array")
    expected_assertions = plan["case"]["assertions"]
    if len(raw_assertions) != len(expected_assertions):
        raise UiRuntimeEvidenceError("runtime assertion count drift")
    receipt_assertions = []
    for index, (raw, expected_text) in enumerate(
        zip(raw_assertions, expected_assertions),
        start=1,
    ):
        if (
            not isinstance(raw, dict)
            or raw.get("index") != index
            or raw.get("text") != expected_text
            or raw.get("passed") is not True
        ):
            raise UiRuntimeEvidenceError(
                f"runtime assertion {index} did not pass"
            )
        notes = raw.get("notes")
        if not isinstance(notes, str):
            raise UiRuntimeEvidenceError(
                f"runtime assertion {index} notes are invalid"
            )
        receipt_assertions.append(
            {
                "index": index,
                "text": expected_text,
                "passed": True,
                "notes": notes,
            }
        )
    known_limits = draft.get("known_limits")
    if not isinstance(known_limits, list) or any(
        not isinstance(value, str) or not value for value in known_limits
    ):
        raise UiRuntimeEvidenceError("known_limits must be a string array")

    artifact = plan["artifact"]
    fixture = plan["fixture"]
    return {
        "schema_version": 1,
        "status": "passed",
        "content_policy": (
            "Hashes, dimensions, route identities and verdicts only; "
            "screenshots, logs, textures, saves and game bytes remain under "
            "ignored work/ or build/."
        ),
        "matrix": {
            "matrix_id": plan["matrix"]["matrix_id"],
            "plan_sha256": plan["matrix"]["plan_sha256"],
        },
        "case": {
            "case_id": plan["case"]["case_id"],
            "purpose": plan["case"]["purpose"],
            "scene_ids": plan["case"]["scene_ids"],
            "variant": plan["case"]["variant"],
        },
        "artifact": {
            "artifact_id": artifact["artifact_id"],
            "manifest_sha256": artifact["manifest_sha256"],
            "iso_path": artifact["iso_path"],
            "iso_size": artifact["iso_size"],
            "iso_sha256": artifact["iso_sha256"],
        },
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "kind": fixture["kind"],
            "sha256": fixture["sha256"],
        },
        "session": session,
        "captures": receipt_captures,
        "assertions": receipt_assertions,
        "verdict": "passed",
        "known_limits": known_limits,
    }


def validate_committed_runtime_receipt(
    project_root: Path,
    lock: object,
    *,
    matrix_id: str,
    matrix_plan_sha256: str,
    case: Mapping[str, object],
    artifact: Mapping[str, object],
    fixture: Mapping[str, object],
    emulator: Mapping[str, object],
    capture_points: list[dict],
    assertion_count: int,
) -> dict:
    """Validate a committed hash-only receipt for a matrix passed case."""

    if not isinstance(lock, dict):
        raise UiRuntimeEvidenceError(
            f"passed case {case['case_id']} needs runtime_evidence"
        )
    path = _project_path(
        project_root,
        lock.get("manifest"),
        context=f"case {case['case_id']} runtime evidence",
        prefix="manifests/runtime/ui-cases",
        require_file=True,
    )
    expected_hash = _require_sha256(
        lock.get("sha256"),
        context=f"case {case['case_id']} runtime evidence hash",
    )
    if _sha256(path) != expected_hash:
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime evidence hash drift"
        )
    receipt = _json_object(path)
    if receipt.get("schema_version") != 1 or receipt.get("status") != "passed":
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime receipt did not pass"
        )
    if (
        receipt.get("matrix", {}).get("matrix_id") != matrix_id
        or receipt.get("matrix", {}).get("plan_sha256")
        != matrix_plan_sha256
        or receipt.get("case", {}).get("case_id") != case["case_id"]
        or receipt.get("case", {}).get("purpose") != case["purpose"]
        or receipt.get("case", {}).get("scene_ids") != case["scene_ids"]
        or receipt.get("case", {}).get("variant") != case["variant"]
    ):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime receipt identity drift"
        )
    receipt_artifact = receipt.get("artifact")
    receipt_fixture = receipt.get("fixture")
    if not isinstance(receipt_artifact, dict) or not isinstance(
        receipt_fixture, dict
    ):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime receipt locks are invalid"
        )
    if (
        receipt_artifact.get("artifact_id") != artifact["artifact_id"]
        or receipt_artifact.get("manifest_sha256") != artifact["manifest_sha256"]
        or receipt_artifact.get("iso_path") != artifact["iso_path"]
        or receipt_artifact.get("iso_size") != artifact["iso_size"]
        or receipt_artifact.get("iso_sha256") != artifact["iso_sha256"]
        or receipt_fixture.get("fixture_id") != fixture["fixture_id"]
        or receipt_fixture.get("kind") != fixture["kind"]
        or receipt_fixture.get("sha256") != fixture["sha256"]
    ):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime receipt artifact/fixture drift"
        )
    session = receipt.get("session")
    if not isinstance(session, dict):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime receipt session is invalid"
        )
    session_emulator = session.get("emulator")
    session_log = session.get("log")
    session_checks = session.get("checks")
    if (
        not isinstance(session_emulator, dict)
        or not isinstance(session_log, dict)
        or not isinstance(session_checks, dict)
        or not session_checks
        or not all(session_checks.values())
        or session_emulator.get("name") != emulator["name"]
        or session_emulator.get("version") != emulator["pine_version"]
        or session_emulator.get("architecture") != emulator["architecture"]
        or session_emulator.get("launch_mode") != emulator["launch_mode"]
        or session_emulator.get("game_id") != emulator["game_id"]
        or session_emulator.get("status_before") != 0
        or session_emulator.get("status_after") != 0
        or session_emulator.get("fresh_process") is not True
        or not isinstance(session_emulator.get("game_title"), str)
        or not session_emulator["game_title"]
        or set(session_checks) != _SESSION_CHECKS
    ):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime receipt session drift"
        )
    _require_sha256(
        session.get("sha256"),
        context=f"case {case['case_id']} session probe hash",
    )
    if (
        not isinstance(session.get("size"), int)
        or isinstance(session.get("size"), bool)
        or session["size"] <= 0
    ):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} session probe size is invalid"
        )
    _project_path(
        project_root,
        session.get("workspace_path"),
        context=f"case {case['case_id']} session probe path",
        prefix=f"work/runtime/ui-cases/{case['case_id']}",
    )
    _require_sha256(
        session_log.get("sha256"),
        context=f"case {case['case_id']} emulator log hash",
    )
    if (
        not isinstance(session_log.get("size"), int)
        or isinstance(session_log.get("size"), bool)
        or session_log["size"] <= 0
    ):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} emulator log size is invalid"
        )
    _project_path(
        project_root,
        session_log.get("workspace_path"),
        context=f"case {case['case_id']} emulator log path",
        prefix=f"work/runtime/ui-cases/{case['case_id']}",
    )
    expected_captures = {
        capture["capture_id"]: capture["kind"] for capture in capture_points
    }
    receipt_captures = receipt.get("captures")
    if (
        not isinstance(receipt_captures, list)
        or len(receipt_captures) != len(expected_captures)
        or {
            capture.get("capture_id"): capture.get("kind")
            for capture in receipt_captures
            if isinstance(capture, dict)
        }
        != expected_captures
    ):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime receipt capture drift"
        )
    for capture in receipt_captures:
        expected_capture = next(
            item
            for item in capture_points
            if item["capture_id"] == capture["capture_id"]
        )
        if capture.get("passed") is not True:
            raise UiRuntimeEvidenceError(
                f"case {case['case_id']} runtime receipt capture failed"
            )
        images = capture.get("images")
        kind = capture.get("kind")
        minimum = 2 if kind == "screenshot_sequence" else 1
        maximum = None if kind == "screenshot_sequence" else 1
        if (
            not isinstance(images, list)
            or len(images) < minimum
            or (maximum is not None and len(images) != maximum)
        ):
            raise UiRuntimeEvidenceError(
                f"case {case['case_id']} runtime receipt image count drift"
            )
        for image in images:
            if (
                not isinstance(image, dict)
                or not isinstance(image.get("size"), int)
                or isinstance(image.get("size"), bool)
                or image["size"] <= 0
                or not isinstance(image.get("width"), int)
                or isinstance(image.get("width"), bool)
                or image["width"] <= 0
                or not isinstance(image.get("height"), int)
                or isinstance(image.get("height"), bool)
                or image["height"] <= 0
            ):
                raise UiRuntimeEvidenceError(
                    f"case {case['case_id']} runtime receipt image lock drift"
                )
            _require_sha256(
                image.get("sha256"),
                context=(
                    f"case {case['case_id']} runtime receipt image hash"
                ),
            )
            _project_path(
                project_root,
                image.get("workspace_path"),
                context=(
                    f"case {case['case_id']} runtime receipt image path"
                ),
                prefix=f"work/runtime/ui-cases/{case['case_id']}",
            )
        if (
            capture.get("state") != expected_capture["state"]
            or capture.get("phase") != expected_capture["phase"]
        ):
            raise UiRuntimeEvidenceError(
                f"case {case['case_id']} runtime receipt capture state drift"
            )
        delta = capture.get("texture_delta")
        if kind == "texture_delta":
            expected_delta = artifact.get("mapping")
            if (
                not isinstance(delta, dict)
                or not isinstance(expected_delta, dict)
                or delta.get("changed_pixel_count")
                != expected_delta["changed_pixel_count"]
                or delta.get("changed_pixel_indexes_sha256")
                != expected_delta["changed_pixel_indexes_sha256"]
                or delta.get("outside_mask_rgba_exact") is not True
                or delta.get("replacement_rgba_exact") is not True
                or delta.get("preserved_rgba_exact") is not True
            ):
                raise UiRuntimeEvidenceError(
                    f"case {case['case_id']} runtime texture receipt drift"
                )
            _require_sha256(
                delta.get("reference_png_sha256"),
                context=(
                    f"case {case['case_id']} runtime reference PNG hash"
                ),
            )
        elif delta is not None:
            raise UiRuntimeEvidenceError(
                f"case {case['case_id']} non-texture receipt has a delta"
            )
    assertions = receipt.get("assertions")
    if (
        not isinstance(assertions, list)
        or len(assertions) != assertion_count
        or receipt.get("verdict") != "passed"
    ):
        raise UiRuntimeEvidenceError(
            f"case {case['case_id']} runtime receipt verdict drift"
        )
    for index, (assertion, text) in enumerate(
        zip(assertions, case["assertions"]),
        start=1,
    ):
        if (
            not isinstance(assertion, dict)
            or assertion.get("index") != index
            or assertion.get("text") != text
            or assertion.get("passed") is not True
            or not isinstance(assertion.get("notes"), str)
        ):
            raise UiRuntimeEvidenceError(
                f"case {case['case_id']} runtime receipt assertion drift"
            )
    return {
        "manifest": _relative(project_root, path),
        "sha256": expected_hash,
        "status": "passed",
        "capture_count": len(receipt_captures),
        "assertion_count": len(assertions),
    }


__all__ = [
    "UiRuntimeEvidenceError",
    "build_case_plan",
    "build_session_probe",
    "case_workspace",
    "prepare_case_workspace",
    "validate_committed_runtime_receipt",
    "verify_runtime_evidence",
]
