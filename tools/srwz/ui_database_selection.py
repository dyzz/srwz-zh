"""Select and audit a bounded fixed-span subset of the large UI databases."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Mapping

from .codec import decode
from .font import (
    decode_vt1_font_segment,
    read_extended_glyph_table,
    sha256_bytes,
)
from .menu import parse_menu_file
from .text import augment_text_table, load_text_table
from .ui_inventory import (
    UiInventoryError,
    audit_entry_font,
    expand_scene_entries,
    expand_selector,
    load_scene_config,
)
from .ui_menu import (
    UiMenuError,
    build_fixed_menu_slice,
    load_ui_font_overrides,
)


class UiDatabaseSelectionError(ValueError):
    """A database subset, source lock or fixed-span ratchet is inconsistent."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiDatabaseSelectionError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise UiDatabaseSelectionError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise UiDatabaseSelectionError("project path must be a non-empty string")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiDatabaseSelectionError(f"path escapes project root: {relative}") from error
    return path


def _file_lock(project_root: Path, path: Path) -> dict:
    resolved = path.resolve()
    return {
        "path": str(resolved.relative_to(project_root.resolve())),
        "sha256": sha256_bytes(resolved.read_bytes()),
    }


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _assignment_index(path: Path) -> dict[str, dict]:
    document = _json_object(path)
    raw_assignments = document.get("assignments")
    if not isinstance(raw_assignments, list):
        raise UiDatabaseSelectionError(f"assignment file has no assignments: {path}")
    assignments = {}
    for raw in raw_assignments:
        if not isinstance(raw, dict):
            raise UiDatabaseSelectionError(f"malformed assignment in {path}")
        character = raw.get("character")
        code = raw.get("code")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code, str)
        ):
            raise UiDatabaseSelectionError(f"malformed assignment in {path}")
        if character in assignments:
            raise UiDatabaseSelectionError(f"duplicate assignment in {path}")
        assignment = dict(raw)
        assignment["code_value"] = int(code, 16)
        assignments[character] = assignment
    return assignments


def load_database_selection_config(path: Path) -> dict:
    """Load and validate the stable outer shape of a database subset."""

    document = _json_object(path)
    if document.get("schema_version") != 1:
        raise UiDatabaseSelectionError("unsupported database selection schema")
    if not isinstance(document.get("selection_id"), str):
        raise UiDatabaseSelectionError("database selection needs a selection_id")
    parent = document.get("parent_scene")
    families = document.get("families")
    if not isinstance(parent, dict):
        raise UiDatabaseSelectionError("database selection needs a parent_scene")
    if not isinstance(families, list) or not families:
        raise UiDatabaseSelectionError("database selection needs families")
    family_ids = []
    runtime_scene_ids = []
    for family in families:
        if not isinstance(family, dict):
            raise UiDatabaseSelectionError("database family must be an object")
        family_id = family.get("family_id")
        runtime_scene_id = family.get("runtime_scene_id")
        selectors = family.get("selectors")
        expected = family.get("expected_entry_count")
        if (
            not isinstance(family_id, str)
            or not family_id
            or not isinstance(runtime_scene_id, str)
            or not runtime_scene_id
            or not isinstance(selectors, list)
            or not selectors
            or not isinstance(expected, int)
            or isinstance(expected, bool)
            or expected <= 0
        ):
            raise UiDatabaseSelectionError("database family contract is invalid")
        family_ids.append(family_id)
        runtime_scene_ids.append(runtime_scene_id)
    if len(family_ids) != len(set(family_ids)):
        raise UiDatabaseSelectionError("database family IDs must be unique")
    if len(runtime_scene_ids) != len(set(runtime_scene_ids)):
        raise UiDatabaseSelectionError("database runtime scene IDs must be unique")
    return document


def select_database_entries(
    project_root: Path,
    config_path: Path,
) -> tuple[dict[str, dict], dict[str, set[str]], dict]:
    """Return the exact selected decisions and their runtime-family ownership."""

    document = load_database_selection_config(config_path)
    inventory_reference = document["parent_scene"].get("inventory")
    if not isinstance(inventory_reference, dict):
        raise UiDatabaseSelectionError("database parent has no inventory")
    inventory_path = _project_path(
        project_root,
        inventory_reference.get("path"),
    )
    inventory_lock = _file_lock(project_root, inventory_path)
    if inventory_lock["sha256"] != inventory_reference.get("sha256"):
        raise UiDatabaseSelectionError("database parent inventory SHA-256 drift")
    inventory = load_scene_config(inventory_path)
    if inventory["inventory_id"] != inventory_reference.get("inventory_id"):
        raise UiDatabaseSelectionError("database parent inventory ID drift")
    parent_scene_id = document["parent_scene"].get("scene_id")
    parent_matches = [
        scene for scene in inventory["scenes"] if scene["scene_id"] == parent_scene_id
    ]
    if len(parent_matches) != 1:
        raise UiDatabaseSelectionError("database parent scene is not unique")
    try:
        parent_entries = expand_scene_entries(project_root, parent_matches[0])
    except UiInventoryError as error:
        raise UiDatabaseSelectionError(str(error)) from error
    expected_parent = document["parent_scene"].get("expected_entry_count")
    if (
        len(parent_entries) != expected_parent
        or parent_matches[0].get("expected_selected_entry_count") != expected_parent
    ):
        raise UiDatabaseSelectionError("database parent entry count drift")
    parent_by_id = {entry["id"]: entry for entry in parent_entries}

    selected: dict[str, dict] = {}
    entry_families: defaultdict[str, set[str]] = defaultdict(set)
    family_reports = []
    translation_paths = {}
    for family in document["families"]:
        family_entries = {}
        selector_reports = []
        for selector in family["selectors"]:
            if not isinstance(selector, dict):
                raise UiDatabaseSelectionError("database selector must be an object")
            try:
                entries = expand_selector(project_root, selector)
            except UiInventoryError as error:
                raise UiDatabaseSelectionError(str(error)) from error
            translation_path = _project_path(
                project_root,
                selector.get("translation_file"),
            )
            translation_paths[selector["translation_file"]] = translation_path
            for entry in entries:
                entry_id = entry["id"]
                if entry_id not in parent_by_id:
                    raise UiDatabaseSelectionError(
                        f"database selection escapes parent: {entry_id}"
                    )
                previous = family_entries.setdefault(entry_id, entry)
                if previous != entry:
                    raise UiDatabaseSelectionError(
                        f"database family decision differs: {entry_id}"
                    )
            selector_reports.append(
                {
                    "translation_file": selector["translation_file"],
                    "entry_count": len(entries),
                    "entry_ids_sha256": _stable_hash(
                        sorted(entry["id"] for entry in entries)
                    ),
                }
            )
        if len(family_entries) != family["expected_entry_count"]:
            raise UiDatabaseSelectionError(
                f"database family count drift: {family['family_id']}"
            )
        for entry_id, entry in family_entries.items():
            previous = selected.setdefault(entry_id, entry)
            if previous != entry:
                raise UiDatabaseSelectionError(
                    f"database selection decision differs: {entry_id}"
                )
            entry_families[entry_id].add(family["runtime_scene_id"])
        family_reports.append(
            {
                "family_id": family["family_id"],
                "runtime_scene_id": family["runtime_scene_id"],
                "label": family.get("label"),
                "entry_count": len(family_entries),
                "slps_entry_count": sum(
                    entry_id.startswith("menu/SLPS/") for entry_id in family_entries
                ),
                "compdata_entry_count": sum(
                    entry_id.startswith("menu/Compdata/")
                    for entry_id in family_entries
                ),
                "entry_ids_sha256": _stable_hash(sorted(family_entries)),
                "selectors": selector_reports,
            }
        )

    if len(selected) != document["ratchet"]["selected_entry_count"]:
        raise UiDatabaseSelectionError("database selected entry count drift")
    protected = document.get("protected_exclusions")
    if not isinstance(protected, list) or not protected:
        raise UiDatabaseSelectionError("database protected exclusions are missing")
    protected_ids = []
    for item in protected:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("entry_id"), str)
            or not isinstance(item.get("reason"), str)
            or not item["reason"]
        ):
            raise UiDatabaseSelectionError("database protected exclusion is invalid")
        entry_id = item["entry_id"]
        if entry_id not in parent_by_id or entry_id in selected:
            raise UiDatabaseSelectionError(
                f"database protected exclusion is not deferred: {entry_id}"
            )
        protected_ids.append(entry_id)
    if len(protected_ids) != len(set(protected_ids)):
        raise UiDatabaseSelectionError("database protected exclusions must be unique")

    deferred_ids = sorted(set(parent_by_id) - set(selected))
    metadata = {
        "selection_id": document["selection_id"],
        "scope": document["scope"],
        "config": _file_lock(project_root, config_path),
        "parent_scene": {
            "inventory": inventory_lock,
            "inventory_id": inventory["inventory_id"],
            "scene_id": parent_scene_id,
            "entry_count": len(parent_by_id),
            "entry_ids_sha256": _stable_hash(sorted(parent_by_id)),
        },
        "families": family_reports,
        "translation_files": [
            _file_lock(project_root, translation_paths[relative])
            for relative in sorted(translation_paths)
        ],
        "selected_entry_count": len(selected),
        "selected_slps_entry_count": sum(
            entry_id.startswith("menu/SLPS/") for entry_id in selected
        ),
        "selected_compdata_entry_count": sum(
            entry_id.startswith("menu/Compdata/") for entry_id in selected
        ),
        "selected_entry_ids_sha256": _stable_hash(sorted(selected)),
        "selected_decisions_sha256": _stable_hash(
            [
                {
                    "id": entry_id,
                    "source_text_sha256": selected[entry_id][
                        "source_text_sha256"
                    ],
                    "translation": selected[entry_id].get("translation"),
                    "translation_action": selected[entry_id].get(
                        "translation_action"
                    ),
                    "editorial_status": selected[entry_id].get("editorial_status"),
                }
                for entry_id in sorted(selected)
            ]
        ),
        "deferred_entry_count": len(deferred_ids),
        "deferred_entry_ids_sha256": _stable_hash(deferred_ids),
        "protected_exclusions": [dict(item) for item in protected],
    }
    return selected, dict(entry_families), metadata


def _verified_manifest_reference(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, dict]:
    path = _project_path(project_root, reference.get("manifest"))
    lock = _file_lock(project_root, path)
    if lock["sha256"] != reference.get("sha256"):
        raise UiDatabaseSelectionError(f"{label} SHA-256 drift")
    return path, _json_object(path)


def _verified_payload(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, bytes]:
    path = _project_path(project_root, reference.get("path"))
    payload = path.read_bytes()
    if (
        len(payload) != reference.get("size")
        or sha256_bytes(payload) != reference.get("sha256")
    ):
        raise UiDatabaseSelectionError(f"{label} payload drift")
    return path, payload


def _synthetic_missing_overrides(
    table,
    inherited: Mapping[str, int],
    missing_characters: str,
) -> dict[str, int]:
    """Assign unique two-byte planning codes; only encoded size is consumed."""

    used = set(table.characters) | set(inherited.values())
    candidates = []
    for lead in range(0x81, 0xFD):
        for trail in range(0x40, 0x100):
            code = (lead << 8) | trail
            if code not in used:
                candidates.append(code)
    if len(candidates) < len(missing_characters):
        raise UiDatabaseSelectionError("insufficient synthetic planning codes")
    return {
        character: code
        for character, code in zip(missing_characters, candidates)
    }


def audit_ui_database_selection(
    project_root: Path,
    config_path: Path,
) -> dict:
    """Prove font demand and fixed-span readiness for one database subset."""

    document = load_database_selection_config(config_path)
    try:
        entries, entry_families, selection = select_database_entries(
            project_root,
            config_path,
        )
    except (UiInventoryError, UiMenuError) as error:
        raise UiDatabaseSelectionError(str(error)) from error

    font_reference = document.get("font_baseline")
    if not isinstance(font_reference, dict):
        raise UiDatabaseSelectionError("database selection has no font baseline")
    font_manifest_path, font_manifest = _verified_manifest_reference(
        project_root,
        font_reference,
        label="database font baseline",
    )
    if font_manifest.get("status") != font_reference.get("required_status"):
        raise UiDatabaseSelectionError("database font baseline status drift")
    writer_config_path = _project_path(
        project_root,
        font_reference.get("writer_baseline_config"),
    )
    writer_config = _json_object(writer_config_path)
    try:
        inherited_overrides, codebook = load_ui_font_overrides(
            project_root,
            writer_config,
            font_manifest,
        )
    except UiMenuError as error:
        raise UiDatabaseSelectionError(str(error)) from error

    base_reference = document.get("base_ui_core")
    if not isinstance(base_reference, dict):
        raise UiDatabaseSelectionError("database selection has no base UI core")
    base_manifest_path, base_manifest = _verified_manifest_reference(
        project_root,
        base_reference,
        label="database base UI core",
    )
    if (
        base_manifest.get("profile_id") != base_reference.get("required_profile_id")
        or base_manifest.get("status") != base_reference.get("required_status")
        or base_manifest.get("runtime", {}).get("status")
        != base_reference.get("required_runtime_status")
    ):
        raise UiDatabaseSelectionError("database base UI core status drift")
    base_payloads = {}
    base_paths = {}
    for output_id in ("slps", "vt1", "compdata", "mtv_pros"):
        reference = base_reference.get("outputs", {}).get(output_id)
        if not isinstance(reference, dict):
            raise UiDatabaseSelectionError(
                f"database base UI output is missing: {output_id}"
            )
        path, payload = _verified_payload(
            project_root,
            reference,
            label=f"database base UI {output_id}",
        )
        manifest_output = base_manifest.get("outputs", {}).get(output_id)
        if (
            not isinstance(manifest_output, dict)
            or manifest_output.get("size") != len(payload)
            or manifest_output.get("sha256") != sha256_bytes(payload)
        ):
            raise UiDatabaseSelectionError(
                f"database base UI manifest output drift: {output_id}"
            )
        base_paths[output_id] = path
        base_payloads[output_id] = payload

    table_reference = document.get("text_table")
    descriptor_reference = document.get("menu_descriptor")
    if not isinstance(table_reference, dict) or not isinstance(
        descriptor_reference,
        dict,
    ):
        raise UiDatabaseSelectionError("database parser inputs are missing")
    table_path = _project_path(project_root, table_reference.get("path"))
    descriptor_path = _project_path(
        project_root,
        descriptor_reference.get("path"),
    )
    if (
        _file_lock(project_root, table_path)["sha256"]
        != table_reference.get("sha256")
        or _file_lock(project_root, descriptor_path)["sha256"]
        != descriptor_reference.get("sha256")
    ):
        raise UiDatabaseSelectionError("database parser input SHA-256 drift")
    table = load_text_table(table_path)
    proposal_reference = font_manifest.get("proposal")
    if not isinstance(proposal_reference, dict):
        raise UiDatabaseSelectionError("database font manifest has no proposal")
    proposal_path = _project_path(
        project_root,
        proposal_reference.get("path"),
    )
    if _file_lock(project_root, proposal_path)["sha256"] != proposal_reference.get(
        "sha256"
    ):
        raise UiDatabaseSelectionError("database font proposal SHA-256 drift")
    font = decode_vt1_font_segment(
        base_payloads["slps"],
        base_payloads["vt1"],
    ).decoded
    if (
        sha256_bytes(font)
        != font_manifest.get("font_component", {}).get("decoded_sha256")
    ):
        raise UiDatabaseSelectionError(
            "database base UI decoded font differs from P7"
        )
    font_demand = audit_entry_font(
        entries.values(),
        {
            "table": table,
            "extended_entries": read_extended_glyph_table(base_payloads["slps"]),
            "font": font,
            "base_assignments": _assignment_index(
                _project_path(project_root, writer_config["base_codebook"]["path"])
            ),
            "proposal_assignments": _assignment_index(proposal_path),
        },
    )
    expected_missing = font_reference.get("expected_missing_characters")
    if font_demand["missing_characters"] != expected_missing:
        raise UiDatabaseSelectionError(
            "database missing-character selection drift: "
            f"{font_demand['missing_characters']!r}"
        )
    planning_overrides = dict(inherited_overrides)
    planning_overrides.update(
        _synthetic_missing_overrides(
            table,
            inherited_overrides,
            font_demand["missing_characters"],
        )
    )

    try:
        descriptors = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise UiDatabaseSelectionError("database menu descriptor is invalid") from error
    if not isinstance(descriptors, list):
        raise UiDatabaseSelectionError("database menu descriptor must be a list")
    source_table = augment_text_table(table, inherited_overrides)
    slps_descriptor = next(
        (
            item
            for item in descriptors
            if isinstance(item, dict) and item.get("friendly_name") == "SLPS"
        ),
        None,
    )
    compdata_descriptor = next(
        (
            item
            for item in descriptors
            if isinstance(item, dict) and item.get("friendly_name") == "Compdata"
        ),
        None,
    )
    if slps_descriptor is None or compdata_descriptor is None:
        raise UiDatabaseSelectionError("database menu descriptors are missing")
    decoded_compdata_result = decode(base_payloads["compdata"])
    if decoded_compdata_result.consumed != len(base_payloads["compdata"]):
        raise UiDatabaseSelectionError("database base COMPDATA has trailing bytes")
    sources = {
        "slps": base_payloads["slps"],
        "compdata": decoded_compdata_result.output,
    }
    parsed = {
        "slps": parse_menu_file(
            sources["slps"],
            slps_descriptor,
            source_table,
        ),
        "compdata": parse_menu_file(
            sources["compdata"],
            compdata_descriptor,
            source_table,
        ),
    }
    member_reports = {}
    for member_id, prefix in (
        ("slps", "menu/SLPS/"),
        ("compdata", "menu/Compdata/"),
    ):
        decisions = {
            entry_id: entry
            for entry_id, entry in entries.items()
            if entry_id.startswith(prefix)
        }
        try:
            _output, slice_report = build_fixed_menu_slice(
                sources[member_id],
                parsed[member_id],
                table,
                decisions=decisions,
                overrides=planning_overrides,
                source_name=f"P9 {member_id} database planning source",
            )
        except UiMenuError as error:
            raise UiDatabaseSelectionError(str(error)) from error
        slice_report.pop("changed_offsets")
        member_reports[member_id] = slice_report

    ratchet = document.get("ratchet")
    if not isinstance(ratchet, dict):
        raise UiDatabaseSelectionError("database selection has no ratchet")
    actual_ratchet = {
        "parent_entry_count": selection["parent_scene"]["entry_count"],
        "selected_entry_count": selection["selected_entry_count"],
        "deferred_entry_count": selection["deferred_entry_count"],
        "selected_slps_entry_count": selection["selected_slps_entry_count"],
        "selected_compdata_entry_count": selection["selected_compdata_entry_count"],
        "missing_renderer_character_count": font_demand["missing_character_count"],
        "slps_no_op_entry_count": member_reports["slps"]["selection"][
            "no_op_entry_count"
        ],
        "slps_selected_write_entry_count": member_reports["slps"]["selection"][
            "selected_write_entry_count"
        ],
        "slps_selected_write_target_count": member_reports["slps"]["selection"][
            "selected_write_target_count"
        ],
        "compdata_no_op_entry_count": member_reports["compdata"]["selection"][
            "no_op_entry_count"
        ],
        "compdata_selected_write_entry_count": member_reports["compdata"][
            "selection"
        ]["selected_write_entry_count"],
        "compdata_selected_write_target_count": member_reports["compdata"][
            "selection"
        ]["selected_write_target_count"],
        "excluded_after_font_entry_count": sum(
            report["selection"]["excluded_entry_count"]
            for report in member_reports.values()
        ),
    }
    checks = {key: actual == ratchet.get(key) for key, actual in actual_ratchet.items()}
    if not all(checks.values()):
        raise UiDatabaseSelectionError(
            f"database selection ratchet failed: {actual_ratchet}"
        )

    family_entry_counts = defaultdict(int)
    for family_ids in entry_families.values():
        for family_id in family_ids:
            family_entry_counts[family_id] += 1
    family_reports = []
    for family in selection["families"]:
        runtime_scene_id = family["runtime_scene_id"]
        family_reports.append(
            {
                **family,
                "entry_count": family_entry_counts[runtime_scene_id],
            }
        )
    return {
        "schema_version": 1,
        "status": "static_database_fixed_subset_selected_font_extension_required",
        "selection_id": document["selection_id"],
        "scope": document["scope"],
        "inputs": {
            "config": selection["config"],
            "parent_scene": selection["parent_scene"],
            "translation_files": selection["translation_files"],
            "font_baseline": {
                "manifest": _file_lock(project_root, font_manifest_path),
                "status": font_manifest["status"],
                "proposal": _file_lock(project_root, proposal_path),
                "writer_baseline_config": _file_lock(
                    project_root,
                    writer_config_path,
                ),
                "codebook": codebook,
            },
            "base_ui_core": {
                "manifest": _file_lock(project_root, base_manifest_path),
                "profile_id": base_manifest["profile_id"],
                "status": base_manifest["status"],
                "runtime_status": base_manifest["runtime"]["status"],
                "outputs": {
                    output_id: _file_lock(project_root, base_paths[output_id])
                    for output_id in base_paths
                },
            },
            "menu_descriptor": _file_lock(project_root, descriptor_path),
            "text_table": _file_lock(project_root, table_path),
        },
        "selection": {
            "selected_entry_count": selection["selected_entry_count"],
            "selected_slps_entry_count": selection["selected_slps_entry_count"],
            "selected_compdata_entry_count": selection[
                "selected_compdata_entry_count"
            ],
            "selected_entry_ids_sha256": selection[
                "selected_entry_ids_sha256"
            ],
            "selected_decisions_sha256": selection[
                "selected_decisions_sha256"
            ],
            "deferred_entry_count": selection["deferred_entry_count"],
            "deferred_entry_ids_sha256": selection[
                "deferred_entry_ids_sha256"
            ],
            "families": family_reports,
            "protected_exclusions": selection["protected_exclusions"],
        },
        "font_demand": {
            "literal_character_count": font_demand["literal_character_count"],
            "unique_literal_character_count": font_demand[
                "unique_literal_character_count"
            ],
            "missing_renderer_character_count": font_demand[
                "missing_character_count"
            ],
            "missing_renderer_characters": font_demand["missing_characters"],
            "missing_renderer_occurrence_count": font_demand[
                "missing_character_occurrence_count"
            ],
            "selected_font_han_count": font_demand["selected_font_han_count"],
            "original_font_han_count": font_demand["original_font_han_count"],
            "original_font_han_characters": font_demand[
                "original_font_han_characters"
            ],
        },
        "fixed_span_readiness": {
            "status": "fixed_span_ready_after_declared_font_extension",
            "planning_code_policy": (
                "Every missing literal receives a unique synthetic two-byte "
                "planning code. The production font profile must allocate the "
                "same character set; only encoded size is consumed here."
            ),
            "members": member_reports,
            "all_selected_entries_covered": (
                actual_ratchet["excluded_after_font_entry_count"] == 0
            ),
            "pointer_write_policy": "forbidden",
        },
        "ratchet": {
            "expected": ratchet,
            "actual": actual_ratchet,
            "checks": checks,
            "passed": True,
        },
        "runtime": {
            "status": "not_tested",
            "reason": (
                "The selection proves bounded font demand and fixed spans only. "
                "It does not build the P10 font, write either member, build an "
                "ISO or prove any database page in PCSX2."
            ),
        },
    }


def build_database_selection_manifest(report: Mapping[str, object]) -> dict:
    """Project the bounded selection facts into a committed manifest."""

    if report.get("status") != (
        "static_database_fixed_subset_selected_font_extension_required"
    ):
        raise UiDatabaseSelectionError("database selection report status is invalid")
    fixed = report["fixed_span_readiness"]
    member_summary = {}
    for member_id, member in fixed["members"].items():
        member_summary[member_id] = {
            "selection": member["selection"],
            "write": member["write"],
            "component": member["component"],
        }
    return {
        "schema_version": 1,
        "status": report["status"],
        "selection_id": report["selection_id"],
        "scope": report["scope"],
        "inputs": report["inputs"],
        "selection": report["selection"],
        "font_demand": report["font_demand"],
        "fixed_span_readiness": {
            "status": fixed["status"],
            "planning_code_policy": fixed["planning_code_policy"],
            "members": member_summary,
            "all_selected_entries_covered": fixed[
                "all_selected_entries_covered"
            ],
            "pointer_write_policy": fixed["pointer_write_policy"],
        },
        "ratchet": report["ratchet"],
        "runtime": report["runtime"],
    }


__all__ = [
    "UiDatabaseSelectionError",
    "audit_ui_database_selection",
    "build_database_selection_manifest",
    "load_database_selection_config",
    "select_database_entries",
]
