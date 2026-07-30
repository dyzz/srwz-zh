"""Build and verify the incremental P0 UI font/codebook proposal."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping

from .canary import rasterize_character, rasterizer_point_size
from .display_name_coverage import (
    DisplayNameCoverageError,
    audit_display_name_coverage,
)
from .font import (
    GLYPH_SIZE,
    RAW_STANDARD_TRAILS,
    decode_vt1_font_segment,
    glyph_index_for_code,
    is_cjk_unified_ideograph,
    raw_standard_allocation_candidates,
    read_extended_glyph_table,
    safe_standard_allocation_candidates,
    sha256_bytes,
)
from .font_profile import FontProfileError, load_font_profile
from .font_source import (
    FontSourceError,
    load_font_lock,
    verify_font_lock_files,
)
from .text import load_text_table
from .ui_database_selection import (
    UiDatabaseSelectionError,
    audit_ui_database_selection,
    build_database_selection_manifest,
    select_database_entries,
)
from .ui_embedded_scenes import (
    UiEmbeddedSceneError,
    audit_ui_embedded_scenes,
    build_embedded_scene_manifest,
    load_embedded_scene_config,
)
from .ui_inventory import (
    UiInventoryError,
    audit_entry_font,
    audit_ui_inventory,
    build_inventory_manifest,
    expand_selector,
    expand_scene_entries,
    load_scene_config,
    rendered_characters,
)


class UiFontError(ValueError):
    """The incremental UI font selection or allocation has drifted."""


def _json_object(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiFontError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(document, dict):
        raise UiFontError(f"JSON root must be an object: {path}")
    return document


def _project_path(project_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise UiFontError("project path must be a non-empty string")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiFontError(f"path escapes project root: {relative}") from error
    return path


def _hash_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _assignment_index(path: Path) -> dict[str, dict]:
    document = _json_object(path)
    raw_assignments = document.get("assignments")
    if not isinstance(raw_assignments, list):
        raise UiFontError(f"assignment file has no assignments: {path}")
    assignments = {}
    for raw in raw_assignments:
        if not isinstance(raw, dict):
            raise UiFontError(f"malformed assignment in {path}")
        character = raw.get("character")
        code = raw.get("code")
        glyph_index = raw.get("glyph_index")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code, str)
            or not isinstance(glyph_index, int)
        ):
            raise UiFontError(f"malformed assignment in {path}")
        if character in assignments:
            raise UiFontError(f"duplicate character assignment in {path}")
        assignment = dict(raw)
        assignment["code_value"] = int(code, 16)
        assignments[character] = assignment
    return assignments


def _font_source_metadata(lock: Mapping[str, object]) -> dict:
    return {
        "family": lock["family"],
        "version": lock["version"],
        "commit": lock["commit"],
        "font_sha256": lock["font"]["sha256"],
        "license_spdx": lock["license"]["spdx"],
        "license_sha256": lock["license"]["sha256"],
    }


def _selection_digest(entries: Mapping[str, Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry_id in sorted(entries):
        entry = entries[entry_id]
        row = {
            "id": entry_id,
            "source_text_sha256": entry.get("source_text_sha256"),
            "translation": entry.get("translation"),
            "translation_action": entry.get("translation_action"),
            "editorial_status": entry.get("editorial_status"),
        }
        digest.update(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _selected_ui_entries(
    project_root: Path,
    profile_document: Mapping[str, object],
) -> tuple[dict[str, dict], dict[str, set[str]], dict]:
    scene_reference = profile_document.get("scene_inventory")
    if not isinstance(scene_reference, dict):
        raise UiFontError("UI font profile has no scene_inventory")
    scene_path = _project_path(project_root, scene_reference.get("path"))
    if _hash_file(scene_path) != scene_reference.get("sha256"):
        raise UiFontError("UI scene inventory SHA-256 drift")
    scene_config = load_scene_config(scene_path)
    if scene_config["inventory_id"] != scene_reference.get("inventory_id"):
        raise UiFontError("UI scene inventory ID drift")

    priorities = scene_reference.get("priorities")
    expected_scene_ids = scene_reference.get("scene_ids")
    if (
        not isinstance(priorities, list)
        or not priorities
        or any(priority not in {"P0", "P1", "P2"} for priority in priorities)
        or not isinstance(expected_scene_ids, list)
    ):
        raise UiFontError("UI font scene selection is invalid")
    expected_scene_id_set = set(expected_scene_ids)
    if len(expected_scene_id_set) != len(expected_scene_ids):
        raise UiFontError("UI font scene IDs must be unique")
    selected_scenes = [
        scene
        for scene in scene_config["scenes"]
        if scene["scene_id"] in expected_scene_id_set
    ]
    actual_scene_ids = [scene["scene_id"] for scene in selected_scenes]
    if actual_scene_ids != expected_scene_ids:
        raise UiFontError("UI font scene ID selection drift")
    if any(scene["priority"] not in priorities for scene in selected_scenes):
        raise UiFontError("UI font selected scene priority drift")

    entries = {}
    entry_scenes: defaultdict[str, set[str]] = defaultdict(set)
    for scene in selected_scenes:
        for entry in expand_scene_entries(project_root, scene):
            entry_id = entry["id"]
            previous = entries.setdefault(entry_id, entry)
            if previous != entry:
                raise UiFontError(f"UI decision differs for {entry_id}")
            entry_scenes[entry_id].add(scene["scene_id"])
    expected_count = scene_reference.get("expected_unique_entry_count")
    if len(entries) != expected_count:
        raise UiFontError(
            f"UI font entry selection drift: {len(entries)} != {expected_count}"
        )

    inventory_report = audit_ui_inventory(project_root, scene_path)
    manifest_path = project_root / "manifests/ui-surface-inventory.json"
    if _json_object(manifest_path) != build_inventory_manifest(inventory_report):
        raise UiFontError("committed UI inventory manifest drift")
    return (
        entries,
        dict(entry_scenes),
        {
            "path": str(scene_path.relative_to(project_root.resolve())),
            "sha256": _hash_file(scene_path),
            "inventory_id": scene_config["inventory_id"],
            "priorities": priorities,
            "scene_ids": actual_scene_ids,
            "unique_entry_count": len(entries),
            "selection_sha256": _selection_digest(entries),
        },
    )


def _selected_display_name_entries(
    project_root: Path,
    profile_document: Mapping[str, object],
) -> tuple[dict[str, dict], dict[str, set[str]], dict]:
    scene_reference = profile_document.get("scene_inventory")
    if not isinstance(scene_reference, dict):
        raise UiFontError("UI font profile has no baseline scene inventory")
    scene_path = _project_path(
        project_root,
        scene_reference.get("path"),
    )
    if _hash_file(scene_path) != scene_reference.get("sha256"):
        raise UiFontError("baseline scene inventory SHA-256 drift")
    scene_config = load_scene_config(scene_path)
    if scene_config["inventory_id"] != scene_reference.get("inventory_id"):
        raise UiFontError("baseline scene inventory ID drift")

    reference = profile_document.get("display_name_selection")
    if not isinstance(reference, dict):
        raise UiFontError("UI font profile has no display_name_selection")
    config_path = _project_path(
        project_root,
        reference.get("config"),
    )
    manifest_path = _project_path(
        project_root,
        reference.get("manifest"),
    )
    if _hash_file(config_path) != reference.get("config_sha256"):
        raise UiFontError("display-name selection config SHA-256 drift")
    if _hash_file(manifest_path) != reference.get("manifest_sha256"):
        raise UiFontError("display-name selection manifest SHA-256 drift")
    committed = _json_object(manifest_path)
    if committed.get("status") != reference.get("required_status"):
        raise UiFontError("display-name selection status drift")
    if committed.get("selection_id") != reference.get("selection_id"):
        raise UiFontError("display-name selection ID drift")
    try:
        report, expected_manifest = audit_display_name_coverage(
            project_root,
            config_path,
        )
    except DisplayNameCoverageError as error:
        raise UiFontError(str(error)) from error
    if committed != expected_manifest:
        raise UiFontError("display-name selection manifest is not reproducible")

    raw_entries = report.get("selection", {}).get("entries")
    expected_count = reference.get("expected_entry_count")
    surface_id = reference.get("surface_id")
    if (
        not isinstance(raw_entries, list)
        or not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count <= 0
        or len(raw_entries) != expected_count
        or not isinstance(surface_id, str)
        or not surface_id
    ):
        raise UiFontError("display-name font selection is invalid")
    entries = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise UiFontError("display-name font entry is malformed")
        entry_id = raw.get("id")
        if not isinstance(entry_id, str) or not entry_id or entry_id in entries:
            raise UiFontError("display-name font entry ID is invalid")
        entries[entry_id] = raw
    selection_sha256 = committed.get("selection", {}).get(
        "selection_sha256"
    )
    if not isinstance(selection_sha256, str):
        raise UiFontError("display-name selection hash is missing")
    root = project_root.resolve()
    return (
        entries,
        {entry_id: {surface_id} for entry_id in entries},
        {
            "kind": "display_name_coverage",
            "selection_id": committed["selection_id"],
            "config": {
                "path": str(config_path.relative_to(root)),
                "sha256": _hash_file(config_path),
            },
            "manifest": {
                "path": str(manifest_path.relative_to(root)),
                "sha256": _hash_file(manifest_path),
                "status": committed["status"],
            },
            "surface_ids": [surface_id],
            "unique_entry_count": len(entries),
            "selection_sha256": selection_sha256,
            "baseline_scene_inventory": {
                "path": str(scene_path.relative_to(root)),
                "sha256": _hash_file(scene_path),
                "inventory_id": scene_config["inventory_id"],
            },
        },
    )


def _selected_embedded_scene_entries(
    project_root: Path,
    profile_document: Mapping[str, object],
) -> tuple[dict[str, dict], dict[str, set[str]], dict]:
    scene_reference = profile_document.get("scene_inventory")
    if not isinstance(scene_reference, dict):
        raise UiFontError("UI font profile has no baseline scene inventory")
    scene_path = _project_path(
        project_root,
        scene_reference.get("path"),
    )
    if _hash_file(scene_path) != scene_reference.get("sha256"):
        raise UiFontError("baseline scene inventory SHA-256 drift")
    scene_config = load_scene_config(scene_path)
    if scene_config["inventory_id"] != scene_reference.get("inventory_id"):
        raise UiFontError("baseline scene inventory ID drift")

    reference = profile_document.get("embedded_scene_selection")
    if not isinstance(reference, dict):
        raise UiFontError("UI font profile has no embedded_scene_selection")
    config_path = _project_path(project_root, reference.get("config"))
    manifest_path = _project_path(project_root, reference.get("manifest"))
    if _hash_file(config_path) != reference.get("config_sha256"):
        raise UiFontError("embedded-scene selection config SHA-256 drift")
    if _hash_file(manifest_path) != reference.get("manifest_sha256"):
        raise UiFontError("embedded-scene selection manifest SHA-256 drift")

    committed = _json_object(manifest_path)
    if committed.get("status") != reference.get("required_status"):
        raise UiFontError("embedded-scene selection status drift")
    if committed.get("map_id") != reference.get("map_id"):
        raise UiFontError("embedded-scene selection map ID drift")
    try:
        report = audit_ui_embedded_scenes(project_root, config_path)
    except UiEmbeddedSceneError as error:
        raise UiFontError(str(error)) from error
    if committed != build_embedded_scene_manifest(report):
        raise UiFontError("embedded-scene selection manifest is not reproducible")

    expected_scene_ids = reference.get("scene_ids")
    expected_count = reference.get("expected_entry_count")
    required_writeback_status = reference.get("required_writeback_status")
    if (
        not isinstance(expected_scene_ids, list)
        or not expected_scene_ids
        or any(
            not isinstance(scene_id, str) or not scene_id
            for scene_id in expected_scene_ids
        )
        or len(expected_scene_ids) != len(set(expected_scene_ids))
        or not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count <= 0
        or not isinstance(required_writeback_status, str)
        or not required_writeback_status
    ):
        raise UiFontError("embedded-scene font selection is invalid")

    config = load_embedded_scene_config(config_path)
    selected_groups = [
        group
        for group in config["groups"]
        if group["scene_id"] in set(expected_scene_ids)
    ]
    actual_scene_ids = [group["scene_id"] for group in selected_groups]
    if actual_scene_ids != expected_scene_ids:
        raise UiFontError("embedded-scene font group selection drift")
    report_by_id = {
        group["scene_id"]: group
        for group in report["groups"]
    }

    entries: dict[str, dict] = {}
    entry_scenes: defaultdict[str, set[str]] = defaultdict(set)
    for group in selected_groups:
        group_id = group["scene_id"]
        group_report = report_by_id.get(group_id)
        if (
            not isinstance(group_report, dict)
            or group_report.get("classification") != "user_facing_candidate"
            or group_report.get("writeback_readiness", {}).get("status")
            != required_writeback_status
        ):
            raise UiFontError(
                f"embedded-scene font group is not eligible: {group_id}"
            )
        try:
            selected_entries = expand_selector(
                project_root,
                group["selector"],
            )
        except UiInventoryError as error:
            raise UiFontError(str(error)) from error
        for entry in selected_entries:
            entry_id = entry["id"]
            previous = entries.setdefault(entry_id, entry)
            if previous != entry:
                raise UiFontError(
                    f"embedded-scene decision differs for {entry_id}"
                )
            entry_scenes[entry_id].add(group_id)
    if len(entries) != expected_count:
        raise UiFontError(
            "embedded-scene font entry selection drift: "
            f"{len(entries)} != {expected_count}"
        )

    root = project_root.resolve()
    return (
        entries,
        dict(entry_scenes),
        {
            "kind": "embedded_scene_groups",
            "map_id": config["map_id"],
            "config": {
                "path": str(config_path.relative_to(root)),
                "sha256": _hash_file(config_path),
            },
            "manifest": {
                "path": str(manifest_path.relative_to(root)),
                "sha256": _hash_file(manifest_path),
                "status": committed["status"],
            },
            "required_writeback_status": required_writeback_status,
            "scene_ids": actual_scene_ids,
            "unique_entry_count": len(entries),
            "selection_sha256": _selection_digest(entries),
            "baseline_scene_inventory": {
                "path": str(scene_path.relative_to(root)),
                "sha256": _hash_file(scene_path),
                "inventory_id": scene_config["inventory_id"],
            },
        },
    )


def _selected_database_entries(
    project_root: Path,
    profile_document: Mapping[str, object],
) -> tuple[dict[str, dict], dict[str, set[str]], dict]:
    reference = profile_document.get("database_selection")
    if not isinstance(reference, dict):
        raise UiFontError("UI font profile has no database_selection")
    config_path = _project_path(project_root, reference.get("config"))
    manifest_path = _project_path(project_root, reference.get("manifest"))
    if _hash_file(config_path) != reference.get("config_sha256"):
        raise UiFontError("database selection config SHA-256 drift")
    if _hash_file(manifest_path) != reference.get("manifest_sha256"):
        raise UiFontError("database selection manifest SHA-256 drift")
    committed = _json_object(manifest_path)
    if (
        committed.get("status") != reference.get("required_status")
        or committed.get("selection_id") != reference.get("selection_id")
    ):
        raise UiFontError("database selection manifest identity drift")
    try:
        report = audit_ui_database_selection(project_root, config_path)
        entries, entry_scenes, _metadata = select_database_entries(
            project_root,
            config_path,
        )
    except UiDatabaseSelectionError as error:
        raise UiFontError(str(error)) from error
    if committed != build_database_selection_manifest(report):
        raise UiFontError("database selection manifest is not reproducible")
    expected_count = reference.get("expected_entry_count")
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or len(entries) != expected_count
    ):
        raise UiFontError("database font entry selection drift")
    root = project_root.resolve()
    return (
        entries,
        entry_scenes,
        {
            "kind": "database_fixed_subset",
            "selection_id": report["selection_id"],
            "config": {
                "path": str(config_path.relative_to(root)),
                "sha256": _hash_file(config_path),
            },
            "manifest": {
                "path": str(manifest_path.relative_to(root)),
                "sha256": _hash_file(manifest_path),
                "status": committed["status"],
            },
            "parent_scene": report["inputs"]["parent_scene"],
            "families": report["selection"]["families"],
            "unique_entry_count": len(entries),
            "selection_sha256": report["selection"][
                "selected_decisions_sha256"
            ],
        },
    )


def _selected_font_entries(
    project_root: Path,
    profile_document: Mapping[str, object],
) -> tuple[dict[str, dict], dict[str, set[str]], dict]:
    if "display_name_selection" in profile_document:
        return _selected_display_name_entries(
            project_root,
            profile_document,
        )
    if "embedded_scene_selection" in profile_document:
        return _selected_embedded_scene_entries(
            project_root,
            profile_document,
        )
    if "database_selection" in profile_document:
        return _selected_database_entries(
            project_root,
            profile_document,
        )
    return _selected_ui_entries(project_root, profile_document)


def _character_provenance(
    entries: Mapping[str, Mapping[str, object]],
    entry_scenes: Mapping[str, set[str]],
) -> tuple[Counter[str], dict[str, set[str]]]:
    counts: Counter[str] = Counter()
    scenes: defaultdict[str, set[str]] = defaultdict(set)
    for entry_id, entry in entries.items():
        translation = entry.get("translation")
        if not isinstance(translation, str):
            raise UiFontError(f"{entry_id} translation is not text")
        for character in rendered_characters(translation):
            counts[character] += 1
            scenes[character].update(entry_scenes[entry_id])
    return counts, dict(scenes)


def _resolve_registry(
    project_root: Path,
    registry_path: Path,
    *,
    seen: frozenset[Path] = frozenset(),
) -> tuple[dict, tuple[str, ...], set[str]]:
    resolved = registry_path.resolve()
    if resolved in seen:
        raise UiFontError("UI allocation registry inheritance cycle")
    registry = _json_object(registry_path)
    if registry.get("schema_version") != 1:
        raise UiFontError("unsupported UI allocation registry")

    allocated = registry.get("allocated_characters")
    base_reference = registry.get("base_registry")
    if isinstance(allocated, str):
        if base_reference is not None:
            raise UiFontError("base allocation registry cannot also be incremental")
        characters = tuple(allocated)
        if not characters or len(characters) != len(set(characters)):
            raise UiFontError("base allocation registry characters are invalid")
        retired = set(registry.get("retired_characters", []))
        if not retired <= set(characters):
            raise UiFontError("retired base allocation is not registered")
        return registry, characters, retired

    if not isinstance(base_reference, dict):
        raise UiFontError("UI allocation registry has no base_registry")
    base_path = _project_path(project_root, base_reference.get("path"))
    if _hash_file(base_path) != base_reference.get("sha256"):
        raise UiFontError("base allocation registry SHA-256 drift")
    base, base_characters, retired = _resolve_registry(
        project_root,
        base_path,
        seen=seen | {resolved},
    )
    if len(base_characters) != base_reference.get("registered_character_count"):
        raise UiFontError("base allocation registry character count drift")

    appended = tuple(registry.get("appended_characters", ""))
    if not appended or len(appended) != len(set(appended)):
        raise UiFontError("UI appended allocation characters are invalid")
    if set(appended) & set(base_characters):
        raise UiFontError("UI allocation duplicates the base registry")
    retired_appended = set(registry.get("retired_appended_characters", []))
    if not retired_appended <= set(appended):
        raise UiFontError("retired UI allocation is not registered")
    reactivated = set(registry.get("reactivated_characters", []))
    if not reactivated <= retired or reactivated & set(appended):
        raise UiFontError("reactivated UI allocation is invalid")
    registered = (*base_characters, *appended)
    return registry, registered, (retired - reactivated) | retired_appended


def _load_incremental_registry(
    project_root: Path,
    registry_path: Path,
) -> tuple[
    dict,
    dict,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    set[str],
]:
    registry = _json_object(registry_path)
    base_reference = registry.get("base_registry")
    if not isinstance(base_reference, dict):
        raise UiFontError("UI allocation registry has no base_registry")
    base_path = _project_path(project_root, base_reference.get("path"))
    base, base_characters, _ = _resolve_registry(project_root, base_path)
    resolved, registered, retired = _resolve_registry(
        project_root,
        registry_path,
    )
    if resolved != registry:
        raise UiFontError("UI allocation registry changed during load")
    reactivated = tuple(registry.get("reactivated_characters", []))
    return (
        registry,
        base,
        base_characters,
        registered,
        reactivated,
        retired,
    )


def _new_assignment(
    *,
    character: str,
    code: int,
    glyph_index: int,
    mapping: str,
    status: str,
    owner: str,
    basis: str,
    occurrence_count: int,
    scene_ids: set[str],
    original_font: bytes,
    rasterizer: Mapping[str, object],
    font_path: Path,
    assignment_id_prefix: str,
) -> dict:
    gray, pixels, packed = rasterize_character(
        rasterizer["executable"],
        font_path,
        character,
        rasterizer,
    )
    start = glyph_index * GLYPH_SIZE
    preimage = original_font[start : start + GLYPH_SIZE]
    return {
        "id": f"{assignment_id_prefix}-u{ord(character):04x}",
        "character": character,
        "code": f"{code:04X}",
        "glyph_index": glyph_index,
        "mapping": mapping,
        "status": status,
        "allocation": {
            "owner": owner,
            "basis": basis,
            "source_occurrences": occurrence_count,
            "scene_ids": sorted(scene_ids),
            "glyph_preimage_sha256": sha256_bytes(preimage),
            "glyph_preimage_all_zero": not any(preimage),
        },
        "raster": {
            "point_size": rasterizer_point_size(character, rasterizer),
            "raw_gray_sha256": sha256_bytes(gray),
            "pixels_4bpp_sha256": sha256_bytes(pixels),
            "packed_glyph_sha256": sha256_bytes(packed),
        },
    }


def _validation_proposal_reference(
    project_root: Path,
    validation: Mapping[str, object],
) -> tuple[Path, str]:
    proposal = validation.get("proposal")
    if isinstance(proposal, dict):
        raw_path = proposal.get("path")
        expected_hash = proposal.get("sha256")
    else:
        codebook = validation.get("codebook")
        if not isinstance(codebook, dict):
            raise UiFontError("base validation manifest has no proposal")
        raw_path = codebook.get("proposal")
        expected_hash = codebook.get("proposal_sha256")
    path = _project_path(project_root, raw_path)
    if _hash_file(path) != expected_hash:
        raise UiFontError("base proposal SHA-256 drift")
    return path, expected_hash


def _validation_component_hash(
    validation: Mapping[str, object],
    label: str,
) -> str:
    component = validation.get("font_component")
    if not isinstance(component, dict):
        raise UiFontError("base validation manifest has no font component")
    outputs = component.get("outputs")
    if isinstance(outputs, dict):
        output = outputs.get(label)
        if isinstance(output, dict) and isinstance(output.get("sha256"), str):
            return output["sha256"]
    value = component.get(f"{label}_sha256")
    if not isinstance(value, str):
        raise UiFontError(f"base validation has no {label} component hash")
    return value


def _load_base_font_baseline(
    project_root: Path,
    document: Mapping[str, object],
    scene_config: Mapping[str, object],
    validation: Mapping[str, object],
    base_proposal_path: Path,
) -> tuple[dict, dict]:
    reference = document.get("base_font_component")
    if reference is None:
        baseline = scene_config["baseline"]
        raw_paths = {
            "slps": baseline["built_slps"],
            "vt1": baseline["built_vt1"],
        }
    elif isinstance(reference, dict):
        raw_paths = {
            "slps": reference.get("slps"),
            "vt1": reference.get("vt1"),
        }
    else:
        raise UiFontError("base_font_component must be an object")

    paths = {
        label: _project_path(project_root, raw_path)
        for label, raw_path in raw_paths.items()
    }
    for label, path in paths.items():
        if _hash_file(path) != _validation_component_hash(validation, label):
            raise UiFontError(f"locked base {label} component changed")

    slps = paths["slps"].read_bytes()
    vt1 = paths["vt1"].read_bytes()
    font = decode_vt1_font_segment(slps, vt1).decoded
    table = load_text_table(
        _project_path(project_root, scene_config["baseline"]["text_table"])
    )
    base_assignments = _assignment_index(
        _project_path(project_root, scene_config["baseline"]["base_codebook"])
    )
    proposal_assignments = _assignment_index(base_proposal_path)
    root = project_root.resolve()
    return (
        {
            "table": table,
            "extended_entries": read_extended_glyph_table(slps),
            "font": font,
            "base_assignments": base_assignments,
            "proposal_assignments": proposal_assignments,
        },
        {
            label: {
                "path": str(path.relative_to(root)),
                "sha256": _hash_file(path),
                "exact": True,
            }
            for label, path in paths.items()
        },
    )


def _raw_standard_policy_report(
    project_root: Path,
    document: Mapping[str, object],
    source_slps: bytes,
) -> dict | None:
    policy = document.get("allocation_policy")
    if policy is None:
        return None
    if not isinstance(policy, dict):
        raise UiFontError("UI font allocation_policy must be an object")
    if policy.get("mode") != "valid-sjis-then-raw-standard-trail-gaps":
        raise UiFontError("unsupported UI font allocation policy")
    raw_trails = policy.get("raw_standard_trails")
    try:
        trail_values = tuple(int(value, 16) for value in raw_trails)
    except (TypeError, ValueError) as error:
        raise UiFontError("raw standard trail list is invalid") from error
    if trail_values != RAW_STANDARD_TRAILS:
        raise UiFontError("raw standard trail policy drift")

    raw_windows = policy.get("instruction_windows")
    if not isinstance(raw_windows, list) or len(raw_windows) != 2:
        raise UiFontError("raw standard policy needs two instruction windows")
    windows = []
    for raw in raw_windows:
        if not isinstance(raw, dict):
            raise UiFontError("raw standard instruction window is malformed")
        offset = raw.get("file_offset")
        size = raw.get("size")
        expected_hash = raw.get("sha256")
        if (
            not isinstance(offset, int)
            or not isinstance(size, int)
            or size <= 0
            or not isinstance(expected_hash, str)
            or offset < 0
            or offset + size > len(source_slps)
        ):
            raise UiFontError("raw standard instruction window is invalid")
        actual_hash = sha256_bytes(source_slps[offset : offset + size])
        if actual_hash != expected_hash:
            raise UiFontError("raw standard instruction window drift")
        windows.append(
            {
                "name": raw.get("name"),
                "virtual_address": raw.get("virtual_address"),
                "file_offset": offset,
                "size": size,
                "sha256": actual_hash,
            }
        )

    evidence = policy.get("runtime_precedent")
    if not isinstance(evidence, dict):
        raise UiFontError("raw standard policy has no runtime precedent")
    static_path = _project_path(project_root, evidence.get("static_manifest"))
    runtime_path = _project_path(project_root, evidence.get("runtime_manifest"))
    if _hash_file(static_path) != evidence.get("static_sha256"):
        raise UiFontError("raw standard static evidence drift")
    if _hash_file(runtime_path) != evidence.get("runtime_sha256"):
        raise UiFontError("raw standard runtime evidence drift")
    static = _json_object(static_path)
    runtime = _json_object(runtime_path)
    if static.get("status") != evidence.get("required_static_status"):
        raise UiFontError("raw standard static evidence status drift")
    if runtime.get("runtime_acceptance") != evidence.get(
        "required_runtime_acceptance"
    ):
        raise UiFontError("raw standard runtime acceptance drift")
    assignment = {
        "character": evidence.get("character"),
        "code": evidence.get("code"),
        "glyph_index": evidence.get("glyph_index"),
    }
    if not any(
        {
            "character": item.get("character"),
            "code": item.get("code"),
            "glyph_index": item.get("glyph_index"),
        }
        == assignment
        for item in static.get("slot_safety", {}).get("assignments", [])
        if isinstance(item, dict)
    ):
        raise UiFontError("raw standard runtime precedent assignment drift")
    opening = runtime.get("runtime", {}).get("opening_canary", {})
    if (
        assignment["character"] not in opening.get("rendered_text", "")
        or not opening.get("runtime_bytes_exact")
        or not opening.get("characters_visible")
    ):
        raise UiFontError("raw standard runtime precedent is incomplete")

    root = project_root.resolve()
    return {
        "mode": policy["mode"],
        "raw_standard_trails": list(raw_trails),
        "instruction_windows": windows,
        "runtime_precedent": {
            **assignment,
            "static_manifest": str(static_path.relative_to(root)),
            "static_sha256": _hash_file(static_path),
            "runtime_manifest": str(runtime_path.relative_to(root)),
            "runtime_sha256": _hash_file(runtime_path),
            "runtime_bytes_exact": True,
            "characters_visible": True,
        },
        "classification": (
            "Instruction windows prove formula addressability for all listed "
            "trail gaps. Runtime evidence exists for 0x7F only; the combined "
            "P1 component and every additional trail class remain runtime pending."
        ),
    }


def build_ui_font_proposal(
    project_root: Path,
    work_root: Path,
    config_path: Path,
) -> tuple[dict, dict]:
    """Return one inherited UI font proposal and byte-free readiness report."""

    try:
        profile = load_font_profile(project_root, config_path)
    except FontProfileError as error:
        raise UiFontError(str(error)) from error
    document = profile["document"]
    entries, entry_scenes, selection = _selected_font_entries(
        project_root,
        document,
    )
    counts, character_scenes = _character_provenance(entries, entry_scenes)

    scene_config = load_scene_config(
        _project_path(project_root, document["scene_inventory"]["path"])
    )

    registry_path = _project_path(
        project_root,
        document.get("allocation_registry"),
    )
    (
        registry,
        base_registry,
        base_registered,
        registered,
        reactivated,
        retired,
    ) = _load_incremental_registry(
        project_root,
        registry_path,
    )

    validation = _json_object(
        _project_path(
            project_root,
            document.get("base_validation_manifest"),
        )
    )
    base_proposal_path, base_proposal_hash = _validation_proposal_reference(
        project_root,
        validation,
    )
    base_proposal = _json_object(base_proposal_path)
    if (
        base_proposal.get("allocation_registry", {}).get("sha256")
        != (registry["base_registry"]["sha256"])
    ):
        raise UiFontError("base proposal allocation registry drift")
    base_assignments = list(base_proposal.get("assignments", []))
    if not base_assignments:
        raise UiFontError("base proposal has no assignments")
    font_baseline, base_components = _load_base_font_baseline(
        project_root,
        document,
        scene_config,
        validation,
        base_proposal_path,
    )
    demand = audit_entry_font(entries.values(), font_baseline)
    appended = tuple(registry["appended_characters"])
    retired_appended = set(registry["retired_appended_characters"])
    active_appended = tuple(
        character
        for character in appended
        if character not in retired_appended
    )
    allocation_demand = tuple(demand["missing_characters"])
    if (
        tuple(sorted((*active_appended, *reactivated))) != allocation_demand
        or set(active_appended) & set(reactivated)
    ):
        raise UiFontError(
            "UI allocation registry must append or reactivate every missing "
            f"characters: {demand['missing_characters']}"
        )
    original_han = tuple(demand["original_font_han_characters"])
    ratchet = registry.get("ratchet")
    if not isinstance(ratchet, dict):
        raise UiFontError("UI allocation registry has no ratchet")

    try:
        font_lock = load_font_lock(project_root / profile["font_lock"])
        locked_paths = verify_font_lock_files(
            project_root,
            work_root,
            font_lock,
        )
    except FontSourceError as error:
        raise UiFontError(str(error)) from error
    font_source = _font_source_metadata(font_lock)
    if base_proposal.get("font_source") != font_source:
        raise UiFontError("base proposal font source drift")
    if base_proposal.get("rasterizer") != profile["rasterizer"]:
        raise UiFontError("base proposal rasterizer drift")

    source_slps = (work_root / "disc/SLPS_258.87").read_bytes()
    source_vt1 = (work_root / "disc/DATA/VT1.BIN").read_bytes()
    extended_entries = read_extended_glyph_table(source_slps)
    original_font = decode_vt1_font_segment(source_slps, source_vt1).decoded
    table = load_text_table(
        _project_path(
            project_root,
            scene_config["baseline"]["text_table"],
        )
    )
    base_codebook_path = _project_path(
        project_root,
        scene_config["baseline"]["base_codebook"],
    )
    base_codebook = _assignment_index(base_codebook_path)
    reserved_codes = tuple(
        assignment["code_value"] for assignment in base_codebook.values()
    )
    reserved_glyphs = tuple(
        assignment["glyph_index"] for assignment in base_codebook.values()
    )
    legacy_candidates, expanded_candidates = safe_standard_allocation_candidates(
        table,
        extended_entries,
        reserved_codes=reserved_codes,
        reserved_glyphs=reserved_glyphs,
    )
    allocation_policy = _raw_standard_policy_report(
        project_root,
        document,
        source_slps,
    )
    raw_candidates = (
        raw_standard_allocation_candidates(
            table,
            extended_entries,
            reserved_codes=reserved_codes,
            reserved_glyphs=reserved_glyphs,
        )
        if allocation_policy is not None
        else ()
    )
    candidates = (*legacy_candidates, *expanded_candidates, *raw_candidates)
    if len(candidates) < len(registered):
        raise UiFontError("insufficient safe candidates for UI allocation")
    allocation_by_character = dict(zip(registered, candidates))
    assignment_id_prefix = document.get("assignment_id_prefix", "ui-p0")
    allocation_owner = document.get("allocation_owner", "ui/p0")
    if (
        not isinstance(assignment_id_prefix, str)
        or not assignment_id_prefix
        or not isinstance(allocation_owner, str)
        or not allocation_owner
    ):
        raise UiFontError("UI font assignment identity is invalid")
    raw_codes = {code for code, _ in raw_candidates}

    new_allocations = []
    reactivated_set = set(reactivated)
    for character in allocation_demand:
        code, glyph_index = allocation_by_character[character]
        raw_standard = code in raw_codes
        is_reactivated = character in reactivated_set
        new_allocations.append(
            _new_assignment(
                character=character,
                code=code,
                glyph_index=glyph_index,
                mapping=("standard_raw_trail_gap" if raw_standard else "standard"),
                status=(
                    "proposed_reactivation"
                    if is_reactivated
                    else "proposed_allocation"
                ),
                owner=allocation_owner,
                basis=(
                    (
                        "reactivate the character's reserved append-only "
                        "allocation without changing its code or glyph index"
                    )
                    if is_reactivated
                    else
                    (
                        "append-only renderer-addressable raw standard-trail "
                        "gap absent from the pinned text table, ASCII mapping, "
                        "executable extension table and inherited codebook"
                    )
                    if raw_standard
                    else (
                        "append-only valid Shift-JIS slot absent from the "
                        "pinned text table, ASCII mapping, executable extension "
                        "table and inherited codebook"
                    )
                ),
                occurrence_count=counts[character],
                scene_ids=character_scenes[character],
                original_font=original_font,
                rasterizer=profile["rasterizer"],
                font_path=locked_paths["font"],
                assignment_id_prefix=assignment_id_prefix,
            )
        )

    base_by_character = {
        assignment["character"]: assignment for assignment in base_assignments
    }
    new_reraster = []
    for character in original_han:
        if not is_cjk_unified_ideograph(character):
            raise UiFontError("UI reraster selection contains a non-Han character")
        if character in base_by_character:
            raise UiFontError("UI reraster character already exists in base proposal")
        if character in base_codebook:
            code = base_codebook[character]["code_value"]
            mapping = "existing_codebook"
        else:
            code = table.inverse_characters.get(character)
            mapping = "pinned_text_table"
        if code is None:
            raise UiFontError(f"UI reraster code is absent for {character!r}")
        try:
            glyph_index = glyph_index_for_code(code, extended_entries)
        except ValueError as error:
            raise UiFontError(
                f"UI reraster glyph is unreachable for {character!r}"
            ) from error
        new_reraster.append(
            _new_assignment(
                character=character,
                code=code,
                glyph_index=glyph_index,
                mapping=mapping,
                status="proposed_reraster",
                owner=allocation_owner,
                basis=(
                    "existing reachable Han used by the selected UI "
                    "translations; rerasterized to keep one font source"
                ),
                occurrence_count=counts[character],
                scene_ids=character_scenes[character],
                original_font=original_font,
                rasterizer=profile["rasterizer"],
                font_path=locked_paths["font"],
                assignment_id_prefix=assignment_id_prefix,
            )
        )

    assignments = [*base_assignments, *new_allocations, *new_reraster]
    assignments.sort(
        key=lambda assignment: (
            assignment["glyph_index"],
            assignment["code"],
            assignment["character"],
        )
    )
    characters = [assignment["character"] for assignment in assignments]
    codes = [assignment["code"] for assignment in assignments]
    glyphs = [assignment["glyph_index"] for assignment in assignments]
    if (
        len(characters) != len(set(characters))
        or len(codes) != len(set(codes))
        or len(glyphs) != len(set(glyphs))
    ):
        raise UiFontError("combined UI font proposal has an assignment collision")

    remaining = len(candidates) - len(registered)
    checks = {
        "appended_character_count": (
            len(appended) == ratchet["appended_character_count"]
        ),
        "combined_registered_character_count": (
            len(registered) == ratchet["combined_registered_character_count"]
        ),
        "remaining_candidate_slot_count": (
            remaining == ratchet["remaining_candidate_slot_count"]
        ),
        "additional_reraster_existing_han_count": (
            len(new_reraster) == ratchet["additional_reraster_existing_han_count"]
        ),
    }
    if "reactivated_character_count" in ratchet:
        checks["reactivated_character_count"] = (
            len(reactivated) == ratchet["reactivated_character_count"]
        )
    if "additional_allocation_assignment_count" in ratchet:
        checks["additional_allocation_assignment_count"] = (
            len(new_allocations)
            == ratchet["additional_allocation_assignment_count"]
        )
    if not all(checks.values()):
        raise UiFontError(f"UI font ratchet failed: {checks}")

    active_count = (
        base_proposal["allocation_registry"]["active_character_count"]
        + len(appended)
        + len(reactivated)
        - len(retired_appended)
    )
    proposal = {
        "schema_version": 1,
        "proposal_id": profile["profile_id"],
        "status": "static_proposal_not_runtime_verified",
        "stage_indices": profile["scope"]["base_stage_indices"],
        "ui_selection": selection,
        "base_proposal": {
            "path": str(base_proposal_path.relative_to(project_root.resolve())),
            "sha256": base_proposal_hash,
            "proposal_id": base_proposal["proposal_id"],
            "assignment_count": len(base_assignments),
        },
        "base_font_components": base_components,
        "font_source": font_source,
        "selection_policy": profile["scope"],
        "rasterizer": profile["rasterizer"],
        "allocation_registry": {
            "id": registry["registry_id"],
            "sha256": _hash_file(registry_path),
            "base_id": base_registry["registry_id"],
            "base_sha256": registry["base_registry"]["sha256"],
            "registered_character_count": len(registered),
            "active_character_count": active_count,
            "retired_characters": sorted(retired),
        },
        "allocation_assignment_count": (
            base_proposal["allocation_assignment_count"] + len(new_allocations)
        ),
        "reraster_existing_assignment_count": (
            base_proposal["reraster_existing_assignment_count"] + len(new_reraster)
        ),
        "assignments": assignments,
    }
    report = {
        "schema_version": 1,
        "status": "capacity_passed_proposal_generated_runtime_not_tested",
        "font_profile_id": profile["profile_id"],
        "base_font_config": profile["base_font_config"],
        "base_proposal": proposal["base_proposal"],
        "base_font_components": base_components,
        "ui_selection": selection,
        "font_demand_before": {
            "missing_renderer_character_count": demand["missing_character_count"],
            "missing_renderer_characters": demand["missing_characters"],
            "original_font_han_count": demand["original_font_han_count"],
            "original_font_han_characters": demand["original_font_han_characters"],
        },
        "additional_allocations": {
            "count": len(new_allocations),
            "characters": "".join(allocation_demand),
            **(
                {
                    "appended_character_count": len(appended),
                    "appended_characters": "".join(appended),
                    "retired_appended_character_count": len(
                        retired_appended
                    ),
                    "retired_appended_characters": "".join(
                        character
                        for character in appended
                        if character in retired_appended
                    ),
                    "reactivated_character_count": len(reactivated),
                    "reactivated_characters": "".join(reactivated),
                }
                if (
                    "reactivated_characters" in registry
                    or "reactivated_character_count" in ratchet
                )
                else {}
            ),
            "blank_preimage_count": sum(
                assignment["allocation"]["glyph_preimage_all_zero"]
                for assignment in new_allocations
            ),
            "raw_standard_trail_gap_count": sum(
                assignment["mapping"] == "standard_raw_trail_gap"
                for assignment in new_allocations
            ),
        },
        "additional_reraster_existing_han": {
            "count": len(new_reraster),
            "characters": "".join(original_han),
        },
        "capacity": {
            (
                "combined_renderer_addressable_candidate_slot_count"
                if allocation_policy is not None
                else "safe_candidate_slot_count"
            ): len(candidates),
            "valid_sjis_safe_candidate_slot_count": (
                len(legacy_candidates) + len(expanded_candidates)
            ),
            "legacy_safe_candidate_slot_count": len(legacy_candidates),
            "expanded_standard_candidate_slot_count": len(expanded_candidates),
            "raw_standard_addressable_candidate_slot_count": len(raw_candidates),
            "base_registered_character_count": len(base_registered),
            "combined_registered_character_count": len(registered),
            "remaining_candidate_slot_count": remaining,
        },
        "combined_assignments": {
            "allocation_assignment_count": proposal["allocation_assignment_count"],
            "reraster_existing_assignment_count": proposal[
                "reraster_existing_assignment_count"
            ],
            "font_assignment_count": len(assignments),
        },
        "allocation_registry": proposal["allocation_registry"],
        "font_source": font_source,
        "selection_policy": profile["scope"],
        "rasterizer": profile["rasterizer"],
        "ratchet": {
            "expected": ratchet,
            "checks": checks,
            "passed": True,
        },
        "runtime_acceptance": "not tested",
    }
    if allocation_policy is not None:
        proposal["allocation_policy"] = allocation_policy
        report["allocation_policy"] = allocation_policy
    return proposal, report


def audit_ui_font_candidate(
    project_root: Path,
    work_root: Path,
    config_path: Path,
) -> dict:
    """Rebuild planning facts and prove one generated UI font component."""

    expected_proposal, expected_readiness = build_ui_font_proposal(
        project_root,
        work_root,
        config_path,
    )
    profile = load_font_profile(project_root, config_path)
    document = profile["document"]
    outputs = document.get("outputs")
    if not isinstance(outputs, dict):
        raise UiFontError("UI font profile has no outputs")
    proposal_path = _project_path(project_root, outputs.get("proposal"))
    readiness_path = _project_path(project_root, outputs.get("readiness"))
    component_root = _project_path(
        project_root,
        outputs.get("component_root"),
    )
    if _json_object(proposal_path) != expected_proposal:
        raise UiFontError("UI font proposal drift; rerun the profile audit")
    if _json_object(readiness_path) != expected_readiness:
        raise UiFontError("UI font readiness drift; rerun the profile audit")

    component_report_path = component_root / "font-validation.json"
    component_report = _json_object(component_report_path)
    if component_report.get("status") != ("offline_font_validated_runtime_not_tested"):
        raise UiFontError("UI font component status is invalid")
    if (
        component_report.get("allocation_assignment_count")
        != expected_proposal["allocation_assignment_count"]
        or component_report.get("reraster_existing_assignment_count")
        != expected_proposal["reraster_existing_assignment_count"]
        or component_report.get("assignment_count")
        != len(expected_proposal["assignments"])
    ):
        raise UiFontError("UI font component assignment counts drift")

    candidate_slps_path = component_root / "SLPS_258.87"
    candidate_vt1_path = component_root / "DATA/VT1.BIN"
    candidate_slps = candidate_slps_path.read_bytes()
    candidate_vt1 = candidate_vt1_path.read_bytes()
    for label, data in (
        ("slps", candidate_slps),
        ("vt1", candidate_vt1),
    ):
        expected = component_report["outputs"][label]
        if len(data) != expected["size"] or sha256_bytes(data) != expected["sha256"]:
            raise UiFontError(f"UI font {label} component hash drift")

    candidate_font = decode_vt1_font_segment(
        candidate_slps,
        candidate_vt1,
    ).decoded
    if (
        sha256_bytes(candidate_font)
        != component_report["font"]["output_decoded_sha256"]
    ):
        raise UiFontError("UI decoded font hash drift")
    source_slps = (work_root / "disc/SLPS_258.87").read_bytes()
    source_vt1 = (work_root / "disc/DATA/VT1.BIN").read_bytes()
    source_font = decode_vt1_font_segment(source_slps, source_vt1).decoded
    expected_changed_glyphs = []
    for assignment in expected_proposal["assignments"]:
        glyph_index = assignment["glyph_index"]
        start = glyph_index * GLYPH_SIZE
        source_glyph = source_font[start : start + GLYPH_SIZE]
        candidate_glyph = candidate_font[start : start + GLYPH_SIZE]
        if (
            sha256_bytes(source_glyph)
            != assignment["allocation"]["glyph_preimage_sha256"]
        ):
            raise UiFontError(
                f"UI glyph preimage drift for {assignment['character']!r}"
            )
        if sha256_bytes(candidate_glyph) != assignment["raster"]["packed_glyph_sha256"]:
            raise UiFontError(f"UI built raster drift for {assignment['character']!r}")
        if source_glyph != candidate_glyph:
            expected_changed_glyphs.append(glyph_index)
    actual_changed_glyphs = [
        glyph_index
        for glyph_index in range(len(source_font) // GLYPH_SIZE)
        if source_font[glyph_index * GLYPH_SIZE : (glyph_index + 1) * GLYPH_SIZE]
        != candidate_font[glyph_index * GLYPH_SIZE : (glyph_index + 1) * GLYPH_SIZE]
    ]
    if actual_changed_glyphs != sorted(expected_changed_glyphs):
        raise UiFontError("UI font changed outside proposed glyph assignments")
    if len(actual_changed_glyphs) != component_report["changed_glyph_count"]:
        raise UiFontError("UI changed glyph count drift")

    entries, _, selection = _selected_font_entries(project_root, document)
    scene_config = load_scene_config(
        _project_path(project_root, document["scene_inventory"]["path"])
    )
    table = load_text_table(
        _project_path(
            project_root,
            scene_config["baseline"]["text_table"],
        )
    )
    base_assignments = _assignment_index(
        _project_path(
            project_root,
            scene_config["baseline"]["base_codebook"],
        )
    )
    proposal_assignments = _assignment_index(proposal_path)
    coverage = audit_entry_font(
        entries.values(),
        {
            "table": table,
            "extended_entries": read_extended_glyph_table(candidate_slps),
            "font": candidate_font,
            "base_assignments": base_assignments,
            "proposal_assignments": proposal_assignments,
        },
    )
    if coverage["missing_character_count"] != 0:
        raise UiFontError("UI font candidate still has renderer-missing characters")
    if coverage["original_font_han_count"] != 0:
        raise UiFontError("UI font candidate still mixes original reachable Han glyphs")

    base_validation_path = _project_path(
        project_root,
        document["base_validation_manifest"],
    )
    base_components = expected_proposal["base_font_components"]

    contract = document.get("manifest_contract", {})
    if not isinstance(contract, dict):
        raise UiFontError("UI font manifest_contract must be an object")
    manifest_status = contract.get(
        "status",
        "offline_font_and_p0_renderer_coverage_passed_runtime_pending",
    )
    manifest_scope = contract.get(
        "scope",
        (
            "Incremental first-five plus P0 UI font/codebook component. "
            "This does not write UI text, build an ISO or prove runtime "
            "rendering."
        ),
    )
    coverage_key = contract.get("coverage_key", "p0_renderer_coverage")
    base_component_key = contract.get(
        "base_component_key",
        "base_first_five_components",
    )
    base_acceptance_key = contract.get(
        "base_acceptance_key",
        "base_first_five_components_unchanged",
    )
    missing_acceptance_key = contract.get(
        "missing_acceptance_key",
        "p0_renderer_missing_character_count_zero",
    )
    han_acceptance_key = contract.get(
        "han_acceptance_key",
        "p0_original_font_han_count_zero",
    )
    runtime_reason = contract.get(
        "runtime_reason",
        (
            "No P0 UI text writer or combined ISO exists yet; runtime "
            "evidence must bind to that future exact ISO hash."
        ),
    )
    if not all(
        isinstance(value, str) and value
        for value in (
            manifest_status,
            manifest_scope,
            coverage_key,
            base_component_key,
            base_acceptance_key,
            missing_acceptance_key,
            han_acceptance_key,
            runtime_reason,
        )
    ):
        raise UiFontError("UI font manifest contract is invalid")

    acceptance = {
        "proposal_reproduced_exact": True,
        "readiness_reproduced_exact": True,
        base_acceptance_key: True,
        "assignment_counts_exact": True,
        "glyph_preimages_and_rasters_exact": True,
        "codec_round_trip_exact": component_report["font"]["codec_round_trip_exact"],
        "archive_size_preserved": (
            component_report["archive"]["source_size"]
            == component_report["archive"]["output_size"]
        ),
        "offset_reread_exact": component_report["archive"]["offset_reread_exact"],
        missing_acceptance_key: True,
        han_acceptance_key: True,
    }
    if not all(acceptance.values()):
        raise UiFontError(f"UI font candidate acceptance failed: {acceptance}")

    manifest = {
        "schema_version": 1,
        "status": manifest_status,
        "font_profile_id": profile["profile_id"],
        "scope": manifest_scope,
        "inputs": {
            "config": {
                "path": str(config_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(config_path),
            },
            "allocation_registry": {
                "path": document["allocation_registry"],
                "sha256": expected_proposal["allocation_registry"]["sha256"],
            },
            (
                "display_name_selection"
                if "display_name_selection" in document
                else "embedded_scene_selection"
                if "embedded_scene_selection" in document
                else "database_selection"
                if "database_selection" in document
                else "scene_selection"
            ): selection,
            "base_proposal": expected_proposal["base_proposal"],
            "base_validation_manifest": {
                "path": document["base_validation_manifest"],
                "sha256": _hash_file(base_validation_path),
            },
        },
        "capacity": expected_readiness["capacity"],
        "additional_allocations": expected_readiness["additional_allocations"],
        "additional_reraster_existing_han": expected_readiness[
            "additional_reraster_existing_han"
        ],
        "combined_assignments": expected_readiness["combined_assignments"],
        "proposal": {
            "path": str(proposal_path.relative_to(project_root.resolve())),
            "sha256": _hash_file(proposal_path),
        },
        "readiness": {
            "path": str(readiness_path.relative_to(project_root.resolve())),
            "sha256": _hash_file(readiness_path),
        },
        "font_component": {
            "report": str(component_report_path.relative_to(project_root.resolve())),
            "report_sha256": _hash_file(component_report_path),
            "assignment_count": component_report["assignment_count"],
            "allocation_assignment_count": component_report[
                "allocation_assignment_count"
            ],
            "reraster_existing_assignment_count": component_report[
                "reraster_existing_assignment_count"
            ],
            "changed_glyph_count": component_report["changed_glyph_count"],
            "unchanged_assignment_count": component_report[
                "unchanged_assignment_count"
            ],
            "built_raster_hash_exact_count": len(expected_proposal["assignments"]),
            "decoded_size": component_report["font"]["decoded_size"],
            "decoded_sha256": component_report["font"]["output_decoded_sha256"],
            "encoded_size": component_report["font"]["output_encoded_size"],
            "encoder_strategy": component_report["font"]["selected_encoder_strategy"],
            "archive": component_report["archive"],
            "outputs": component_report["outputs"],
        },
        coverage_key: {
            "unique_entry_count": len(entries),
            "literal_character_count": coverage["literal_character_count"],
            "unique_literal_character_count": coverage[
                "unique_literal_character_count"
            ],
            "missing_renderer_character_count": coverage["missing_character_count"],
            "missing_renderer_occurrence_count": coverage[
                "missing_character_occurrence_count"
            ],
            "selected_font_han_count": coverage["selected_font_han_count"],
            "original_font_han_count": coverage["original_font_han_count"],
        },
        base_component_key: base_components,
        "acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "reason": runtime_reason,
        },
    }
    if "allocation_policy" in expected_readiness:
        manifest["allocation_policy"] = expected_readiness["allocation_policy"]
    return manifest


__all__ = [
    "UiFontError",
    "audit_ui_font_candidate",
    "build_ui_font_proposal",
]
