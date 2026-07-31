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
_ARTIFACT_AVAILABILITY = {"runnable", "blocked_runtime"}
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


def _matrix_plan_sha256(config: Mapping[str, object]) -> str:
    """Hash immutable test planning while excluding receipt state.

    A passed case stores its receipt hash back in this config, so hashing the
    complete file inside that receipt would create a circular dependency.
    Runtime status and receipt locks are therefore excluded; routes, captures,
    assertions, artifacts, fixtures and emulator policy remain bound.
    """

    plan = json.loads(json.dumps(config))
    raw_cases = plan.get("cases")
    if not isinstance(raw_cases, list):
        raise UiRuntimeMatrixError("runtime matrix needs test cases")
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise UiRuntimeMatrixError("runtime test case must be an object")
        raw_case.pop("runtime_status", None)
        raw_case.pop("runtime_evidence", None)
    payload = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        availability = raw.get("availability")
        if availability not in _ARTIFACT_AVAILABILITY:
            raise UiRuntimeMatrixError(
                f"artifact {artifact_id} availability is invalid"
            )

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

        iso_manifest = manifest
        iso_manifest_path = manifest_path
        iso_manifest_sha256 = manifest_sha256
        raw_iso_manifest = iso_lock.get("source_manifest")
        raw_iso_manifest_sha256 = iso_lock.get("source_manifest_sha256")
        if raw_iso_manifest is not None or raw_iso_manifest_sha256 is not None:
            iso_manifest_path = _project_path(
                project_root,
                raw_iso_manifest,
                context=f"artifact {artifact_id} ISO source manifest",
                prefix="manifests",
            )
            iso_manifest_sha256 = _require_sha256(
                raw_iso_manifest_sha256,
                context=f"artifact {artifact_id} ISO source manifest hash",
            )
            if _sha256(iso_manifest_path) != iso_manifest_sha256:
                raise UiRuntimeMatrixError(
                    f"artifact {artifact_id} ISO source manifest hash drift"
                )
            iso_manifest = _json_object(iso_manifest_path)

        actual_iso_path = _field(
            iso_manifest,
            iso_lock.get("path_field"),
            context=f"artifact {artifact_id} ISO path",
        )
        actual_iso_size = _field(
            iso_manifest,
            iso_lock.get("size_field"),
            context=f"artifact {artifact_id} ISO size",
        )
        actual_iso_sha256 = _field(
            iso_manifest,
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
                "availability": availability,
                "iso_path": actual_iso_path,
                "iso_size": actual_iso_size,
                "iso_sha256": actual_iso_sha256,
                "iso_source_manifest": {
                    "path": str(
                        iso_manifest_path.relative_to(project_root.resolve())
                    ),
                    "sha256": iso_manifest_sha256,
                },
                "mapping": mapping_projection,
            }
        )
    return tuple(artifacts)


def _locked_scene_extensions(
    project_root: Path,
    raw_extensions: object,
    *,
    base_scenes: Mapping[str, Mapping[str, object]],
) -> tuple[tuple[dict, ...], dict[str, dict]]:
    if raw_extensions is None:
        return (), {}
    if not isinstance(raw_extensions, list):
        raise UiRuntimeMatrixError("scene_extensions must be an array")
    extensions = []
    extension_scenes: dict[str, dict] = {}
    seen_extensions = set()
    for raw in raw_extensions:
        if not isinstance(raw, dict):
            raise UiRuntimeMatrixError("scene extension must be an object")
        extension_id = raw.get("extension_id")
        if (
            not isinstance(extension_id, str)
            or not extension_id
            or extension_id in seen_extensions
        ):
            raise UiRuntimeMatrixError("scene extension ID is invalid or duplicated")
        seen_extensions.add(extension_id)
        manifest_path = _project_path(
            project_root,
            raw.get("manifest"),
            context=f"scene extension {extension_id} manifest",
            prefix="manifests",
        )
        manifest_sha256 = _require_sha256(
            raw.get("manifest_sha256"),
            context=f"scene extension {extension_id} manifest hash",
        )
        if _sha256(manifest_path) != manifest_sha256:
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} manifest SHA-256 drift"
            )
        manifest = _json_object(manifest_path)
        if manifest.get("map_id") != raw.get("map_id"):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} map ID drift"
            )
        status_lock = raw.get("status_lock")
        if not isinstance(status_lock, dict):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} status lock is invalid"
            )
        status = _field(
            manifest,
            status_lock.get("field"),
            context=f"scene extension {extension_id} status",
        )
        if status != status_lock.get("equals"):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} status drift: {status!r}"
            )
        if raw.get("extension_kind") == "database_selection":
            (
                projected_extension,
                projected_database_scenes,
            ) = _locked_database_scene_extension(
                project_root,
                raw,
                manifest_path=manifest_path,
                manifest_sha256=manifest_sha256,
                manifest=manifest,
                status=status,
                base_scenes=base_scenes,
                extension_scenes=extension_scenes,
            )
            extension_scenes.update(projected_database_scenes)
            extensions.append(projected_extension)
            continue
        parent_scene_id = raw.get("parent_scene_id")
        if parent_scene_id not in base_scenes:
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} parent is unknown"
            )
        priority = raw.get("priority")
        if priority != base_scenes[parent_scene_id]["priority"]:
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} priority does not match its parent"
            )
        raw_selected_scene_ids = raw.get("selected_scene_ids", [])
        if (
            not isinstance(raw_selected_scene_ids, list)
            or any(
                not isinstance(scene_id, str) or not scene_id
                for scene_id in raw_selected_scene_ids
            )
        ):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} selected_scene_ids "
                "must be a string array"
            )
        selected_scene_ids = tuple(raw_selected_scene_ids)
        if len(selected_scene_ids) != len(set(selected_scene_ids)):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} selected scenes are duplicated"
            )
        raw_entry_subsets = raw.get("selected_entry_subsets", [])
        if not isinstance(raw_entry_subsets, list) or any(
            not isinstance(subset, dict) for subset in raw_entry_subsets
        ):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} entry subsets are invalid"
            )
        if not selected_scene_ids and not raw_entry_subsets:
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} selects no scenes"
            )
        subset_scene_ids = [
            subset.get("scene_id") for subset in raw_entry_subsets
        ]
        if (
            any(
                not isinstance(scene_id, str) or not scene_id
                for scene_id in subset_scene_ids
            )
            or len(subset_scene_ids) != len(set(subset_scene_ids))
        ):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} subset scene IDs are invalid"
            )
        subset_source_scene_ids = [
            subset.get("source_scene_id")
            for subset in raw_entry_subsets
        ]
        if any(
            not isinstance(scene_id, str) or not scene_id
            for scene_id in subset_source_scene_ids
        ):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} subset sources are invalid"
            )
        raw_groups = manifest.get("groups")
        if not isinstance(raw_groups, list):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} manifest groups are invalid"
            )
        groups = {
            group.get("scene_id"): group
            for group in raw_groups
            if isinstance(group, dict)
            and isinstance(group.get("scene_id"), str)
            and group.get("scene_id")
        }
        missing = sorted(
            (
                set(selected_scene_ids)
                | set(subset_source_scene_ids)
            )
            - set(groups)
        )
        if missing:
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} scenes are absent: {missing!r}"
            )
        promotion_reference = raw.get("promotion_manifest")
        promotion = None
        promoted_scenes: dict[str, dict] = {}
        promoted_entry_subsets: dict[str, dict] = {}
        if promotion_reference is not None:
            if not isinstance(promotion_reference, dict):
                raise UiRuntimeMatrixError(
                    f"scene extension {extension_id} promotion manifest is invalid"
                )
            promotion_path = _project_path(
                project_root,
                promotion_reference.get("path"),
                context=f"scene extension {extension_id} promotion manifest",
                prefix="manifests",
            )
            promotion_sha256 = _require_sha256(
                promotion_reference.get("sha256"),
                context=(
                    f"scene extension {extension_id} promotion manifest hash"
                ),
            )
            if _sha256(promotion_path) != promotion_sha256:
                raise UiRuntimeMatrixError(
                    f"scene extension {extension_id} promotion manifest "
                    "SHA-256 drift"
                )
            promotion_document = _json_object(promotion_path)
            if (
                promotion_document.get("profile_id")
                != promotion_reference.get("required_profile_id")
                or promotion_document.get("status")
                != promotion_reference.get("required_status")
                or promotion_document.get("runtime", {}).get("status")
                != promotion_reference.get("required_runtime_status")
                or not promotion_document.get("acceptance", {}).get(
                    "all_selected_entries_covered"
                )
                or promotion_document.get("selection", {}).get(
                    "excluded_entry_count"
                )
                != 0
                or promotion_document.get("inputs", {})
                .get("scene_map", {})
                .get("manifest", {})
                .get("sha256")
                != manifest_sha256
            ):
                raise UiRuntimeMatrixError(
                    f"scene extension {extension_id} promotion manifest drift"
                )
            raw_promoted_scenes = promotion_document.get(
                "selection",
                {},
            ).get("scenes")
            if not isinstance(raw_promoted_scenes, list):
                raise UiRuntimeMatrixError(
                    f"scene extension {extension_id} promotion scenes are invalid"
                )
            promoted_scenes = {
                scene.get("scene_id"): scene
                for scene in raw_promoted_scenes
                if isinstance(scene, dict)
                and isinstance(scene.get("scene_id"), str)
                and scene.get("scene_id")
            }
            promoted_entry_subsets = {
                scene.get("runtime_scene_id"): scene
                for scene in raw_promoted_scenes
                if isinstance(scene, dict)
                and scene.get("selection_mode") == "entry_subset"
                and isinstance(scene.get("runtime_scene_id"), str)
                and scene.get("runtime_scene_id")
            }
            promotion = {
                "path": str(promotion_path.relative_to(project_root.resolve())),
                "sha256": promotion_sha256,
                "profile_id": promotion_document["profile_id"],
                "status": promotion_document["status"],
                "runtime_status": promotion_document["runtime"]["status"],
                "scene_count": len(promoted_scenes),
                "entry_count": promotion_document["selection"]["entry_count"],
            }
        projected_scenes = []
        for scene_id in selected_scene_ids:
            if scene_id in base_scenes or scene_id in extension_scenes:
                raise UiRuntimeMatrixError(
                    f"scene extension scene is duplicated: {scene_id}"
                )
            group = groups[scene_id]
            readiness = group.get("writeback_readiness")
            directly_ready = (
                isinstance(readiness, dict)
                and readiness.get("status") == "fixed_span_ready"
                and readiness.get("excluded_entry_count") == 0
            )
            promoted_scene = promoted_scenes.get(scene_id)
            promotion_ready = (
                isinstance(readiness, dict)
                and isinstance(promoted_scene, dict)
                and promoted_scene.get("entry_count") == group.get("entry_count")
                and promoted_scene.get("readiness_status")
                == readiness.get("status")
                and promoted_scene.get("runtime_status") == "not_tested"
            )
            if (
                group.get("classification") != "user_facing_candidate"
                or group.get("runtime_status") != "not_tested"
                or not (directly_ready or promotion_ready)
            ):
                raise UiRuntimeMatrixError(
                    f"scene extension {scene_id} is not promotion-ready"
                )
            entry_count = group.get("entry_count")
            fixture_id = group.get("fixture_id")
            if (
                not isinstance(entry_count, int)
                or isinstance(entry_count, bool)
                or entry_count <= 0
                or not isinstance(fixture_id, str)
                or not fixture_id
            ):
                raise UiRuntimeMatrixError(
                    f"scene extension {scene_id} projection is invalid"
                )
            extension_scenes[scene_id] = {
                "scene_id": scene_id,
                "priority": priority,
                "parent_scene_id": parent_scene_id,
                "entry_count": entry_count,
                "fixture_id": fixture_id,
            }
            projected_scenes.append(
                {
                    "scene_id": scene_id,
                    "entry_count": entry_count,
                    "fixture_id": fixture_id,
                    "runtime_status": group["runtime_status"],
                    "writeback_readiness": (
                        "fixed_span_ready"
                        if directly_ready
                        else "font_extension_resolved_by_component"
                    ),
                }
            )
        for raw_subset in raw_entry_subsets:
            scene_id = raw_subset["scene_id"]
            source_scene_id = raw_subset["source_scene_id"]
            if scene_id in base_scenes or scene_id in extension_scenes:
                raise UiRuntimeMatrixError(
                    f"scene extension scene is duplicated: {scene_id}"
                )
            group = groups[source_scene_id]
            readiness = group.get("writeback_readiness")
            promoted_subset = promoted_entry_subsets.get(scene_id)
            entry_count = raw_subset.get("entry_count")
            entry_ids_sha256 = _require_sha256(
                raw_subset.get("entry_ids_sha256"),
                context=(
                    f"scene extension {extension_id} subset {scene_id} "
                    "entry hash"
                ),
            )
            fixture_id = group.get("fixture_id")
            if (
                promotion is None
                or group.get("classification")
                != "mixed_user_and_diagnostic"
                or group.get("runtime_status") != "not_tested"
                or not isinstance(readiness, dict)
                or readiness.get("status") != "fixed_span_ready"
                or readiness.get("excluded_entry_count") != 0
                or not isinstance(promoted_subset, dict)
                or promoted_subset.get("scene_id") != source_scene_id
                or promoted_subset.get("selection_mode")
                != "entry_subset"
                or promoted_subset.get("entry_count") != entry_count
                or promoted_subset.get("entry_ids_sha256")
                != entry_ids_sha256
                or promoted_subset.get("source_group_entry_count")
                != group.get("entry_count")
                or promoted_subset.get("source_group_entry_ids_sha256")
                != group.get("entry_ids_sha256")
                or promoted_subset.get("readiness_status")
                != readiness.get("status")
                or promoted_subset.get("runtime_status") != "not_tested"
            ):
                raise UiRuntimeMatrixError(
                    f"scene extension subset {scene_id} is not promotion-ready"
                )
            if (
                not isinstance(entry_count, int)
                or isinstance(entry_count, bool)
                or entry_count <= 0
                or entry_count >= group.get("entry_count", 0)
                or not isinstance(fixture_id, str)
                or not fixture_id
            ):
                raise UiRuntimeMatrixError(
                    f"scene extension subset {scene_id} projection is invalid"
                )
            extension_scenes[scene_id] = {
                "scene_id": scene_id,
                "priority": priority,
                "parent_scene_id": parent_scene_id,
                "source_scene_id": source_scene_id,
                "entry_count": entry_count,
                "fixture_id": fixture_id,
            }
            projected_scenes.append(
                {
                    "scene_id": scene_id,
                    "source_scene_id": source_scene_id,
                    "entry_count": entry_count,
                    "entry_ids_sha256": entry_ids_sha256,
                    "fixture_id": fixture_id,
                    "runtime_status": group["runtime_status"],
                    "writeback_readiness": (
                        "entry_subset_fixed_span_ready"
                    ),
                }
            )
        aggregate_entry_count = manifest.get("summary", {}).get(
            "aggregate_entry_count"
        )
        if (
            not isinstance(aggregate_entry_count, int)
            or isinstance(aggregate_entry_count, bool)
            or aggregate_entry_count <= 0
        ):
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} aggregate count is invalid"
            )
        promoted_entry_count = sum(
            scene["entry_count"] for scene in projected_scenes
        )
        if promoted_entry_count >= aggregate_entry_count:
            raise UiRuntimeMatrixError(
                f"scene extension {extension_id} leaves no deferred remainder"
            )
        extensions.append(
            {
                "extension_id": extension_id,
                "manifest": str(
                    manifest_path.relative_to(project_root.resolve())
                ),
                "manifest_sha256": manifest_sha256,
                "map_id": manifest["map_id"],
                "status": status,
                "parent_scene_id": parent_scene_id,
                "priority": priority,
                "scene_count": len(projected_scenes),
                "promoted_entry_count": promoted_entry_count,
                "aggregate_entry_count": aggregate_entry_count,
                "remaining_entry_count": (
                    aggregate_entry_count - promoted_entry_count
                ),
                "scenes": projected_scenes,
                **(
                    {"promotion_manifest": promotion}
                    if promotion is not None
                    else {}
                ),
            }
        )
    return tuple(extensions), extension_scenes


def _locked_database_scene_extension(
    project_root: Path,
    raw: Mapping[str, object],
    *,
    manifest_path: Path,
    manifest_sha256: str,
    manifest: Mapping[str, object],
    status: object,
    base_scenes: Mapping[str, Mapping[str, object]],
    extension_scenes: Mapping[str, Mapping[str, object]],
) -> tuple[dict, dict[str, dict]]:
    """Project a reviewed database selection into bounded runtime scenes."""

    extension_id = raw["extension_id"]
    selection_id = raw.get("selection_id")
    if manifest.get("selection_id") != selection_id:
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} selection ID drift"
        )
    parent_scene_id = raw.get("parent_scene_id")
    if parent_scene_id not in base_scenes:
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} parent is unknown"
        )
    parent = base_scenes[parent_scene_id]
    priority = raw.get("priority")
    if (
        parent.get("priority") != raw.get("parent_priority")
        or priority != "P1"
        or parent.get("priority") != "P2"
        or not isinstance(raw.get("priority_override_reason"), str)
        or not raw["priority_override_reason"]
    ):
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} priority override is invalid"
        )
    fixture_id = raw.get("fixture_id")
    if not isinstance(fixture_id, str) or not fixture_id:
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} fixture is invalid"
        )

    selection = manifest.get("selection")
    if not isinstance(selection, Mapping):
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} selection is invalid"
        )
    families = selection.get("families")
    if not isinstance(families, list) or not families:
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} families are invalid"
        )
    selected_scene_ids = raw.get("selected_family_scene_ids")
    if (
        not isinstance(selected_scene_ids, list)
        or not selected_scene_ids
        or any(
            not isinstance(scene_id, str) or not scene_id
            for scene_id in selected_scene_ids
        )
        or len(selected_scene_ids) != len(set(selected_scene_ids))
    ):
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} family scenes are invalid"
        )
    families_by_scene = {
        family.get("runtime_scene_id"): family
        for family in families
        if isinstance(family, Mapping)
        and isinstance(family.get("runtime_scene_id"), str)
        and family.get("runtime_scene_id")
    }
    if set(selected_scene_ids) != set(families_by_scene):
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} does not select every family"
        )

    promotion_reference = raw.get("promotion_manifest")
    if not isinstance(promotion_reference, Mapping):
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} promotion manifest is invalid"
        )
    promotion_path = _project_path(
        project_root,
        promotion_reference.get("path"),
        context=f"scene extension {extension_id} promotion manifest",
        prefix="manifests",
    )
    promotion_sha256 = _require_sha256(
        promotion_reference.get("sha256"),
        context=f"scene extension {extension_id} promotion manifest hash",
    )
    if _sha256(promotion_path) != promotion_sha256:
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} promotion manifest SHA-256 drift"
        )
    promotion = _json_object(promotion_path)
    promotion_selection = promotion.get("selection")
    promotion_acceptance = promotion.get("acceptance")
    bound_selection = (
        promotion.get("inputs", {})
        .get("database_selection", {})
        .get("manifest", {})
        .get("sha256")
    )
    if (
        promotion.get("profile_id")
        != promotion_reference.get("required_profile_id")
        or promotion.get("status")
        != promotion_reference.get("required_status")
        or promotion.get("runtime", {}).get("status")
        != promotion_reference.get("required_runtime_status")
        or bound_selection != manifest_sha256
        or not isinstance(promotion_selection, Mapping)
        or not isinstance(promotion_acceptance, Mapping)
        or not promotion_acceptance.get(
            "all_selected_entries_fixed_span_covered"
        )
        or not promotion_acceptance.get(
            "selected_targets_reread_exact"
        )
        or promotion_selection.get("entry_count")
        != selection.get("selected_entry_count")
        or promotion_selection.get("deferred_entry_count")
        != selection.get("deferred_entry_count")
    ):
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} promotion manifest drift"
        )
    promoted_families = {
        family.get("runtime_scene_id"): family
        for family in promotion_selection.get("families", [])
        if isinstance(family, Mapping)
        and isinstance(family.get("runtime_scene_id"), str)
        and family.get("runtime_scene_id")
    }

    projected_scenes = []
    projected_scene_map = {}
    for scene_id in selected_scene_ids:
        if scene_id in base_scenes or scene_id in extension_scenes:
            raise UiRuntimeMatrixError(
                f"scene extension scene is duplicated: {scene_id}"
            )
        family = families_by_scene[scene_id]
        promoted_family = promoted_families.get(scene_id)
        entry_count = family.get("entry_count")
        entry_ids_sha256 = _require_sha256(
            family.get("entry_ids_sha256"),
            context=(
                f"scene extension {extension_id} family {scene_id} entry hash"
            ),
        )
        if (
            not isinstance(entry_count, int)
            or isinstance(entry_count, bool)
            or entry_count <= 0
            or not isinstance(promoted_family, Mapping)
            or promoted_family.get("family_id") != family.get("family_id")
            or promoted_family.get("entry_count") != entry_count
            or promoted_family.get("entry_ids_sha256")
            != entry_ids_sha256
        ):
            raise UiRuntimeMatrixError(
                f"scene extension family {scene_id} is not promotion-ready"
            )
        projected_scene_map[scene_id] = {
            "scene_id": scene_id,
            "priority": priority,
            "parent_scene_id": parent_scene_id,
            "entry_count": entry_count,
            "fixture_id": fixture_id,
        }
        projected_scenes.append(
            {
                "scene_id": scene_id,
                "family_id": family["family_id"],
                "label": family.get("label"),
                "entry_count": entry_count,
                "entry_ids_sha256": entry_ids_sha256,
                "fixture_id": fixture_id,
                "runtime_status": "not_tested",
                "writeback_readiness": (
                    "fixed_span_and_font_extension_resolved_by_component"
                ),
            }
        )

    aggregate_entry_count = parent.get("expected_selected_entry_count")
    promoted_entry_count = sum(
        scene["entry_count"] for scene in projected_scenes
    )
    deferred_entry_count = selection.get("deferred_entry_count")
    if (
        not isinstance(aggregate_entry_count, int)
        or isinstance(aggregate_entry_count, bool)
        or promoted_entry_count != selection.get("selected_entry_count")
        or deferred_entry_count != aggregate_entry_count - promoted_entry_count
        or deferred_entry_count <= 0
    ):
        raise UiRuntimeMatrixError(
            f"scene extension {extension_id} aggregate count drift"
        )
    return (
        {
            "extension_id": extension_id,
            "extension_kind": "database_selection",
            "manifest": str(
                manifest_path.relative_to(project_root.resolve())
            ),
            "manifest_sha256": manifest_sha256,
            "selection_id": selection_id,
            "status": status,
            "parent_scene_id": parent_scene_id,
            "parent_priority": parent["priority"],
            "priority": priority,
            "priority_override_reason": raw["priority_override_reason"],
            "scene_count": len(projected_scenes),
            "promoted_entry_count": promoted_entry_count,
            "aggregate_entry_count": aggregate_entry_count,
            "remaining_entry_count": deferred_entry_count,
            "scenes": projected_scenes,
            "promotion_manifest": {
                "path": str(
                    promotion_path.relative_to(project_root.resolve())
                ),
                "sha256": promotion_sha256,
                "profile_id": promotion["profile_id"],
                "status": promotion["status"],
                "runtime_status": promotion["runtime"]["status"],
                "scene_count": len(projected_scenes),
                "entry_count": promotion_selection["entry_count"],
            },
        },
        projected_scene_map,
    )


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
    project_root: Path,
    matrix_id: str,
    matrix_plan_sha256: str,
    raw_cases: object,
    *,
    scenes: Mapping[str, Mapping[str, object]],
    artifacts: Mapping[str, Mapping[str, object]],
    fixtures: Mapping[str, Mapping[str, object]],
    emulator: Mapping[str, object],
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
        for scene_id in scene_ids:
            expected_fixture_id = scenes[scene_id].get("fixture_id")
            if (
                expected_fixture_id is not None
                and fixture_id != expected_fixture_id
            ):
                raise UiRuntimeMatrixError(
                    f"case {case_id} fixture does not match scene {scene_id}"
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
        artifact_availability = artifacts[artifact_id]["availability"]
        if runtime_status == "passed" and artifact_availability != "runnable":
            raise UiRuntimeMatrixError(
                f"passed case {case_id} uses a blocked runtime artifact"
            )
        case_projection = {
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
            "route": list(route),
            "assertions": list(assertions),
            "capture_counts": dict(sorted(kinds.items())),
            "capture_points": captures,
            "runtime_status": runtime_status,
            "execution_readiness": (
                "runtime_passed"
                if runtime_status == "passed"
                else (
                    "blocked_by_artifact_runtime"
                    if artifact_availability == "blocked_runtime"
                    else (
                        "route_ready_runtime_not_tested"
                        if fixtures[fixture_id]["status"] == "ready"
                        else "blocked_by_missing_fixture"
                    )
                )
            ),
            "texture_delta": mapping,
        }
        evidence_lock = raw.get("runtime_evidence")
        if runtime_status == "not_tested":
            if evidence_lock is not None:
                raise UiRuntimeMatrixError(
                    f"not-tested case {case_id} cannot claim runtime evidence"
                )
            evidence_projection = None
        else:
            if fixtures[fixture_id]["status"] != "ready":
                raise UiRuntimeMatrixError(
                    f"passed case {case_id} uses an unready fixture"
                )
            from .ui_runtime_evidence import (
                UiRuntimeEvidenceError,
                validate_committed_runtime_receipt,
            )

            try:
                evidence_projection = validate_committed_runtime_receipt(
                    project_root,
                    evidence_lock,
                    matrix_id=matrix_id,
                    matrix_plan_sha256=matrix_plan_sha256,
                    case=case_projection,
                    artifact=artifacts[artifact_id],
                    fixture=fixtures[fixture_id],
                    emulator=emulator,
                    capture_points=captures,
                    assertion_count=len(assertions),
                )
            except UiRuntimeEvidenceError as error:
                raise UiRuntimeMatrixError(str(error)) from error
        case_projection["runtime_evidence"] = evidence_projection
        cases.append(case_projection)
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
    matrix_config_sha256 = _sha256(config_path)
    matrix_plan_sha256 = _matrix_plan_sha256(config)

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
    base_scenes = {
        scene["scene_id"]: scene for scene in scene_config["scenes"]
    }
    scene_extensions, extension_scenes = _locked_scene_extensions(
        project_root,
        config.get("scene_extensions"),
        base_scenes=base_scenes,
    )
    scenes = {**base_scenes, **extension_scenes}

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
    emulator = evidence_policy.get("required_emulator")
    if not isinstance(emulator, dict):
        raise UiRuntimeMatrixError("runtime matrix needs required_emulator")
    emulator_fields = {
        "name",
        "version",
        "pine_version",
        "architecture",
        "launch_mode",
        "game_id",
    }
    if set(emulator) != emulator_fields or any(
        not isinstance(emulator[field], str) or not emulator[field]
        for field in emulator_fields
    ):
        raise UiRuntimeMatrixError("runtime emulator lock is invalid")
    if emulator["pine_version"] != (
        f"{emulator['name']} v{emulator['version']}"
    ):
        raise UiRuntimeMatrixError("runtime PINE emulator version lock is invalid")

    artifacts = _locked_artifacts(project_root, config.get("artifact_profiles"))
    artifacts_by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    fixtures = _fixtures(project_root, config.get("fixtures"))
    fixtures_by_id = {fixture["fixture_id"]: fixture for fixture in fixtures}
    cases = _cases(
        project_root,
        matrix_id,
        matrix_plan_sha256,
        config.get("cases"),
        scenes=scenes,
        artifacts=artifacts_by_id,
        fixtures=fixtures_by_id,
        emulator=emulator,
    )
    cases_by_id = {case["case_id"]: case for case in cases}
    dispositions = _scene_dispositions(
        config.get("scene_dispositions"),
        scenes=scenes,
        cases=cases_by_id,
    )
    dispositions_by_scene = {
        disposition["scene_id"]: disposition for disposition in dispositions
    }
    for scene_id, disposition in dispositions_by_scene.items():
        if disposition["disposition"] != "selected":
            continue
        expected_case_ids = {
            case["case_id"] for case in cases if scene_id in case["scene_ids"]
        }
        if set(disposition["case_ids"]) != expected_case_ids:
            raise UiRuntimeMatrixError(
                f"scene {scene_id} disposition does not own every case"
            )
    for extension in scene_extensions:
        parent_scene_id = extension["parent_scene_id"]
        if dispositions_by_scene[parent_scene_id]["disposition"] != "deferred":
            raise UiRuntimeMatrixError(
                f"scene extension parent {parent_scene_id} must remain deferred"
            )
        for scene in extension["scenes"]:
            if (
                dispositions_by_scene[scene["scene_id"]]["disposition"]
                != "selected"
            ):
                raise UiRuntimeMatrixError(
                    f"scene extension {scene['scene_id']} must be selected"
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
    artifact_blocked_cases = [
        case
        for case in cases
        if case["execution_readiness"] == "blocked_by_artifact_runtime"
    ]
    passed_cases = [
        case for case in cases if case["runtime_status"] == "passed"
    ]
    not_tested_cases = [
        case for case in cases if case["runtime_status"] == "not_tested"
    ]

    return {
        "schema_version": 1,
        "status": "runtime_matrix_validated_execution_pending",
        "matrix_id": matrix_id,
        "scope": scope,
        "matrix_config": {
            "path": str(config_path.resolve().relative_to(project_root)),
            "sha256": matrix_config_sha256,
        },
        "matrix_plan_sha256": matrix_plan_sha256,
        "scene_inventory": {
            "path": str(scene_path.relative_to(project_root)),
            "sha256": scene_sha256,
            "inventory_id": scene_config["inventory_id"],
            "scene_count": len(base_scenes),
        },
        "scene_extensions": list(scene_extensions),
        "evidence_policy": {
            "required_common": sorted(common),
            "required_for_asset_mapping": sorted(mapping),
            "required_emulator": emulator,
        },
        "summary": {
            "scene_count": len(scenes),
            "base_scene_count": len(base_scenes),
            "extended_scene_count": len(extension_scenes),
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
            "artifact_runtime_blocked_case_count": len(
                artifact_blocked_cases
            ),
            "capture_counts": dict(sorted(capture_counts.items())),
            "runtime_passed_case_count": len(passed_cases),
            "runtime_not_tested_case_count": len(not_tested_cases),
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
        "matrix_config": report["matrix_config"],
        "matrix_plan_sha256": report["matrix_plan_sha256"],
        "scene_inventory": report["scene_inventory"],
        "scene_extensions": report["scene_extensions"],
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
                    "runtime_evidence",
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
