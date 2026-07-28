"""Machine-checkable UI scene selection and coverage audit helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, TextIO

from .codec import decode
from .corpus import text_sha256
from .font import (
    GLYPH_SIZE,
    decode_vt1_font_segment,
    glyph_index_for_code,
    is_cjk_unified_ideograph,
    read_extended_glyph_table,
    sha256_bytes,
)
from .text import (
    control_notation_positions,
    decode_text,
    load_text_table,
)


class UiInventoryError(ValueError):
    """A UI inventory selector, source or ratchet is inconsistent."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiInventoryError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise UiInventoryError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise UiInventoryError("project-relative path must be a non-empty string")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiInventoryError(f"path escapes project root: {relative}") from error
    return path


def load_scene_config(path: Path) -> dict:
    """Load and validate the stable outer shape of a UI scene registry."""

    document = _json_object(path)
    if document.get("schema_version") != 1:
        raise UiInventoryError("unsupported UI scene schema")
    if not isinstance(document.get("inventory_id"), str):
        raise UiInventoryError("UI inventory needs an inventory_id")
    baseline = document.get("baseline")
    ratchet = document.get("ratchet")
    scenes = document.get("scenes")
    if not isinstance(baseline, dict):
        raise UiInventoryError("UI inventory baseline must be an object")
    if not isinstance(ratchet, dict):
        raise UiInventoryError("UI inventory ratchet must be an object")
    if not isinstance(scenes, list) or not scenes:
        raise UiInventoryError("UI inventory needs at least one scene")

    scene_ids = []
    for scene in scenes:
        if not isinstance(scene, dict):
            raise UiInventoryError("UI scene must be an object")
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id:
            raise UiInventoryError("UI scene needs a scene_id")
        scene_ids.append(scene_id)
        if scene.get("priority") not in {"P0", "P1", "P2"}:
            raise UiInventoryError(f"{scene_id} has invalid priority")
        if not isinstance(scene.get("selectors"), list):
            raise UiInventoryError(f"{scene_id} selectors must be a list")
        if not isinstance(scene.get("route"), list) or not scene["route"]:
            raise UiInventoryError(f"{scene_id} needs a runtime route")
        if (
            not isinstance(scene.get("runtime_assertions"), list)
            or not scene["runtime_assertions"]
        ):
            raise UiInventoryError(f"{scene_id} needs runtime assertions")
        if "layout_manifest" in scene and not isinstance(
            scene["layout_manifest"], dict
        ):
            raise UiInventoryError(f"{scene_id} layout_manifest must be an object")
    if len(scene_ids) != len(set(scene_ids)):
        raise UiInventoryError("UI scene IDs must be unique")
    return document


def _range_ids(raw: Mapping[str, object]) -> tuple[str, ...]:
    prefix = raw.get("prefix")
    start = raw.get("start")
    end = raw.get("end")
    width = raw.get("width", 4)
    if not isinstance(prefix, str) or not prefix:
        raise UiInventoryError("entry range prefix must be a non-empty string")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not isinstance(width, int)
        or isinstance(width, bool)
        or start < 0
        or end < start
        or width <= 0
    ):
        raise UiInventoryError("entry range bounds are invalid")
    return tuple(f"{prefix}{index:0{width}d}" for index in range(start, end + 1))


def _translation_entries(path: Path) -> tuple[dict, ...]:
    document = _json_object(path)
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list):
        raise UiInventoryError(f"translation file has no entries list: {path}")
    entries = []
    seen = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise UiInventoryError(f"translation entry is not an object: {path}")
        entry_id = raw.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise UiInventoryError(f"translation entry has no stable ID: {path}")
        if entry_id in seen:
            raise UiInventoryError(f"duplicate translation ID {entry_id}: {path}")
        seen.add(entry_id)
        entries.append(raw)
    return tuple(entries)


def expand_selector(
    project_root: Path, selector: Mapping[str, object]
) -> tuple[dict, ...]:
    """Expand a file/prefix/range selector while preserving source file order."""

    relative = selector.get("translation_file")
    if not isinstance(relative, str):
        raise UiInventoryError("selector needs a translation_file")
    entries = _translation_entries(_project_path(project_root, relative))
    by_id = {entry["id"]: entry for entry in entries}

    requested = set()
    raw_entry_ids = selector.get("entry_ids", [])
    if not isinstance(raw_entry_ids, list) or any(
        not isinstance(entry_id, str) or not entry_id for entry_id in raw_entry_ids
    ):
        raise UiInventoryError(f"selector entry_ids are invalid: {relative}")
    missing_entry_ids = sorted(set(raw_entry_ids) - set(by_id))
    if missing_entry_ids:
        raise UiInventoryError(
            f"selector references IDs absent from {relative}: {missing_entry_ids!r}"
        )
    requested.update(raw_entry_ids)

    raw_prefixes = selector.get("id_prefixes", [])
    if not isinstance(raw_prefixes, list) or any(
        not isinstance(prefix, str) or not prefix for prefix in raw_prefixes
    ):
        raise UiInventoryError(f"selector id_prefixes are invalid: {relative}")
    for prefix in raw_prefixes:
        requested.update(entry_id for entry_id in by_id if entry_id.startswith(prefix))

    raw_ranges = selector.get("id_ranges", [])
    if not isinstance(raw_ranges, list) or any(
        not isinstance(raw_range, dict) for raw_range in raw_ranges
    ):
        raise UiInventoryError(f"selector id_ranges are invalid: {relative}")
    for raw_range in raw_ranges:
        ids = _range_ids(raw_range)
        missing = sorted(set(ids) - set(by_id))
        if missing:
            raise UiInventoryError(
                f"selector references IDs absent from {relative}: {missing!r}"
            )
        requested.update(ids)

    if not raw_entry_ids and not raw_prefixes and not raw_ranges:
        requested.update(by_id)

    raw_excluded_ids = selector.get("exclude_ids", [])
    if not isinstance(raw_excluded_ids, list) or any(
        not isinstance(entry_id, str) or not entry_id for entry_id in raw_excluded_ids
    ):
        raise UiInventoryError(f"selector exclude_ids are invalid: {relative}")
    missing_excluded_ids = sorted(set(raw_excluded_ids) - set(by_id))
    if missing_excluded_ids:
        raise UiInventoryError(
            f"selector excludes IDs absent from {relative}: {missing_excluded_ids!r}"
        )

    raw_excluded = selector.get("exclude_id_ranges", [])
    if not isinstance(raw_excluded, list) or any(
        not isinstance(raw_range, dict) for raw_range in raw_excluded
    ):
        raise UiInventoryError(f"selector exclusions are invalid: {relative}")
    excluded = set(raw_excluded_ids)
    for raw_range in raw_excluded:
        ids = _range_ids(raw_range)
        missing = sorted(set(ids) - set(by_id))
        if missing:
            raise UiInventoryError(
                f"selector excludes IDs absent from {relative}: {missing!r}"
            )
        excluded.update(ids)
    requested.difference_update(excluded)

    selected = tuple(entry for entry in entries if entry["id"] in requested)
    expected = selector.get("expected_entry_count")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        raise UiInventoryError(f"selector needs expected_entry_count: {relative}")
    if len(selected) != expected:
        raise UiInventoryError(
            f"selector count drift for {relative}: {len(selected)} != {expected}"
        )
    return selected


def expand_scene_entries(
    project_root: Path, scene: Mapping[str, object]
) -> tuple[dict, ...]:
    """Return the unique translation decisions selected by one scene."""

    selected = []
    seen = set()
    for selector in scene["selectors"]:
        if not isinstance(selector, dict):
            raise UiInventoryError("scene selector must be an object")
        for entry in expand_selector(project_root, selector):
            entry_id = entry["id"]
            if entry_id in seen:
                raise UiInventoryError(
                    f"{scene['scene_id']} selects {entry_id} more than once"
                )
            seen.add(entry_id)
            selected.append(entry)
    expected = scene.get("expected_selected_entry_count")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        raise UiInventoryError(
            f"{scene['scene_id']} needs expected_selected_entry_count"
        )
    if len(selected) != expected:
        raise UiInventoryError(
            f"{scene['scene_id']} count drift: {len(selected)} != {expected}"
        )
    return tuple(selected)


_TAG_PREFIX = re.compile(r"@(?=<[A-Za-z0-9_]+:[0-9A-Fa-f]{2}>)")


def rendered_characters(text: str) -> tuple[str, ...]:
    """Return literal glyphs, excluding lossless and runtime format notation."""

    if not isinstance(text, str):
        raise TypeError("rendered text must be a string")
    skipped = set(control_notation_positions(text))
    for match in _TAG_PREFIX.finditer(text):
        skipped.add(match.start())
    return tuple(
        character
        for index, character in enumerate(text)
        if index not in skipped and character != "\n"
    )


def decision_is_complete(entry: Mapping[str, object]) -> bool:
    """A preserve action or non-empty translation is an explicit decision."""

    status = entry.get("editorial_status")
    if status not in {"draft", "reviewed", "final"}:
        return False
    translation = entry.get("translation")
    if not isinstance(translation, str):
        return False
    return bool(translation) or entry.get("translation_action") == "preserve"


def load_source_index(
    project_root: Path, config: Mapping[str, object]
) -> tuple[dict, dict]:
    """Load ignored source corpus and prove it matches the committed manifest."""

    baseline = config["baseline"]
    corpus_path = _project_path(project_root, baseline["source_corpus"])
    manifest_path = _project_path(project_root, baseline["corpus_manifest"])
    manifest = _json_object(manifest_path)
    digest = hashlib.sha256()
    entries = {}
    with corpus_path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                raw = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise UiInventoryError(
                    f"invalid source corpus line {line_number}: {error}"
                ) from error
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                raise UiInventoryError(f"malformed source corpus line {line_number}")
            entry_id = raw["id"]
            if entry_id in entries:
                raise UiInventoryError(f"duplicate source corpus ID: {entry_id}")
            entries[entry_id] = raw
    expected_count = manifest.get("entry_count")
    expected_digest = manifest.get("aggregate_sha256")
    if len(entries) != expected_count:
        raise UiInventoryError(
            f"source corpus count drift: {len(entries)} != {expected_count}"
        )
    if digest.hexdigest() != expected_digest:
        raise UiInventoryError(
            "source corpus aggregate SHA-256 differs from committed manifest"
        )
    return entries, {
        "path": baseline["source_corpus"],
        "entry_count": len(entries),
        "aggregate_sha256": digest.hexdigest(),
        "manifest": baseline["corpus_manifest"],
        "exact": True,
    }


def _assignments(path: Path) -> dict[str, dict]:
    document = _json_object(path)
    raw_assignments = document.get("assignments")
    if not isinstance(raw_assignments, list):
        raise UiInventoryError(f"assignment file has no assignments: {path}")
    result = {}
    for raw in raw_assignments:
        if not isinstance(raw, dict):
            raise UiInventoryError(f"malformed assignment in {path}")
        character = raw.get("character")
        code = raw.get("code")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code, str)
        ):
            raise UiInventoryError(f"malformed assignment in {path}")
        if character in result:
            raise UiInventoryError(f"duplicate character assignment in {path}")
        assignment = dict(raw)
        assignment["code_value"] = int(code, 16)
        result[character] = assignment
    return result


def load_font_baseline(project_root: Path, config: Mapping[str, object]) -> dict:
    """Load the actual first-five executable/font planning baseline once."""

    baseline = config["baseline"]
    table = load_text_table(_project_path(project_root, baseline["text_table"]))
    slps_path = _project_path(project_root, baseline["built_slps"])
    vt1_path = _project_path(project_root, baseline["built_vt1"])
    slps = slps_path.read_bytes()
    vt1 = vt1_path.read_bytes()
    font = decode_vt1_font_segment(slps, vt1).decoded
    base_assignments = _assignments(
        _project_path(project_root, baseline["base_codebook"])
    )
    proposal_assignments = _assignments(
        _project_path(project_root, baseline["font_proposal"])
    )
    capacity = _json_object(_project_path(project_root, baseline["capacity_manifest"]))
    remaining = capacity.get("codebook", {}).get("remaining_candidate_slot_count")
    if not isinstance(remaining, int) or isinstance(remaining, bool):
        raise UiInventoryError("capacity manifest lacks remaining slot count")
    return {
        "table": table,
        "extended_entries": read_extended_glyph_table(slps),
        "font": font,
        "base_assignments": base_assignments,
        "proposal_assignments": proposal_assignments,
        "remaining_candidate_slot_count": remaining,
        "slps_sha256": sha256_bytes(slps),
        "vt1_sha256": sha256_bytes(vt1),
        "decoded_font_sha256": sha256_bytes(font),
    }


def audit_entry_font(
    entries: Iterable[Mapping[str, object]], baseline: Mapping[str, object]
) -> dict:
    """Measure literal translation glyph demand against the actual built font."""

    counts: Counter[str] = Counter()
    for entry in entries:
        translation = entry.get("translation", "")
        if not isinstance(translation, str):
            raise UiInventoryError(f"{entry.get('id')} translation is not text")
        counts.update(rendered_characters(translation))

    table = baseline["table"]
    extended_entries = baseline["extended_entries"]
    font = baseline["font"]
    base_assignments = baseline["base_assignments"]
    proposal_assignments = baseline["proposal_assignments"]
    missing = []
    original_han = []
    selected_han = []

    for character in sorted(counts):
        assignment = proposal_assignments.get(character)
        mapping = "first_five_proposal"
        if assignment is None:
            assignment = base_assignments.get(character)
            mapping = "base_codebook"
        if assignment is None:
            code = table.inverse_characters.get(character)
            mapping = "pinned_text_table"
        else:
            code = assignment["code_value"]

        if code is None:
            missing.append(
                {
                    "character": character,
                    "reason": "unmapped",
                    "occurrence_count": counts[character],
                }
            )
            continue
        try:
            glyph_index = glyph_index_for_code(code, extended_entries)
        except ValueError:
            missing.append(
                {
                    "character": character,
                    "reason": "resolver_unreachable",
                    "occurrence_count": counts[character],
                }
            )
            continue
        glyph = font[glyph_index * GLYPH_SIZE : (glyph_index + 1) * GLYPH_SIZE]
        if not any(glyph) and character not in {" ", "\u3000"}:
            missing.append(
                {
                    "character": character,
                    "reason": "blank_glyph",
                    "occurrence_count": counts[character],
                }
            )
            continue

        if is_cjk_unified_ideograph(character):
            row = {
                "character": character,
                "occurrence_count": counts[character],
                "glyph_index": glyph_index,
                "mapping": mapping,
            }
            if character in proposal_assignments:
                selected_han.append(row)
            else:
                original_han.append(row)

    return {
        "literal_character_count": sum(counts.values()),
        "unique_literal_character_count": len(counts),
        "missing_character_count": len(missing),
        "missing_character_occurrence_count": sum(
            item["occurrence_count"] for item in missing
        ),
        "missing_characters": "".join(item["character"] for item in missing),
        "missing": missing,
        "selected_font_han_count": len(selected_han),
        "original_font_han_count": len(original_han),
        "original_font_han_characters": "".join(
            item["character"] for item in original_han
        ),
    }


def verify_dynamic_sources(
    project_root: Path, config: Mapping[str, object]
) -> tuple[dict, ...]:
    """Verify hash-only probes into currently unparsed dynamic display tables."""

    table = load_text_table(
        _project_path(project_root, config["baseline"]["text_table"])
    )
    reports = []
    for source in config.get("dynamic_sources", []):
        if not isinstance(source, dict):
            raise UiInventoryError("dynamic source must be an object")
        member = _project_path(project_root, source["member"])
        stored = member.read_bytes()
        if source.get("storage") != "srwz_stream":
            raise UiInventoryError(
                f"unsupported dynamic source storage: {source.get('source_id')}"
            )
        decoded = decode(stored).output
        structure_reference = source.get("structure_manifest")
        writer_reference = source.get("writer_manifest")
        if not isinstance(structure_reference, dict) or not isinstance(
            writer_reference, dict
        ):
            raise UiInventoryError(
                f"dynamic source manifests are missing: {source.get('source_id')}"
            )
        structure_path = _project_path(
            project_root,
            structure_reference.get("path"),
        )
        writer_path = _project_path(
            project_root,
            writer_reference.get("path"),
        )
        if sha256_bytes(structure_path.read_bytes()) != structure_reference.get(
            "sha256"
        ):
            raise UiInventoryError("dynamic structure manifest SHA-256 drift")
        structure_manifest = _json_object(structure_path)
        writer_manifest = _json_object(writer_path)
        if structure_manifest.get("status") != structure_reference.get(
            "required_status"
        ):
            raise UiInventoryError("dynamic structure manifest status drift")
        if writer_manifest.get("status") != writer_reference.get("required_status"):
            raise UiInventoryError("dynamic writer manifest status drift")
        structure_source = structure_manifest.get("inputs", {}).get("source_member", {})
        if structure_source.get("sha256") != sha256_bytes(
            stored
        ) or structure_source.get("decoded_sha256") != sha256_bytes(decoded):
            raise UiInventoryError("dynamic structure source identity drift")
        if writer_manifest.get("runtime", {}).get("status") != "not_tested":
            raise UiInventoryError("dynamic writer runtime status is unsupported")
        if writer_manifest.get("selection", {}).get(
            "translation_entry_count"
        ) != writer_reference.get(
            "selected_translation_entry_count"
        ) or writer_manifest.get("remaining_work", {}).get(
            "unselected_non_empty_entry_count"
        ) != writer_reference.get("unselected_non_empty_entry_count"):
            raise UiInventoryError("dynamic writer coverage ratchet drift")
        probes = []
        for raw in source.get("probes", []):
            if not isinstance(raw, dict):
                raise UiInventoryError("dynamic probe must be an object")
            offset = int(raw["decoded_offset"], 0)
            parsed = decode_text(decoded, offset, table)
            actual_hash = text_sha256(parsed.text)
            exact = (
                parsed.consumed == raw["encoded_size_with_terminator"]
                and actual_hash == raw["source_text_sha256"]
            )
            if not exact:
                raise UiInventoryError(f"dynamic probe drift: {raw['semantic_id']}")
            probes.append(
                {
                    "semantic_id": raw["semantic_id"],
                    "decoded_offset": raw["decoded_offset"],
                    "encoded_size_with_terminator": parsed.consumed,
                    "source_text_sha256": actual_hash,
                    "exact": True,
                }
            )
        structure_probes = {
            item["semantic_id"]: item
            for item in structure_manifest.get("probes", [])
            if isinstance(item, dict) and isinstance(item.get("semantic_id"), str)
        }
        for probe in probes:
            structured = structure_probes.get(probe["semantic_id"])
            if (
                structured is None
                or structured.get("decoded_offset") != probe["decoded_offset"]
                or structured.get("source_text_sha256") != probe["source_text_sha256"]
            ):
                raise UiInventoryError(
                    f"dynamic structure probe mismatch: {probe['semantic_id']}"
                )
        reports.append(
            {
                "source_id": source["source_id"],
                "status": source["status"],
                "member": source["member"],
                "stored_size": len(stored),
                "stored_sha256": sha256_bytes(stored),
                "decoded_size": len(decoded),
                "decoded_sha256": sha256_bytes(decoded),
                "structure_manifest": {
                    "path": str(structure_path.relative_to(project_root.resolve())),
                    "sha256": sha256_bytes(structure_path.read_bytes()),
                    "status": structure_manifest["status"],
                    "entry_count": structure_manifest["totals"]["entry_count"],
                    "non_empty_entry_count": structure_manifest["totals"][
                        "non_empty_entry_count"
                    ],
                },
                "writer_manifest": {
                    "path": str(writer_path.relative_to(project_root.resolve())),
                    "sha256": sha256_bytes(writer_path.read_bytes()),
                    "status": writer_manifest["status"],
                    "selected_translation_entry_count": writer_manifest["selection"][
                        "translation_entry_count"
                    ],
                    "unselected_non_empty_entry_count": writer_manifest[
                        "remaining_work"
                    ]["unselected_non_empty_entry_count"],
                    "runtime_status": writer_manifest["runtime"]["status"],
                },
                "probe_count": len(probes),
                "probes": probes,
            }
        )
    return tuple(reports)


def _asset_report(project_root: Path, source: Mapping[str, object]) -> dict:
    manifest = _json_object(_project_path(project_root, source["manifest"]))
    translations = manifest.get("translations")
    actual_count = len(translations) if isinstance(translations, list) else 0
    expected_count = source.get("expected_translation_count")
    required_status = source.get("required_status")
    exact = actual_count == expected_count and manifest.get("status") == required_status
    if not exact:
        raise UiInventoryError(f"asset manifest drift: {source['manifest']}")
    return {
        "manifest": source["manifest"],
        "translation_count": actual_count,
        "status": manifest["status"],
        "exact": True,
    }


def _layout_manifest_report(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    selected_entry_count: int,
) -> dict:
    path = _project_path(project_root, reference.get("path"))
    manifest = _json_object(path)
    selection = manifest.get("selection")
    layout = manifest.get("layout")
    allocation = manifest.get("allocation")
    editorial = manifest.get("editorial")
    font = manifest.get("font_capacity")
    runtime = manifest.get("runtime")
    if not all(
        isinstance(value, dict)
        for value in (selection, layout, allocation, editorial, font, runtime)
    ):
        raise UiInventoryError(f"layout manifest shape drift: {reference.get('path')}")

    actual = {
        "required_status": manifest.get("status"),
        "expected_entry_count": selection.get("entry_count"),
        "maximum_line_width": layout.get("maximum_line_width"),
        "fixed_allocation_overflow_count": allocation.get("overflow_count"),
        "editorial_draft_entry_count": editorial.get("status_counts", {}).get("draft"),
        "font_missing_character_count": font.get("missing_character_count"),
        "font_candidate_shortfall": font.get("candidate_shortfall"),
        "runtime_status": runtime.get("status"),
    }
    expected = {key: reference.get(key) for key in actual}
    if actual != expected:
        raise UiInventoryError(
            f"layout manifest ratchet drift: {reference.get('path')}"
        )
    if actual["expected_entry_count"] != selected_entry_count:
        raise UiInventoryError(
            f"layout manifest selection drift: {reference.get('path')}"
        )

    return {
        "path": str(path.relative_to(project_root.resolve())),
        "sha256": sha256_bytes(path.read_bytes()),
        "status": manifest["status"],
        "entry_count": selection["entry_count"],
        "output_line_count": layout.get("output_line_count"),
        "maximum_line_width": layout["maximum_line_width"],
        "fixed_allocation_overflow_count": allocation["overflow_count"],
        "editorial_draft_entry_count": editorial["status_counts"]["draft"],
        "font_missing_character_count": font["missing_character_count"],
        "font_candidate_shortfall": font["candidate_shortfall"],
        "runtime_status": runtime["status"],
    }


def audit_ui_inventory(project_root: Path, config_path: Path) -> dict:
    """Audit selectors, source freshness, font demand and planning ratchets."""

    config = load_scene_config(config_path)
    source_index, source_report = load_source_index(project_root, config)
    font_baseline = load_font_baseline(project_root, config)
    dynamic_reports = verify_dynamic_sources(project_root, config)
    scene_reports = []
    p0_entries = {}

    for scene in config["scenes"]:
        entries = expand_scene_entries(project_root, scene)
        for entry in entries:
            source = source_index.get(entry["id"])
            if source is None:
                raise UiInventoryError(
                    f"{scene['scene_id']} source ID missing: {entry['id']}"
                )
            if source.get("source_text_sha256") != entry.get("source_text_sha256"):
                raise UiInventoryError(
                    f"{scene['scene_id']} source hash drift: {entry['id']}"
                )
        incomplete = [
            entry["id"] for entry in entries if not decision_is_complete(entry)
        ]
        if incomplete:
            raise UiInventoryError(
                f"{scene['scene_id']} has incomplete decisions: {incomplete!r}"
            )
        assets = [
            _asset_report(project_root, raw) for raw in scene.get("asset_sources", [])
        ]
        layout_report = None
        if "layout_manifest" in scene:
            layout_report = _layout_manifest_report(
                project_root,
                scene["layout_manifest"],
                selected_entry_count=len(entries),
            )
        font_report = audit_entry_font(entries, font_baseline)
        if scene["priority"] == "P0":
            for entry in entries:
                previous = p0_entries.setdefault(entry["id"], entry)
                if previous != entry:
                    raise UiInventoryError(
                        f"P0 translation decision differs for {entry['id']}"
                    )
        scene_reports.append(
            {
                "scene_id": scene["scene_id"],
                "priority": scene["priority"],
                "label": scene["label"],
                "category": scene["category"],
                "selected_entry_count": len(entries),
                "decision_complete_count": len(entries),
                "asset_translation_count": sum(
                    item["translation_count"] for item in assets
                ),
                "font": font_report,
                "assets": assets,
                "layout": layout_report,
                "implementation": scene["implementation"],
                "runtime_route_step_count": len(scene["route"]),
                "runtime_assertion_count": len(scene["runtime_assertions"]),
            }
        )

    p0_font = audit_entry_font(p0_entries.values(), font_baseline)
    remaining = font_baseline["remaining_candidate_slot_count"]
    margin = remaining - p0_font["missing_character_count"]
    ratchet = config["ratchet"]
    ratchet_checks = {
        "p0_unique_entry_count": (len(p0_entries) == ratchet["p0_unique_entry_count"]),
        "p0_missing_renderer_character_limit": (
            p0_font["missing_character_count"]
            <= ratchet["p0_missing_renderer_character_limit"]
        ),
        "p0_candidate_slot_margin": (
            margin >= ratchet["p0_minimum_candidate_slot_margin"]
        ),
    }
    if not all(ratchet_checks.values()):
        raise UiInventoryError(f"UI P0 ratchet failed: {ratchet_checks}")

    priority_counts = Counter(scene["priority"] for scene in scene_reports)
    report = {
        "schema_version": 1,
        "status": "inventory_passed_work_remaining",
        "inventory_id": config["inventory_id"],
        "scope": (
            "Scene selection, source freshness, translation-decision coverage, "
            "current first-five font demand and hash-only dynamic probes. "
            "This is not writer, ISO or runtime acceptance."
        ),
        "source_corpus": source_report,
        "font_baseline": {
            "slps_sha256": font_baseline["slps_sha256"],
            "vt1_sha256": font_baseline["vt1_sha256"],
            "decoded_font_sha256": font_baseline["decoded_font_sha256"],
            "remaining_candidate_slot_count": remaining,
            "interpretation": (
                "Planning baseline only; a future UI candidate must rebuild "
                "and revalidate the exact font and ISO."
            ),
        },
        "dynamic_sources": list(dynamic_reports),
        "summary": {
            "scene_count": len(scene_reports),
            "priority_scene_counts": dict(sorted(priority_counts.items())),
            "p0_unique_entry_count": len(p0_entries),
            "p0_missing_renderer_character_count": p0_font["missing_character_count"],
            "p0_missing_renderer_characters": p0_font["missing_characters"],
            "p0_original_font_han_count": p0_font["original_font_han_count"],
            "p0_remaining_candidate_slot_count": remaining,
            "p0_candidate_slot_margin": margin,
            "dynamic_probe_count": sum(
                source["probe_count"] for source in dynamic_reports
            ),
        },
        "ratchet": {
            "expected": ratchet,
            "checks": ratchet_checks,
            "passed": True,
        },
        "scenes": scene_reports,
    }
    return report


def build_inventory_manifest(report: Mapping[str, object]) -> dict:
    """Project a bounded, source-text-free manifest from a full local report."""

    scenes = []
    for scene in report["scenes"]:
        projected = {
            "scene_id": scene["scene_id"],
            "priority": scene["priority"],
            "label": scene["label"],
            "category": scene["category"],
            "selected_entry_count": scene["selected_entry_count"],
            "decision_complete_count": scene["decision_complete_count"],
            "asset_translation_count": scene["asset_translation_count"],
            "missing_renderer_character_count": scene["font"][
                "missing_character_count"
            ],
            "assets": scene["assets"],
            "implementation": scene["implementation"],
            "runtime_route_step_count": scene["runtime_route_step_count"],
            "runtime_assertion_count": scene["runtime_assertion_count"],
        }
        if scene.get("layout") is not None:
            projected["layout"] = scene["layout"]
        scenes.append(projected)

    return {
        "schema_version": 1,
        "status": report["status"],
        "inventory_id": report["inventory_id"],
        "scope": report["scope"],
        "source_corpus": report["source_corpus"],
        "font_baseline": report["font_baseline"],
        "summary": report["summary"],
        "ratchet": report["ratchet"],
        "dynamic_sources": report["dynamic_sources"],
        "scenes": scenes,
    }


def write_scene_tsv(report: Mapping[str, object], stream: TextIO) -> None:
    """Write a compact planning matrix without source Japanese text."""

    fieldnames = (
        "priority",
        "scene_id",
        "label",
        "selected_entry_count",
        "asset_translation_count",
        "missing_character_count",
        "missing_characters",
        "original_font_han_count",
        "text_state",
        "asset_state",
        "integration_state",
    )
    writer = csv.DictWriter(
        stream,
        fieldnames=fieldnames,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    for scene in report["scenes"]:
        implementation = scene["implementation"]
        writer.writerow(
            {
                "priority": scene["priority"],
                "scene_id": scene["scene_id"],
                "label": scene["label"],
                "selected_entry_count": scene["selected_entry_count"],
                "asset_translation_count": scene["asset_translation_count"],
                "missing_character_count": scene["font"]["missing_character_count"],
                "missing_characters": scene["font"]["missing_characters"],
                "original_font_han_count": scene["font"]["original_font_han_count"],
                "text_state": implementation["text"],
                "asset_state": implementation["asset"],
                "integration_state": implementation["integration"],
            }
        )


__all__ = [
    "UiInventoryError",
    "audit_entry_font",
    "audit_ui_inventory",
    "build_inventory_manifest",
    "decision_is_complete",
    "expand_scene_entries",
    "expand_selector",
    "load_font_baseline",
    "load_scene_config",
    "load_source_index",
    "rendered_characters",
    "verify_dynamic_sources",
    "write_scene_tsv",
]
