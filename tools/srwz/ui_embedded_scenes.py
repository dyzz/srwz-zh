"""Audit the static scene partition for unclassified embedded SLPS UI text."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping, TextIO

from .menu import parse_menu_file
from .text import encode_text, load_text_table
from .ui_menu import (
    UiMenuError,
    load_ui_font_overrides,
    select_fixed_menu_replacements,
)
from .ui_inventory import (
    UiInventoryError,
    decision_is_complete,
    expand_scene_entries,
    expand_selector,
    load_scene_config,
    rendered_characters,
)


class UiEmbeddedSceneError(ValueError):
    """The embedded UI scene map or one of its locked sources has drifted."""


_CLASSIFICATIONS = {
    "user_facing_candidate",
    "mixed_user_and_diagnostic",
    "diagnostic_or_format_fragment",
}


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiEmbeddedSceneError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise UiEmbeddedSceneError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise UiEmbeddedSceneError("project-relative path must be non-empty text")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiEmbeddedSceneError(f"path escapes project root: {relative}") from error
    return path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_hash(rows: object) -> str:
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_embedded_scene_config(path: Path) -> dict:
    """Load and validate the stable outer shape of the scene map."""

    config = _json_object(path)
    if config.get("schema_version") != 1:
        raise UiEmbeddedSceneError("unsupported embedded UI scene-map schema")
    if not isinstance(config.get("map_id"), str) or not config["map_id"]:
        raise UiEmbeddedSceneError("embedded UI scene map needs a map_id")
    if not isinstance(config.get("aggregate_scene"), dict):
        raise UiEmbeddedSceneError("aggregate_scene must be an object")
    if not isinstance(config.get("source"), dict):
        raise UiEmbeddedSceneError("source must be an object")
    if not isinstance(config.get("writeback_readiness"), dict):
        raise UiEmbeddedSceneError("writeback_readiness must be an object")
    if not isinstance(config.get("ratchet"), dict):
        raise UiEmbeddedSceneError("ratchet must be an object")
    if not isinstance(config.get("scope"), str) or not config["scope"]:
        raise UiEmbeddedSceneError("embedded UI scene map needs a scope")
    groups = config.get("groups")
    if not isinstance(groups, list) or not groups:
        raise UiEmbeddedSceneError("embedded UI scene map needs groups")

    group_ids: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            raise UiEmbeddedSceneError("embedded UI group must be an object")
        group_id = group.get("scene_id")
        if not isinstance(group_id, str) or not group_id:
            raise UiEmbeddedSceneError("embedded UI group needs a scene_id")
        group_ids.append(group_id)
        if not isinstance(group.get("label"), str) or not group["label"]:
            raise UiEmbeddedSceneError(f"{group_id} needs a label")
        if group.get("classification") not in _CLASSIFICATIONS:
            raise UiEmbeddedSceneError(f"{group_id} has invalid classification")
        if group.get("mapping_confidence") not in {
            "static_semantic_cluster_runtime_attribution_pending",
            "mixed_cluster_requires_runtime_split",
            "code_reference_required_before_runtime_route",
        }:
            raise UiEmbeddedSceneError(f"{group_id} has invalid mapping confidence")
        if not isinstance(group.get("selector"), dict):
            raise UiEmbeddedSceneError(f"{group_id} selector must be an object")
        if not isinstance(group.get("fixture_id"), str) or not group["fixture_id"]:
            raise UiEmbeddedSceneError(f"{group_id} needs a fixture_id")
        for field in ("route", "capture_points", "runtime_assertions"):
            value = group.get(field)
            if not isinstance(value, list) or not value:
                raise UiEmbeddedSceneError(f"{group_id} needs non-empty {field}")
            if any(not isinstance(item, str) or not item for item in value):
                raise UiEmbeddedSceneError(f"{group_id} has invalid {field}")
    if len(group_ids) != len(set(group_ids)):
        raise UiEmbeddedSceneError("embedded UI scene IDs must be unique")
    return config


def _source_rows(path: Path, wanted_ids: set[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise UiEmbeddedSceneError(
                        f"invalid source corpus JSONL at line {line_number}"
                    ) from error
                if not isinstance(row, dict):
                    raise UiEmbeddedSceneError(
                        f"source corpus row {line_number} is not an object"
                    )
                entry_id = row.get("id")
                if entry_id not in wanted_ids:
                    continue
                if entry_id in rows:
                    raise UiEmbeddedSceneError(
                        f"duplicate source corpus entry: {entry_id}"
                    )
                rows[entry_id] = row
    except OSError as error:
        raise UiEmbeddedSceneError(f"cannot read source corpus {path}: {error}") from error
    missing = sorted(wanted_ids - set(rows))
    if missing:
        raise UiEmbeddedSceneError(
            f"source corpus is missing embedded UI entries: {missing!r}"
        )
    return rows


def _provenance_summary(rows: list[dict]) -> dict:
    target_offsets: set[int] = set()
    pointer_offsets: set[int] = set()
    embedded_hi: set[int] = set()
    embedded_lo: set[int] = set()
    backing_counts: Counter[str] = Counter()
    ownership_rows = []
    for row in rows:
        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            raise UiEmbeddedSceneError(f"{row.get('id')} has no provenance")
        targets = provenance.get("target_offsets")
        pointers = provenance.get("pointer_offsets")
        hi = provenance.get("embedded_hi")
        lo = provenance.get("embedded_lo")
        for label, values in (
            ("target_offsets", targets),
            ("pointer_offsets", pointers),
            ("embedded_hi", hi),
            ("embedded_lo", lo),
        ):
            if not isinstance(values, list) or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in values
            ):
                raise UiEmbeddedSceneError(
                    f"{row.get('id')} has invalid provenance {label}"
                )
        if len(hi) != len(lo):
            raise UiEmbeddedSceneError(
                f"{row.get('id')} has unmatched embedded HI/LO references"
            )
        target_offsets.update(targets)
        pointer_offsets.update(pointers)
        embedded_hi.update(hi)
        embedded_lo.update(lo)
        if pointers and hi:
            backing = "pointer_and_embedded"
        elif pointers:
            backing = "pointer"
        elif hi:
            backing = "embedded"
        else:
            backing = "unreferenced"
        backing_counts[backing] += 1
        ownership_rows.append(
            {
                "id": row["id"],
                "target_offsets": sorted(set(targets)),
                "pointer_offsets": sorted(set(pointers)),
                "embedded_hi": sorted(set(hi)),
                "embedded_lo": sorted(set(lo)),
            }
        )
    return {
        "unique_target_count": len(target_offsets),
        "pointer_reference_count": len(pointer_offsets),
        "embedded_reference_pair_count": len(embedded_hi),
        "entry_backing_counts": dict(sorted(backing_counts.items())),
        "ownership_sha256": _stable_hash(ownership_rows),
    }


def load_embedded_writeback_baseline(
    project_root: Path,
    reference: Mapping[str, object],
) -> tuple[bytes, bytes, object, object, dict[str, int], dict]:
    writer_config_path = _project_path(
        project_root,
        reference.get("writer_baseline_config"),
    )
    writer_config = _json_object(writer_config_path)
    font_manifest_path = _project_path(
        project_root,
        reference.get("font_manifest"),
    )
    font_manifest = _json_object(font_manifest_path)
    if font_manifest.get("status") != reference.get("required_font_status"):
        raise UiEmbeddedSceneError("embedded UI readiness font status drift")

    source_slps_path = _project_path(
        project_root,
        reference.get("source_slps"),
    )
    source_slps = source_slps_path.read_bytes()
    expected_slps = (
        font_manifest.get("font_component", {})
        .get("outputs", {})
        .get("slps", {})
        .get("sha256")
    )
    if hashlib.sha256(source_slps).hexdigest() != expected_slps:
        raise UiEmbeddedSceneError("embedded UI readiness SLPS hash drift")
    source_vt1_path = _project_path(
        project_root,
        reference.get("source_vt1"),
    )
    source_vt1 = source_vt1_path.read_bytes()
    expected_vt1 = (
        font_manifest.get("font_component", {})
        .get("outputs", {})
        .get("vt1", {})
        .get("sha256")
    )
    if hashlib.sha256(source_vt1).hexdigest() != expected_vt1:
        raise UiEmbeddedSceneError("embedded UI readiness VT1 hash drift")

    descriptor_reference = writer_config.get("menu_descriptor")
    table_reference = writer_config.get("text_table")
    if not isinstance(descriptor_reference, dict) or not isinstance(
        table_reference, dict
    ):
        raise UiEmbeddedSceneError("writer baseline lacks descriptor or text table")
    descriptor_path = _project_path(
        project_root,
        descriptor_reference.get("path"),
    )
    table_path = _project_path(project_root, table_reference.get("path"))
    if _sha256_file(descriptor_path) != descriptor_reference.get("sha256"):
        raise UiEmbeddedSceneError("embedded UI menu descriptor hash drift")
    if _sha256_file(table_path) != table_reference.get("sha256"):
        raise UiEmbeddedSceneError("embedded UI text table hash drift")
    descriptor_document = json.loads(descriptor_path.read_text(encoding="utf-8"))
    if not isinstance(descriptor_document, list):
        raise UiEmbeddedSceneError("embedded UI menu descriptor is not a list")
    descriptors = [
        descriptor
        for descriptor in descriptor_document
        if isinstance(descriptor, dict)
        and descriptor.get("friendly_name")
        == descriptor_reference.get("friendly_name")
    ]
    if len(descriptors) != 1:
        raise UiEmbeddedSceneError("embedded UI SLPS descriptor is not unique")
    table = load_text_table(table_path)
    parsed = parse_menu_file(source_slps, descriptors[0], table)
    try:
        overrides, codebook_report = load_ui_font_overrides(
            project_root,
            writer_config,
            font_manifest,
        )
    except UiMenuError as error:
        raise UiEmbeddedSceneError(str(error)) from error
    return (
        source_slps,
        source_vt1,
        parsed,
        table,
        overrides,
        {
            "writer_baseline_config": {
                "path": str(writer_config_path.relative_to(project_root)),
                "sha256": _sha256_file(writer_config_path),
            },
            "font_manifest": {
                "path": str(font_manifest_path.relative_to(project_root)),
                "sha256": _sha256_file(font_manifest_path),
                "status": font_manifest["status"],
            },
            "source_slps": {
                "path": str(source_slps_path.relative_to(project_root)),
                "size": len(source_slps),
                "sha256": hashlib.sha256(source_slps).hexdigest(),
            },
            "source_vt1": {
                "path": str(source_vt1_path.relative_to(project_root)),
                "size": len(source_vt1),
                "sha256": hashlib.sha256(source_vt1).hexdigest(),
            },
            "menu_descriptor": {
                "path": str(descriptor_path.relative_to(project_root)),
                "sha256": _sha256_file(descriptor_path),
            },
            "text_table": {
                "path": str(table_path.relative_to(project_root)),
                "sha256": _sha256_file(table_path),
            },
            "base_codebook": codebook_report["base_codebook"],
            "proposal": codebook_report["proposal"],
            "override_count": codebook_report["override_count"],
            "policy": reference.get("policy"),
        },
    )


def _group_writeback_readiness(
    source: bytes,
    parsed: object,
    table: object,
    overrides: Mapping[str, int],
    entries: tuple[dict, ...],
) -> dict:
    missing_characters: set[str] = set()
    missing_entry_ids: list[str] = []
    for entry in entries:
        try:
            encode_text(
                entry.get("translation", ""),
                table,
                overrides=overrides,
                terminate=True,
            )
        except ValueError as error:
            matches = re.findall(r"unmapped character '(.+?)'", str(error))
            if not matches:
                raise UiEmbeddedSceneError(
                    f"{entry['id']} failed readiness encoding: {error}"
                ) from error
            missing_characters.update(matches)
            missing_entry_ids.append(entry["id"])
    if missing_entry_ids:
        return {
            "status": "font_extension_required",
            "font_missing_entry_count": len(missing_entry_ids),
            "font_missing_entry_ids": missing_entry_ids,
            "font_missing_character_count": len(missing_characters),
            "font_missing_characters": "".join(sorted(missing_characters)),
            "font_missing_characters_sha256": _stable_hash(
                sorted(missing_characters)
            ),
            "fixed_selected_entry_count": 0,
            "fixed_selected_target_count": 0,
            "excluded_entry_count": len(entries),
            "excluded_reason_counts": {
                "font_extension_required": len(entries),
            },
            "excluded": [],
        }

    decisions = {entry["id"]: entry for entry in entries}
    try:
        _, excluded, selection = select_fixed_menu_replacements(
            source,
            parsed,
            table,
            p0_entries=decisions,
            overrides=overrides,
        )
    except UiMenuError as error:
        raise UiEmbeddedSceneError(str(error)) from error
    status = (
        "fixed_span_ready"
        if selection["selected_entry_count"] == len(entries)
        else "allocation_or_shared_owner_required"
    )
    return {
        "status": status,
        "font_missing_entry_count": 0,
        "font_missing_entry_ids": [],
        "font_missing_character_count": 0,
        "font_missing_characters": "",
        "font_missing_characters_sha256": _stable_hash([]),
        "fixed_selected_entry_count": selection["selected_entry_count"],
        "fixed_selected_target_count": selection["selected_target_count"],
        "selection_sha256": selection["selection_sha256"],
        "excluded_entry_count": selection["excluded_entry_count"],
        "excluded_reason_counts": selection["excluded_reason_counts"],
        "excluded": list(excluded),
    }


def audit_ui_embedded_scenes(project_root: Path, config_path: Path) -> dict:
    """Prove that the proposed groups exactly partition the deferred aggregate."""

    root = project_root.resolve()
    config = load_embedded_scene_config(config_path)
    aggregate_reference = config["aggregate_scene"]
    inventory_path = _project_path(root, aggregate_reference.get("inventory"))
    try:
        inventory = load_scene_config(inventory_path)
    except UiInventoryError as error:
        raise UiEmbeddedSceneError(str(error)) from error
    aggregate_scene_id = aggregate_reference.get("scene_id")
    matching_scenes = [
        scene
        for scene in inventory["scenes"]
        if scene["scene_id"] == aggregate_scene_id
    ]
    if len(matching_scenes) != 1:
        raise UiEmbeddedSceneError("aggregate UI scene is absent or not unique")
    try:
        aggregate_entries = expand_scene_entries(root, matching_scenes[0])
    except UiInventoryError as error:
        raise UiEmbeddedSceneError(str(error)) from error
    aggregate_by_id = {entry["id"]: entry for entry in aggregate_entries}
    expected_aggregate_count = aggregate_reference.get("expected_entry_count")
    if len(aggregate_by_id) != expected_aggregate_count:
        raise UiEmbeddedSceneError(
            "aggregate embedded UI entry count drift: "
            f"{len(aggregate_by_id)} != {expected_aggregate_count}"
        )

    source_reference = config["source"]
    translation_path = _project_path(
        root,
        source_reference.get("translation_file"),
    )
    corpus_path = _project_path(root, source_reference.get("source_corpus"))
    source_rows = _source_rows(corpus_path, set(aggregate_by_id))
    (
        readiness_source,
        _readiness_vt1,
        readiness_parsed,
        readiness_table,
        readiness_overrides,
        readiness_sources,
    ) = load_embedded_writeback_baseline(
        root,
        config["writeback_readiness"],
    )

    all_group_ids: set[str] = set()
    group_reports = []
    classification_entry_counts: Counter[str] = Counter()
    classification_group_counts: Counter[str] = Counter()
    readiness_group_counts: Counter[str] = Counter()
    readiness_entry_counts: Counter[str] = Counter()
    all_font_missing_characters: set[str] = set()
    overflow_entry_count = 0
    fixed_span_ready_user_facing_entry_count = 0
    for group in config["groups"]:
        selector = group["selector"]
        if selector.get("translation_file") != source_reference.get(
            "translation_file"
        ):
            raise UiEmbeddedSceneError(
                f"{group['scene_id']} does not use the locked translation source"
            )
        try:
            entries = expand_selector(root, selector)
        except UiInventoryError as error:
            raise UiEmbeddedSceneError(str(error)) from error
        ids = [entry["id"] for entry in entries]
        overlap = sorted(set(ids) & all_group_ids)
        if overlap:
            raise UiEmbeddedSceneError(
                f"embedded UI groups overlap at {overlap!r}"
            )
        outside = sorted(set(ids) - set(aggregate_by_id))
        if outside:
            raise UiEmbeddedSceneError(
                f"{group['scene_id']} selects entries outside aggregate: {outside!r}"
            )
        all_group_ids.update(ids)
        rows = [source_rows[entry_id] for entry_id in ids]
        for entry, source_row in zip(entries, rows):
            if source_row.get("source_text_sha256") != entry.get(
                "source_text_sha256"
            ):
                raise UiEmbeddedSceneError(
                    f"{entry['id']} source text hash differs across sources"
                )
            if source_row.get("source_member") != "SLPS_258.87":
                raise UiEmbeddedSceneError(
                    f"{entry['id']} does not belong to SLPS_258.87"
                )
        classification = group["classification"]
        classification_entry_counts[classification] += len(entries)
        classification_group_counts[classification] += 1
        decision_rows = [
            {
                "id": entry["id"],
                "source_text_sha256": entry["source_text_sha256"],
                "translation": entry.get("translation"),
                "translation_action": entry.get("translation_action"),
                "editorial_status": entry.get("editorial_status"),
            }
            for entry in entries
        ]
        rendered = {
            character
            for entry in entries
            for character in rendered_characters(entry.get("translation", ""))
        }
        readiness = _group_writeback_readiness(
            readiness_source,
            readiness_parsed,
            readiness_table,
            readiness_overrides,
            entries,
        )
        readiness_group_counts[readiness["status"]] += 1
        readiness_entry_counts[readiness["status"]] += len(entries)
        all_font_missing_characters.update(readiness["font_missing_characters"])
        overflow_entry_count += readiness["excluded_reason_counts"].get(
            "overflow", 0
        )
        if (
            readiness["status"] == "fixed_span_ready"
            and classification == "user_facing_candidate"
        ):
            fixed_span_ready_user_facing_entry_count += len(entries)
        group_reports.append(
            {
                "scene_id": group["scene_id"],
                "label": group["label"],
                "classification": classification,
                "mapping_confidence": group["mapping_confidence"],
                "entry_count": len(entries),
                "first_entry_id": ids[0],
                "last_entry_id": ids[-1],
                "entry_ids_sha256": _stable_hash(ids),
                "decision_complete_count": sum(
                    decision_is_complete(entry) for entry in entries
                ),
                "decision_sha256": _stable_hash(decision_rows),
                "rendered_character_count": len(rendered),
                "preserve_entry_count": sum(
                    entry.get("translation_action") == "preserve"
                    for entry in entries
                ),
                "empty_translation_count": sum(
                    entry.get("translation") == "" for entry in entries
                ),
                "provenance": _provenance_summary(rows),
                "fixture_id": group["fixture_id"],
                "route_step_count": len(group["route"]),
                "capture_point_count": len(group["capture_points"]),
                "runtime_assertion_count": len(group["runtime_assertions"]),
                "runtime_status": "not_tested",
                "writeback_readiness": readiness,
            }
        )

    missing = sorted(set(aggregate_by_id) - all_group_ids)
    if missing:
        raise UiEmbeddedSceneError(
            f"embedded UI scene map leaves entries unclassified: {missing!r}"
        )
    ratchet = config["ratchet"]
    actual_group_counts = dict(sorted(classification_group_counts.items()))
    actual_entry_counts = dict(sorted(classification_entry_counts.items()))
    actual_readiness_group_counts = dict(sorted(readiness_group_counts.items()))
    actual_readiness_entry_counts = dict(sorted(readiness_entry_counts.items()))
    checks = {
        "group_count": len(group_reports) == ratchet.get("group_count"),
        "classified_entry_count": len(all_group_ids)
        == ratchet.get("classified_entry_count"),
        "classification_group_counts": actual_group_counts
        == ratchet.get("classification_group_counts"),
        "classification_entry_counts": actual_entry_counts
        == ratchet.get("classification_entry_counts"),
        "writeback_readiness_counts": actual_readiness_group_counts
        == ratchet.get("writeback_readiness_counts"),
        "fixed_span_ready_entry_count": readiness_entry_counts["fixed_span_ready"]
        == ratchet.get("fixed_span_ready_entry_count"),
        "fixed_span_ready_user_facing_entry_count": (
            fixed_span_ready_user_facing_entry_count
            == ratchet.get("fixed_span_ready_user_facing_entry_count")
        ),
        "font_missing_character_count": len(all_font_missing_characters)
        == ratchet.get("font_missing_character_count"),
        "overflow_entry_count": overflow_entry_count
        == ratchet.get("overflow_entry_count"),
    }
    if not all(checks.values()):
        raise UiEmbeddedSceneError(f"embedded UI ratchet failed: {checks}")

    aggregate_decisions = [
        {
            "id": aggregate_by_id[entry_id]["id"],
            "source_text_sha256": aggregate_by_id[entry_id]["source_text_sha256"],
            "translation": aggregate_by_id[entry_id].get("translation"),
            "translation_action": aggregate_by_id[entry_id].get(
                "translation_action"
            ),
            "editorial_status": aggregate_by_id[entry_id].get("editorial_status"),
        }
        for entry_id in sorted(aggregate_by_id)
    ]
    return {
        "schema_version": 1,
        "status": "static_scene_partition_validated_runtime_attribution_pending",
        "map_id": config["map_id"],
        "scope": config["scope"],
        "sources": {
            "config": {
                "path": str(config_path.resolve().relative_to(root)),
                "sha256": _sha256_file(config_path),
            },
            "scene_inventory": {
                "path": str(inventory_path.relative_to(root)),
                "sha256": _sha256_file(inventory_path),
                "inventory_id": inventory["inventory_id"],
                "aggregate_scene_id": aggregate_scene_id,
            },
            "translation_file": {
                "path": str(translation_path.relative_to(root)),
                "sha256": _sha256_file(translation_path),
            },
            "source_corpus": {
                "path": str(corpus_path.relative_to(root)),
                "sha256": _sha256_file(corpus_path),
            },
            "writeback_readiness": readiness_sources,
        },
        "summary": {
            "group_count": len(group_reports),
            "aggregate_entry_count": len(aggregate_by_id),
            "classified_entry_count": len(all_group_ids),
            "unclassified_entry_count": 0,
            "overlap_entry_count": 0,
            "classification_group_counts": actual_group_counts,
            "classification_entry_counts": actual_entry_counts,
            "writeback_readiness_group_counts": actual_readiness_group_counts,
            "writeback_readiness_entry_counts": actual_readiness_entry_counts,
            "fixed_span_ready_entry_count": readiness_entry_counts[
                "fixed_span_ready"
            ],
            "fixed_span_ready_user_facing_entry_count": (
                fixed_span_ready_user_facing_entry_count
            ),
            "font_missing_character_count": len(all_font_missing_characters),
            "font_missing_characters": "".join(
                sorted(all_font_missing_characters)
            ),
            "font_missing_characters_sha256": _stable_hash(
                sorted(all_font_missing_characters)
            ),
            "overflow_entry_count": overflow_entry_count,
            "decision_complete_count": sum(
                decision_is_complete(entry) for entry in aggregate_by_id.values()
            ),
            "aggregate_decision_sha256": _stable_hash(aggregate_decisions),
            "runtime_passed_group_count": 0,
            "runtime_not_tested_group_count": len(group_reports),
        },
        "ratchet": {
            "expected": ratchet,
            "checks": checks,
            "passed": True,
        },
        "groups": group_reports,
    }


def build_embedded_scene_manifest(report: Mapping[str, object]) -> dict:
    """Project the local audit into a bounded, translation-free manifest."""

    groups = []
    for raw in report["groups"]:
        group = dict(raw)
        readiness = dict(group["writeback_readiness"])
        readiness.pop("font_missing_characters", None)
        group["writeback_readiness"] = readiness
        groups.append(group)
    summary = dict(report["summary"])
    summary.pop("font_missing_characters", None)
    return {
        "schema_version": report["schema_version"],
        "status": report["status"],
        "map_id": report["map_id"],
        "content_policy": (
            "Hashes, counts, stable IDs and runtime gates only; no game bytes, "
            "Japanese source text or localized UI strings are embedded."
        ),
        "scope": report["scope"],
        "sources": report["sources"],
        "summary": summary,
        "ratchet": report["ratchet"],
        "groups": groups,
    }


def write_embedded_scene_tsv(
    report: Mapping[str, object],
    stream: TextIO,
) -> None:
    """Write a compact local review table without copying source game text."""

    fieldnames = [
        "scene_id",
        "label",
        "classification",
        "mapping_confidence",
        "entry_count",
        "first_entry_id",
        "last_entry_id",
        "fixture_id",
        "unique_target_count",
        "pointer_reference_count",
        "embedded_reference_pair_count",
        "writeback_readiness",
        "fixed_selected_entry_count",
        "font_missing_character_count",
        "excluded_entry_count",
        "capture_point_count",
        "runtime_status",
    ]
    writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    for group in report["groups"]:
        provenance = group["provenance"]
        readiness = group["writeback_readiness"]
        writer.writerow(
            {
                **{field: group[field] for field in fieldnames if field in group},
                "unique_target_count": provenance["unique_target_count"],
                "pointer_reference_count": provenance["pointer_reference_count"],
                "embedded_reference_pair_count": provenance[
                    "embedded_reference_pair_count"
                ],
                "writeback_readiness": readiness["status"],
                "fixed_selected_entry_count": readiness[
                    "fixed_selected_entry_count"
                ],
                "font_missing_character_count": readiness[
                    "font_missing_character_count"
                ],
                "excluded_entry_count": readiness["excluded_entry_count"],
            }
        )


__all__ = [
    "UiEmbeddedSceneError",
    "audit_ui_embedded_scenes",
    "build_embedded_scene_manifest",
    "load_embedded_writeback_baseline",
    "load_embedded_scene_config",
    "write_embedded_scene_tsv",
]
