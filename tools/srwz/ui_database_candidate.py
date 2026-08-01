"""Build the P10 fixed-span database slice on top of the validated P9 UI core."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .canary import CanaryError
from .codec import decode, reencode_changed_suffix
from .display_names import (
    DisplayNameError,
    load_display_name_source,
    load_full_unit_name_corpus,
    parse_display_names,
)
from .font import decode_vt1_font_segment, sha256_bytes
from .iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from .menu import parse_menu_file
from .text import (
    SrwzTextEncodeError,
    decode_text,
    encode_text,
    load_text_table,
)
from .ui_database_selection import (
    UiDatabaseSelectionError,
    audit_ui_database_selection,
    build_database_selection_manifest,
    select_database_entries,
)
from .ui_menu import (
    UiMenuError,
    augment_ui_source_text_table,
    build_fixed_menu_slice,
    load_ui_font_overrides,
    normalize_ui_font_aliases,
)
from .writeback import replace_archive_chunk_with_preceding_zero_slack
from .writers import WritebackError, build_executable_offset_patch_plan


class UiDatabaseCandidateError(ValueError):
    """The P10 database component or one of its locked inputs has drifted."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiDatabaseCandidateError(
            f"cannot load JSON object {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise UiDatabaseCandidateError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiDatabaseCandidateError("project path must be non-empty text")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiDatabaseCandidateError(
            f"path escapes project root: {raw}"
        ) from error
    return path


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
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


def _stable_hash(value: object) -> str:
    return sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _translation_entries(path: Path) -> dict[str, dict]:
    document = _json_object(path)
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise UiDatabaseCandidateError(
            f"translation corpus has no entries: {path}"
        )
    entries = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise UiDatabaseCandidateError(
                f"malformed translation corpus entry: {path}"
            )
        entry_id = raw.get("id")
        source_sha256 = raw.get("source_text_sha256")
        translation = raw.get("translation")
        editorial_status = raw.get("editorial_status")
        if (
            not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(source_sha256, str)
            or len(source_sha256) != 64
            or not isinstance(translation, str)
            or not isinstance(editorial_status, str)
            or not editorial_status
            or entry_id in entries
        ):
            raise UiDatabaseCandidateError(
                f"invalid translation corpus entry: {path}"
            )
        entries[entry_id] = dict(raw)
    return entries


def _select_translation_entries(
    entries: Mapping[str, dict],
    entry_ids: object,
    *,
    required_editorial_status: object,
    label: str,
) -> dict[str, dict]:
    if (
        not isinstance(entry_ids, list)
        or not entry_ids
        or len(entry_ids) != len(set(entry_ids))
        or not all(isinstance(entry_id, str) for entry_id in entry_ids)
        or not isinstance(required_editorial_status, str)
        or not required_editorial_status
    ):
        raise UiDatabaseCandidateError(f"{label} selection is invalid")
    selected = {}
    for entry_id in entry_ids:
        entry = entries.get(entry_id)
        if entry is None:
            raise UiDatabaseCandidateError(
                f"{label} entry is missing: {entry_id}"
            )
        if entry.get("editorial_status") != required_editorial_status:
            raise UiDatabaseCandidateError(
                f"{label} entry is not finalized: {entry_id}"
            )
        if not entry["translation"]:
            raise UiDatabaseCandidateError(
                f"{label} entry has an empty translation: {entry_id}"
            )
        selected[entry_id] = entry
    return selected


def _apply_direct_fixed_span_text(
    source: bytes,
    table,
    source_table,
    overrides: Mapping[str, int],
    decisions: Mapping[str, Mapping[str, object]],
    records: object,
    *,
    label: str,
    parsed=None,
) -> tuple[bytes, dict]:
    if not isinstance(records, list) or not records:
        raise UiDatabaseCandidateError(
            f"{label} fixed-span records are missing"
        )
    output = bytearray(source)
    reports = []
    owned_offsets = set()
    parsed_entries = (
        {entry.entry_id: entry for entry in parsed.entries}
        if parsed is not None
        else None
    )
    for record in records:
        if not isinstance(record, dict):
            raise UiDatabaseCandidateError(
                f"{label} fixed-span record is malformed"
            )
        entry_id = record.get("entry_id")
        offset = record.get("offset")
        span = record.get("span")
        if (
            not isinstance(entry_id, str)
            or entry_id not in decisions
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
            or not isinstance(span, int)
            or isinstance(span, bool)
            or span <= 1
            or offset + span > len(source)
        ):
            raise UiDatabaseCandidateError(
                f"{label} fixed-span record is invalid"
            )
        if parsed_entries is not None:
            parsed_entry = parsed_entries.get(entry_id)
            if (
                parsed_entry is None
                or set(parsed_entry.target_offsets) != {offset}
            ):
                raise UiDatabaseCandidateError(
                    f"{label} parsed target drift: {entry_id}"
                )
        span_offsets = set(range(offset, offset + span))
        if owned_offsets & span_offsets:
            raise UiDatabaseCandidateError(
                f"{label} fixed-span records overlap"
            )
        owned_offsets.update(span_offsets)
        decision = decisions[entry_id]
        decoded = decode_text(source, offset, source_table)
        source_sha256 = sha256_bytes(decoded.text.encode("utf-8"))
        if source_sha256 != decision.get("source_text_sha256"):
            raise UiDatabaseCandidateError(
                f"{label} source text drift: {entry_id}"
            )
        if decoded.end > offset + span or any(
            source[decoded.end : offset + span]
        ):
            raise UiDatabaseCandidateError(
                f"{label} span or zero padding drift: {entry_id}"
            )
        try:
            encoded = encode_text(
                decision["translation"],
                table,
                overrides=overrides,
                terminate=True,
            )
        except SrwzTextEncodeError as error:
            raise UiDatabaseCandidateError(
                f"{label} cannot be encoded: {entry_id}: {error}"
            ) from error
        if len(encoded) > span:
            raise UiDatabaseCandidateError(
                f"{label} exceeds fixed span: {entry_id}"
            )
        output[offset : offset + span] = encoded + bytes(span - len(encoded))
        reread = normalize_ui_font_aliases(
            decode_text(bytes(output), offset, source_table).text,
            table,
            overrides,
        )
        if reread != decision["translation"]:
            raise UiDatabaseCandidateError(
                f"{label} readback differs: {entry_id}"
            )
        reports.append(
            {
                "entry_id": entry_id,
                "offset": offset,
                "span": span,
                "source_encoded_size": decoded.consumed,
                "output_encoded_size": len(encoded),
                "headroom": span - len(encoded),
                "source_text_sha256": source_sha256,
                "translation_sha256": sha256_bytes(
                    decision["translation"].encode("utf-8")
                ),
                "readback_exact": True,
            }
        )
    if set(decisions) != {report["entry_id"] for report in reports}:
        raise UiDatabaseCandidateError(
            f"{label} decisions and fixed-span records differ"
        )
    changed_offsets = _changed_offsets(source, bytes(output))
    if not set(changed_offsets) <= owned_offsets:
        raise UiDatabaseCandidateError(f"{label} changed unowned bytes")
    report = {
        "entry_count": len(reports),
        "entries": reports,
        "changed_byte_count": len(changed_offsets),
        "difference_range_count": _difference_range_count(changed_offsets),
        "changed_offsets_sha256": _stable_hash(changed_offsets),
        "changed_offsets": changed_offsets,
        "non_target_bytes_unchanged": True,
        "readback_exact": True,
    }
    if parsed_entries is not None:
        pointer_offsets = {
            pointer_offset + byte_offset
            for entry_id in decisions
            for pointer_offset in parsed_entries[entry_id].pointer_offsets
            for byte_offset in range(4)
        }
        if set(changed_offsets) & pointer_offsets:
            raise UiDatabaseCandidateError(f"{label} changed pointer bytes")
        report["pointer_bytes_unchanged"] = True
    return bytes(output), report


def _apply_full_unit_names(
    source: bytes,
    table,
    source_table,
    overrides: Mapping[str, int],
    structure_config: Mapping[str, object],
    original_entries,
    decisions: Mapping[str, Mapping[str, object]],
) -> tuple[bytes, dict]:
    """Write all pointer-backed unit names without modifying pointer bytes."""

    try:
        current = parse_display_names(
            source,
            source_table,
            structure_config,
            verify_text_preimages=False,
        )
    except DisplayNameError as error:
        raise UiDatabaseCandidateError(str(error)) from error
    current_by_id = {entry.entry_id: entry for entry in current.unit_entries}
    original_by_id = {entry.entry_id: entry for entry in original_entries}
    if set(decisions) != set(original_by_id) or set(current_by_id) != set(
        original_by_id
    ):
        raise UiDatabaseCandidateError("full unit-name selection coverage drift")

    output = bytearray(source)
    owned_offsets = set()
    changed_entry_count = 0
    no_op_entry_count = 0
    encoded_sizes = []
    pointer_sites = set()
    for entry_id, decision in decisions.items():
        original = original_by_id[entry_id]
        current_entry = current_by_id[entry_id]
        if (
            current_entry.target_offset != original.target_offset
            or current_entry.pointer_offsets != original.pointer_offsets
            or decision.get("target_offset") != original.target_offset
            or decision.get("capacity") != original.capacity
            or decision.get("pointer_offsets") != list(original.pointer_offsets)
            or decision.get("source_text_sha256")
            != original.source_text_sha256
        ):
            raise UiDatabaseCandidateError(
                f"unit-name structure binding drift: {entry_id}"
            )
        start = original.target_offset
        end = start + original.capacity
        current_end = current_entry.target_offset + current_entry.encoded_size
        if end > len(source) or current_end > end or any(source[current_end:end]):
            raise UiDatabaseCandidateError(
                f"unit-name fixed allocation drift: {entry_id}"
            )
        span_offsets = set(range(start, end))
        if owned_offsets & span_offsets:
            raise UiDatabaseCandidateError("unit-name target allocations overlap")
        owned_offsets.update(span_offsets)
        try:
            encoded = encode_text(
                decision["translation"],
                table,
                overrides=overrides,
                terminate=True,
            )
        except (SrwzTextEncodeError, ValueError) as error:
            raise UiDatabaseCandidateError(
                f"unit-name encoding failed: {entry_id}: {error}"
            ) from error
        if len(encoded) > original.capacity:
            raise UiDatabaseCandidateError(
                f"unit-name translation overflows {entry_id}: "
                f"{len(encoded)} > {original.capacity}"
            )
        after = encoded + bytes(original.capacity - len(encoded))
        before = source[start:end]
        if after == before:
            no_op_entry_count += 1
        else:
            output[start:end] = after
            changed_entry_count += 1
        encoded_sizes.append(len(encoded))
        for pointer_offset in original.pointer_offsets:
            pointer_sites.update(range(pointer_offset, pointer_offset + 4))

    result = bytes(output)
    changed_offsets = _changed_offsets(source, result)
    if any(offset not in owned_offsets for offset in changed_offsets):
        raise UiDatabaseCandidateError(
            "unit-name writer changed bytes outside target allocations"
        )
    if any(source[offset] != result[offset] for offset in pointer_sites):
        raise UiDatabaseCandidateError("unit-name writer modified pointer bytes")
    try:
        reread = parse_display_names(
            result,
            source_table,
            structure_config,
            verify_text_preimages=False,
        )
    except DisplayNameError as error:
        raise UiDatabaseCandidateError(str(error)) from error
    reread_by_id = {entry.entry_id: entry for entry in reread.unit_entries}
    for entry_id, decision in decisions.items():
        actual = normalize_ui_font_aliases(
            reread_by_id[entry_id].text,
            table,
            overrides,
        )
        if actual != decision["translation"]:
            raise UiDatabaseCandidateError(
                f"unit-name reread mismatch: {entry_id}"
            )
    return result, {
        "entry_count": len(decisions),
        "write_entry_count": changed_entry_count,
        "no_op_entry_count": no_op_entry_count,
        "minimum_capacity": min(entry.capacity for entry in original_entries),
        "maximum_capacity": max(entry.capacity for entry in original_entries),
        "minimum_output_headroom": min(
            entry.capacity - size
            for entry, size in zip(original_entries, encoded_sizes)
        ),
        "pointer_count": sum(
            len(entry.pointer_offsets) for entry in original_entries
        ),
        "pointer_bytes_unchanged": True,
        "non_target_bytes_unchanged": True,
        "readback_exact": True,
        "changed_byte_count": len(changed_offsets),
        "changed_offsets_sha256": _stable_hash(changed_offsets),
        "changed_offsets": changed_offsets,
    }


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    if len(before) != len(after):
        raise UiDatabaseCandidateError("fixed member size changed")
    return [
        offset
        for offset, (source_byte, output_byte) in enumerate(zip(before, after))
        if source_byte != output_byte
    ]


def _difference_range_count(offsets: list[int]) -> int:
    if not offsets:
        return 0
    return 1 + sum(
        current != previous + 1
        for previous, current in zip(offsets, offsets[1:])
    )


def _common_prefix_length(before: bytes, after: bytes) -> int:
    return next(
        (
            offset
            for offset, (source_byte, output_byte) in enumerate(
                zip(before, after)
            )
            if source_byte != output_byte
        ),
        min(len(before), len(after)),
    )


def _verified_json_reference(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, dict]:
    path = _project_path(project_root, reference.get("path"))
    if _sha256_path(path) != reference.get("sha256"):
        raise UiDatabaseCandidateError(f"{label} SHA-256 drift")
    value = _json_object(path)
    required_status = reference.get("required_status")
    if required_status is not None and value.get("status") != required_status:
        raise UiDatabaseCandidateError(f"{label} status drift")
    required_profile_id = reference.get("required_profile_id")
    if (
        required_profile_id is not None
        and value.get("profile_id") != required_profile_id
    ):
        raise UiDatabaseCandidateError(f"{label} profile drift")
    required_font_profile_id = reference.get("required_font_profile_id")
    if (
        required_font_profile_id is not None
        and value.get("font_profile_id") != required_font_profile_id
    ):
        raise UiDatabaseCandidateError(f"{label} font profile drift")
    required_selection_id = reference.get("required_selection_id")
    if (
        required_selection_id is not None
        and value.get("selection_id") != required_selection_id
    ):
        raise UiDatabaseCandidateError(f"{label} selection ID drift")
    required_runtime_status = reference.get("required_runtime_status")
    if (
        required_runtime_status is not None
        and value.get("runtime", {}).get("status")
        != required_runtime_status
    ):
        raise UiDatabaseCandidateError(f"{label} runtime status drift")
    return path, value


def _verified_payload(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, bytes]:
    path = _project_path(project_root, reference.get("path"))
    payload = path.read_bytes()
    if _payload_lock(payload) != {
        "size": reference.get("size"),
        "sha256": reference.get("sha256"),
    }:
        raise UiDatabaseCandidateError(f"{label} size or SHA-256 drift")
    return path, payload


def _menu_descriptors(path: Path) -> dict[str, dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise UiDatabaseCandidateError(
            "database menu descriptor JSON is invalid"
        ) from error
    if not isinstance(value, list):
        raise UiDatabaseCandidateError(
            "database menu descriptor root must be a list"
        )
    descriptors = {}
    for name in ("SLPS", "Compdata"):
        matches = [
            item
            for item in value
            if isinstance(item, dict) and item.get("friendly_name") == name
        ]
        if len(matches) != 1:
            raise UiDatabaseCandidateError(
                f"database menu descriptor {name} is not unique"
            )
        descriptors[name] = matches[0]
    return descriptors


def _verify_selected_readback(
    source: bytes,
    parsed,
    table,
    overrides: Mapping[str, int],
    decisions: Mapping[str, Mapping[str, object]],
    *,
    label: str,
) -> None:
    output_table = augment_ui_source_text_table(table, overrides)
    parsed_entries = {entry.entry_id: entry for entry in parsed.entries}
    for entry_id, decision in decisions.items():
        parsed_entry = parsed_entries.get(entry_id)
        if parsed_entry is None or not parsed_entry.target_offsets:
            raise UiDatabaseCandidateError(
                f"{label} selected entry has no parsed target: {entry_id}"
            )
        for target_offset in set(parsed_entry.target_offsets):
            if (
                normalize_ui_font_aliases(
                    decode_text(source, target_offset, output_table).text,
                    table,
                    overrides,
                )
                != decision["translation"]
            ):
                raise UiDatabaseCandidateError(
                    f"{label} final readback differs for {entry_id}"
                )


def build_ui_database_candidate(
    project_root: Path,
    config_path: Path,
) -> tuple[dict[str, bytes], dict]:
    """Return the four-member P10 UI core and a deterministic proof report."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiDatabaseCandidateError(
            "unsupported UI database candidate schema"
        )
    profile_id = config.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise UiDatabaseCandidateError(
            "UI database candidate needs a profile_id"
        )

    selection_reference = config.get("database_selection")
    if not isinstance(selection_reference, dict):
        raise UiDatabaseCandidateError(
            "UI database candidate has no database selection"
        )
    selection_config_reference = selection_reference.get("config")
    selection_manifest_reference = selection_reference.get("manifest")
    if not isinstance(selection_config_reference, dict) or not isinstance(
        selection_manifest_reference,
        dict,
    ):
        raise UiDatabaseCandidateError(
            "UI database selection references are invalid"
        )
    selection_config_path = _project_path(
        root,
        selection_config_reference.get("path"),
    )
    if _sha256_path(selection_config_path) != selection_config_reference.get(
        "sha256"
    ):
        raise UiDatabaseCandidateError(
            "UI database selection config SHA-256 drift"
        )
    selection_manifest_path, selection_manifest = _verified_json_reference(
        root,
        selection_manifest_reference,
        label="UI database selection manifest",
    )
    try:
        selection_report = audit_ui_database_selection(
            root,
            selection_config_path,
        )
        reproduced_selection_manifest = build_database_selection_manifest(
            selection_report
        )
        decisions, entry_families, selection_metadata = (
            select_database_entries(root, selection_config_path)
        )
    except UiDatabaseSelectionError as error:
        raise UiDatabaseCandidateError(str(error)) from error
    if reproduced_selection_manifest != selection_manifest:
        raise UiDatabaseCandidateError(
            "UI database selection manifest is not reproducible"
        )

    font_reference = config.get("font_extension")
    if not isinstance(font_reference, dict):
        raise UiDatabaseCandidateError(
            "UI database candidate has no font extension"
        )
    font_manifest_path, font_manifest = _verified_json_reference(
        root,
        font_reference["manifest"],
        label="P10 font manifest",
    )
    font_slps_path, font_slps = _verified_payload(
        root,
        font_reference["slps"],
        label="P10 font SLPS",
    )
    font_vt1_path, font_vt1 = _verified_payload(
        root,
        font_reference["vt1"],
        label="P10 font VT1",
    )
    font_outputs = font_manifest.get("font_component", {}).get("outputs", {})
    if (
        font_outputs.get("slps") != _payload_lock(font_slps)
        or font_outputs.get("vt1") != _payload_lock(font_vt1)
    ):
        raise UiDatabaseCandidateError(
            "P10 font payloads differ from the font manifest"
        )
    font_selection = font_manifest.get("inputs", {}).get(
        "database_selection",
        {},
    )
    font_additional_selections = font_selection.get(
        "additional_translation_selections",
        [],
    )
    if not isinstance(font_additional_selections, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("entry_count"), int)
        or isinstance(item.get("entry_count"), bool)
        for item in font_additional_selections
    ):
        raise UiDatabaseCandidateError(
            "P10 font additional translation selection is invalid"
        )
    font_additional_entry_count = sum(
        item["entry_count"] for item in font_additional_selections
    )
    if (
        font_selection.get("selection_id") != selection_manifest["selection_id"]
        or font_selection.get("database_unique_entry_count") != len(decisions)
        or font_selection.get("database_selection_sha256")
        != selection_manifest["selection"]["selected_decisions_sha256"]
        or font_selection.get("unique_entry_count")
        != len(decisions)
        + font_selection.get("supplemental_translation_selection", {}).get(
            "entry_count",
            -1,
        )
        + font_selection.get("unit_name_selection", {}).get(
            "entry_count",
            -1,
        )
        + font_additional_entry_count
    ):
        raise UiDatabaseCandidateError(
            "P10 font selection binding drift"
        )

    writer_reference = config.get("writer_baseline_config")
    if not isinstance(writer_reference, dict):
        raise UiDatabaseCandidateError(
            "UI database writer baseline is missing"
        )
    writer_config_path = _project_path(root, writer_reference.get("path"))
    if _sha256_path(writer_config_path) != writer_reference.get("sha256"):
        raise UiDatabaseCandidateError(
            "UI database writer baseline SHA-256 drift"
        )
    writer_config = _json_object(writer_config_path)
    try:
        overrides, codebook_report = load_ui_font_overrides(
            root,
            writer_config,
            font_manifest,
        )
    except UiMenuError as error:
        raise UiDatabaseCandidateError(str(error)) from error

    base_reference = config.get("base_ui_core")
    if not isinstance(base_reference, dict):
        raise UiDatabaseCandidateError(
            "UI database candidate has no base UI core"
        )
    base_manifest_path, base_manifest = _verified_json_reference(
        root,
        base_reference["manifest"],
        label="P9 base UI core manifest",
    )
    base_paths = {}
    base_payloads = {}
    for output_id in ("slps", "vt1", "compdata", "mtv_pros"):
        reference = base_reference.get("outputs", {}).get(output_id)
        if not isinstance(reference, dict):
            raise UiDatabaseCandidateError(
                f"P9 base UI output is missing: {output_id}"
            )
        path, payload = _verified_payload(
            root,
            reference,
            label=f"P9 base UI {output_id}",
        )
        manifest_output = base_manifest.get("outputs", {}).get(output_id)
        if not isinstance(manifest_output, dict) or _payload_lock(payload) != {
            "size": manifest_output.get("size"),
            "sha256": manifest_output.get("sha256"),
        }:
            raise UiDatabaseCandidateError(
                f"P9 base UI manifest output drift: {output_id}"
            )
        base_paths[output_id] = path
        base_payloads[output_id] = payload

    descriptor_reference = config.get("menu_descriptor")
    table_reference = config.get("text_table")
    if not isinstance(descriptor_reference, dict) or not isinstance(
        table_reference,
        dict,
    ):
        raise UiDatabaseCandidateError(
            "UI database parser inputs are missing"
        )
    descriptor_path = _project_path(root, descriptor_reference.get("path"))
    table_path = _project_path(root, table_reference.get("path"))
    if _sha256_path(descriptor_path) != descriptor_reference.get("sha256"):
        raise UiDatabaseCandidateError("menu descriptor SHA-256 drift")
    if _sha256_path(table_path) != table_reference.get("sha256"):
        raise UiDatabaseCandidateError("text table SHA-256 drift")
    descriptors = _menu_descriptors(descriptor_path)
    table = load_text_table(table_path)
    source_table = augment_ui_source_text_table(table, overrides)

    polish = config.get("first_five_polish")
    if not isinstance(polish, dict):
        raise UiDatabaseCandidateError(
            "P10 first-five polish configuration is missing"
        )
    stage_title_reference = polish.get("stage_titles")
    opening_profile_reference = polish.get("opening_profile")
    if not isinstance(stage_title_reference, dict) or not isinstance(
        opening_profile_reference,
        dict,
    ):
        raise UiDatabaseCandidateError(
            "P10 first-five polish references are invalid"
        )
    stage_title_path = _project_path(
        root,
        stage_title_reference.get("path"),
    )
    opening_profile_path = _project_path(
        root,
        opening_profile_reference.get("path"),
    )
    if _sha256_path(stage_title_path) != stage_title_reference.get("sha256"):
        raise UiDatabaseCandidateError("first-five stage-title corpus SHA-256 drift")
    if _sha256_path(opening_profile_path) != opening_profile_reference.get(
        "sha256"
    ):
        raise UiDatabaseCandidateError(
            "opening protagonist-profile corpus SHA-256 drift"
        )
    stage_title_decisions = _select_translation_entries(
        _translation_entries(stage_title_path),
        stage_title_reference.get("entry_ids"),
        required_editorial_status=stage_title_reference.get(
            "required_editorial_status"
        ),
        label="first-five stage title",
    )
    stage_title_records = stage_title_reference.get("records")
    if (
        not isinstance(stage_title_records, list)
        or {
            record.get("entry_id")
            for record in stage_title_records
            if isinstance(record, dict)
        }
        != set(stage_title_decisions)
    ):
        raise UiDatabaseCandidateError(
            "first-five stage-title fixed-span records are invalid"
        )
    opening_profile_entries = _translation_entries(opening_profile_path)
    opening_records = opening_profile_reference.get("records")
    if not isinstance(opening_records, list):
        raise UiDatabaseCandidateError(
            "opening protagonist-profile records are invalid"
        )
    opening_profile_decisions = _select_translation_entries(
        opening_profile_entries,
        [
            record.get("entry_id")
            for record in opening_records
            if isinstance(record, dict)
        ],
        required_editorial_status=opening_profile_reference.get(
            "required_editorial_status"
        ),
        label="opening protagonist profile",
    )
    opening_font_selections = [
        item
        for item in font_additional_selections
        if item.get("selection_id") == "opening-protagonist-profile"
    ]
    if len(opening_font_selections) != 1:
        raise UiDatabaseCandidateError(
            "P10 font does not bind the opening protagonist profile"
        )
    opening_font_selection = opening_font_selections[0]
    opening_entry_ids = sorted(opening_profile_decisions)
    if (
        opening_font_selection.get("path")
        != opening_profile_reference.get("path")
        or opening_font_selection.get("sha256")
        != opening_profile_reference.get("sha256")
        or opening_font_selection.get("entry_count")
        != len(opening_profile_decisions)
        or opening_font_selection.get("entry_ids_sha256")
        != _stable_hash(opening_entry_ids)
    ):
        raise UiDatabaseCandidateError(
            "P10 font opening protagonist-profile binding drift"
        )

    unit_reference = config.get("unit_names")
    if not isinstance(unit_reference, dict):
        raise UiDatabaseCandidateError("P10 full unit-name configuration is missing")
    unit_corpus_path = _project_path(root, unit_reference.get("path"))
    unit_structure_path = _project_path(
        root,
        unit_reference.get("structure_config"),
    )
    if _sha256_path(unit_corpus_path) != unit_reference.get("sha256"):
        raise UiDatabaseCandidateError("full unit-name corpus SHA-256 drift")
    if _sha256_path(unit_structure_path) != unit_reference.get(
        "structure_sha256"
    ):
        raise UiDatabaseCandidateError("unit-name structure config SHA-256 drift")
    try:
        (
            unit_structure_config,
            _original_compdata_decoded,
            original_display_names,
            _display_name_context,
        ) = load_display_name_source(root, unit_structure_path)
        unit_name_decisions, unit_name_selection = load_full_unit_name_corpus(
            root,
            unit_corpus_path,
            original_display_names.unit_entries,
        )
    except DisplayNameError as error:
        raise UiDatabaseCandidateError(str(error)) from error
    if len(unit_name_decisions) != unit_reference.get("expected_entry_count"):
        raise UiDatabaseCandidateError("full unit-name entry-count drift")

    decoded_compdata_result = decode(base_payloads["compdata"])
    if decoded_compdata_result.consumed != len(base_payloads["compdata"]):
        raise UiDatabaseCandidateError(
            "P9 COMPDATA compressed member has trailing bytes"
        )
    base_compdata_decoded = decoded_compdata_result.output
    parsed_slps = parse_menu_file(
        base_payloads["slps"],
        descriptors["SLPS"],
        source_table,
    )
    parsed_compdata = parse_menu_file(
        base_compdata_decoded,
        descriptors["Compdata"],
        source_table,
    )
    slps_decisions = {
        entry_id: decision
        for entry_id, decision in decisions.items()
        if entry_id.startswith("menu/SLPS/")
    }
    compdata_decisions = {
        entry_id: decision
        for entry_id, decision in decisions.items()
        if entry_id.startswith("menu/Compdata/")
    }
    if len(slps_decisions) + len(compdata_decisions) != len(decisions):
        raise UiDatabaseCandidateError(
            "UI database selection contains an unsupported member"
        )
    try:
        slps_text_slice, slps_slice_report = build_fixed_menu_slice(
            base_payloads["slps"],
            parsed_slps,
            table,
            decisions=slps_decisions,
            overrides=overrides,
            source_name="P9 SLPS P10 database source",
        )
        database_compdata_decoded, compdata_slice_report = build_fixed_menu_slice(
            base_compdata_decoded,
            parsed_compdata,
            table,
            decisions=compdata_decisions,
            overrides=overrides,
            source_name="P9 decoded COMPDATA P10 database source",
        )
    except UiMenuError as error:
        raise UiDatabaseCandidateError(str(error)) from error

    slps_text_changed_offsets = slps_slice_report.pop("changed_offsets")
    database_compdata_changed_offsets = compdata_slice_report.pop(
        "changed_offsets"
    )
    stage_title_compdata_decoded, stage_title_slice_report = (
        _apply_direct_fixed_span_text(
            database_compdata_decoded,
            table,
            source_table,
            overrides,
            stage_title_decisions,
            stage_title_records,
            label="first-five stage title",
            parsed=parsed_compdata,
        )
    )
    stage_title_changed_offsets = stage_title_slice_report.pop(
        "changed_offsets"
    )
    opening_profile_compdata_decoded, opening_profile_report = _apply_direct_fixed_span_text(
        stage_title_compdata_decoded,
        table,
        source_table,
        overrides,
        opening_profile_decisions,
        opening_records,
        label="opening protagonist profile",
    )
    opening_profile_changed_offsets = opening_profile_report.pop(
        "changed_offsets"
    )
    compdata_decoded, unit_name_report = _apply_full_unit_names(
        opening_profile_compdata_decoded,
        table,
        source_table,
        overrides,
        unit_structure_config,
        original_display_names.unit_entries,
        unit_name_decisions,
    )
    unit_name_changed_offsets = unit_name_report.pop("changed_offsets")
    if set(unit_name_changed_offsets) & {
        *database_compdata_changed_offsets,
        *stage_title_changed_offsets,
        *opening_profile_changed_offsets,
    }:
        raise UiDatabaseCandidateError(
            "unit-name writes overlap database or stage-title writes"
        )
    compdata_changed_offsets = _changed_offsets(
        base_compdata_decoded,
        compdata_decoded,
    )
    codec = config.get("codec")
    if (
        not isinstance(codec, dict)
        or codec.get("mode") != "preserve-prefix-reencode-suffix"
        or codec.get("strategy") != "rust-maximum"
    ):
        raise UiDatabaseCandidateError(
            "UI database COMPDATA codec policy is invalid"
        )
    max_output_size = codec.get("max_output_size")
    sector_size = codec.get("sector_size")
    max_sectors = codec.get("max_sectors")
    if (
        any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for value in (max_output_size, sector_size, max_sectors)
        )
        or max_output_size != sector_size * max_sectors
    ):
        raise UiDatabaseCandidateError(
            "P10 COMPDATA codec sector budget is invalid"
        )
    try:
        output_compdata = reencode_changed_suffix(
            base_payloads["compdata"],
            compdata_decoded,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=max_output_size,
        )
    except (RuntimeError, ValueError) as error:
        raise UiDatabaseCandidateError(
            f"P10 COMPDATA compression failed: {error}"
        ) from error
    output_compdata_result = decode(output_compdata)
    if (
        output_compdata_result.consumed != len(output_compdata)
        or output_compdata_result.output != compdata_decoded
        or output_compdata_result.flags != decoded_compdata_result.flags
    ):
        raise UiDatabaseCandidateError(
            "P10 COMPDATA fails codec round-trip"
        )
    compressed_common_prefix = _common_prefix_length(
        base_payloads["compdata"],
        output_compdata,
    )
    if compressed_common_prefix < codec.get(
        "minimum_preserved_compressed_prefix",
        0,
    ):
        raise UiDatabaseCandidateError(
            "P10 COMPDATA preserved compressed prefix regressed: "
            f"actual={compressed_common_prefix} "
            f"minimum={codec.get('minimum_preserved_compressed_prefix', 0)}"
        )

    chunk_index = font_reference.get("chunk_index")
    archive_alignment = font_reference.get("archive_alignment")
    if (
        font_reference.get("mode")
        != "replace-vt1-font-chunk-and-compose-slps-offset-delta"
        or chunk_index != 2
        or archive_alignment != 16
    ):
        raise UiDatabaseCandidateError(
            "P10 font composition contract is invalid"
        )
    vt1_spec = CORE_ARCHIVE_SPECS["VT1.BIN"]
    base_vt1_offsets = read_executable_archive_offsets(
        base_payloads["slps"],
        vt1_spec,
        len(base_payloads["vt1"]),
    )
    font_vt1_offsets = read_executable_archive_offsets(
        font_slps,
        vt1_spec,
        len(font_vt1),
    )
    stored_font = font_vt1[
        font_vt1_offsets[chunk_index] : font_vt1_offsets[chunk_index + 1]
    ]
    decoded_stored_font = decode(stored_font)
    if any(stored_font[decoded_stored_font.consumed :]):
        raise UiDatabaseCandidateError(
            "P10 font chunk has nonzero archive padding"
        )
    if sha256_bytes(decoded_stored_font.output) != font_manifest.get(
        "font_component",
        {},
    ).get("decoded_sha256"):
        raise UiDatabaseCandidateError(
            "P10 stored font decoded hash drift"
        )
    try:
        (
            output_vt1,
            output_vt1_offsets,
            font_padding_size,
            font_borrowed_zero_slack,
        ) = (
            replace_archive_chunk_with_preceding_zero_slack(
                base_payloads["vt1"],
                base_vt1_offsets,
                chunk_index=chunk_index,
                replacement=stored_font[
                    : decoded_stored_font.consumed
                ],
                alignment=archive_alignment,
            )
        )
        offset_plan = build_executable_offset_patch_plan(
            base_payloads["slps"],
            vt1_spec,
            output_vt1_offsets,
        )
    except (CanaryError, WritebackError) as error:
        raise UiDatabaseCandidateError(str(error)) from error
    font_rebased_slps = offset_plan.apply(base_payloads["slps"])
    if (
        read_executable_archive_offsets(
            font_rebased_slps,
            vt1_spec,
            len(output_vt1),
        )
        != output_vt1_offsets
    ):
        raise UiDatabaseCandidateError(
            "P10 VT1 offsets fail SLPS reread"
        )

    preserved_non_font_vt1_chunk_count = 0
    zero_slack_donor_chunk_index = chunk_index - 1
    for index, (
        base_start,
        base_end,
        output_start,
        output_end,
    ) in enumerate(
        zip(
            base_vt1_offsets,
            base_vt1_offsets[1:],
            output_vt1_offsets,
            output_vt1_offsets[1:],
        )
    ):
        if index == chunk_index:
            continue
        base_chunk = base_payloads["vt1"][base_start:base_end]
        output_chunk = output_vt1[output_start:output_end]
        if index == zero_slack_donor_chunk_index:
            expected_chunk = (
                base_chunk[:-font_borrowed_zero_slack]
                if font_borrowed_zero_slack
                else base_chunk
            )
            donated = (
                base_chunk[-font_borrowed_zero_slack:]
                if font_borrowed_zero_slack
                else b""
            )
            preserved = output_chunk == expected_chunk and not any(donated)
        else:
            preserved = output_chunk == base_chunk
        if not preserved:
            raise UiDatabaseCandidateError(
                f"P10 non-font VT1 chunk {index} changed outside proven "
                "zero padding donation"
            )
        preserved_non_font_vt1_chunk_count += 1

    font_offset_changed_offsets = _changed_offsets(
        base_payloads["slps"],
        font_rebased_slps,
    )
    font_text_overlap = sorted(
        set(font_offset_changed_offsets) & set(slps_text_changed_offsets)
    )
    if font_text_overlap:
        raise UiDatabaseCandidateError(
            "P10 font offset bytes overlap selected SLPS text: "
            f"{font_text_overlap[:16]!r}"
        )
    if any(
        font_rebased_slps[offset] != base_payloads["slps"][offset]
        for offset in slps_text_changed_offsets
    ):
        raise UiDatabaseCandidateError(
            "P10 font offset patch changed a selected SLPS preimage"
        )
    merged_slps = bytearray(font_rebased_slps)
    for offset in slps_text_changed_offsets:
        merged_slps[offset] = slps_text_slice[offset]
    output_slps = bytes(merged_slps)
    final_slps_changed_offsets = _changed_offsets(
        base_payloads["slps"],
        output_slps,
    )
    expected_final_slps_offsets = sorted(
        {*font_offset_changed_offsets, *slps_text_changed_offsets}
    )
    if final_slps_changed_offsets != expected_final_slps_offsets:
        raise UiDatabaseCandidateError(
            "P10 final SLPS delta differs from owned font and text bytes"
        )
    final_font = decode_vt1_font_segment(output_slps, output_vt1).decoded
    if sha256_bytes(final_font) != font_manifest.get(
        "font_component",
        {},
    ).get("decoded_sha256"):
        raise UiDatabaseCandidateError(
            "P10 final decoded font differs from the font extension"
        )

    _verify_selected_readback(
        output_slps,
        parsed_slps,
        table,
        overrides,
        slps_decisions,
        label="P10 SLPS",
    )
    _verify_selected_readback(
        compdata_decoded,
        parsed_compdata,
        table,
        overrides,
        compdata_decisions,
        label="P10 COMPDATA",
    )
    _verify_selected_readback(
        compdata_decoded,
        parsed_compdata,
        table,
        overrides,
        stage_title_decisions,
        label="P10 first-five stage titles",
    )

    ratchet = config.get("ratchet")
    if not isinstance(ratchet, dict):
        raise UiDatabaseCandidateError(
            "UI database candidate has no ratchet"
        )
    slps_selection = slps_slice_report["selection"]
    compdata_selection = compdata_slice_report["selection"]
    actual_ratchet = {
        "family_count": len(selection_manifest["selection"]["families"]),
        "selected_entry_count": len(decisions),
        "selected_slps_entry_count": len(slps_decisions),
        "selected_compdata_entry_count": len(compdata_decisions),
        "font_allocation_count": font_manifest["additional_allocations"][
            "count"
        ],
        "font_reraster_count": font_manifest[
            "additional_reraster_existing_han"
        ]["count"],
        "font_semantic_replacement_count": font_manifest[
            "semantic_code_replacements"
        ]["count"],
        "font_inherited_optical_reraster_count": font_manifest[
            "inherited_optical_reraster_overrides"
        ]["count"],
        "font_cjk_optical_policy_assignment_count": font_manifest[
            "cjk_optical_policy"
        ]["assignment_count"],
        "font_cjk_optical_policy_default_point_size": font_manifest[
            "cjk_optical_policy"
        ]["point_size"],
        "font_cjk_optical_reviewed_exception_count": len(
            font_manifest["cjk_optical_policy"][
                "reviewed_exception_characters"
            ]
        ),
        "first_five_stage_title_count": len(stage_title_decisions),
        "opening_profile_entry_count": len(opening_profile_decisions),
        "unit_name_entry_count": len(unit_name_decisions),
        "unit_name_write_entry_count": unit_name_report[
            "write_entry_count"
        ],
        "unit_name_no_op_entry_count": unit_name_report[
            "no_op_entry_count"
        ],
        "slps_no_op_entry_count": slps_selection["no_op_entry_count"],
        "slps_selected_write_entry_count": slps_selection[
            "selected_write_entry_count"
        ],
        "slps_selected_write_target_count": slps_selection[
            "selected_write_target_count"
        ],
        "compdata_no_op_entry_count": compdata_selection[
            "no_op_entry_count"
        ],
        "compdata_selected_write_entry_count": compdata_selection[
            "selected_write_entry_count"
        ],
        "compdata_selected_write_target_count": compdata_selection[
            "selected_write_target_count"
        ],
        "fixed_covered_entry_count": (
            slps_selection["fixed_covered_entry_count"]
            + compdata_selection["fixed_covered_entry_count"]
        ),
        "excluded_entry_count": (
            slps_selection["excluded_entry_count"]
            + compdata_selection["excluded_entry_count"]
        ),
    }
    ratchet_checks = {
        key: value == ratchet.get(key)
        for key, value in actual_ratchet.items()
    }
    if not all(ratchet_checks.values()):
        raise UiDatabaseCandidateError(
            "P10 database candidate ratchet failed: "
            f"actual={actual_ratchet} checks={ratchet_checks}"
        )

    output_payloads = {
        "slps": output_slps,
        "vt1": output_vt1,
        "compdata": output_compdata,
        "mtv_pros": base_payloads["mtv_pros"],
    }
    member_paths = {
        "slps": "SLPS_258.87",
        "vt1": "DATA/VT1.BIN",
        "compdata": "DATA/COMPDATA.BN",
        "mtv_pros": "DATA/MTV_PROS.BIN",
    }
    outputs = config.get("outputs")
    if not isinstance(outputs, dict):
        raise UiDatabaseCandidateError(
            "UI database candidate outputs are missing"
        )
    component_root = _project_path(root, outputs.get("component_root"))
    output_report = {
        output_id: {
            "path": str(
                (component_root / member_paths[output_id]).relative_to(root)
            ),
            **_payload_lock(payload),
        }
        for output_id, payload in output_payloads.items()
    }

    composition = config.get("composition")
    if not isinstance(composition, dict):
        raise UiDatabaseCandidateError(
            "UI database candidate composition is missing"
        )
    if composition != {
        "require_selection_manifest_reproducible": True,
        "require_every_selected_entry_fixed_span": True,
        "replace_only_vt1_font_chunk": True,
        "preserve_non_font_vt1_chunks_except_proven_zero_slack_donation": True,
        "rebase_vt1_offset_table_on_p9_slps": True,
        "require_font_offset_bytes_disjoint_from_slps_text_bytes": True,
        "require_compdata_pointer_bytes_unchanged": True,
        "require_first_five_stage_titles_fixed_span": True,
        "require_opening_profile_fixed_span": True,
        "require_all_unit_names_fixed_span": True,
        "copy_mtv_pros_byte_exact": True,
    }:
        raise UiDatabaseCandidateError(
            "UI database composition policy drift"
        )
    acceptance = {
        "selection_manifest_reproduced_exact": True,
        "all_selected_entries_fixed_span_covered": (
            actual_ratchet["fixed_covered_entry_count"] == len(decisions)
            and actual_ratchet["excluded_entry_count"] == 0
        ),
        "slps_pointer_bytes_unchanged": slps_slice_report["write"][
            "pointer_bytes_unchanged"
        ],
        "compdata_pointer_bytes_unchanged": compdata_slice_report["write"][
            "pointer_bytes_unchanged"
        ],
        "slps_non_target_bytes_unchanged": slps_slice_report["write"][
            "non_target_bytes_unchanged"
        ],
        "compdata_non_target_bytes_unchanged": compdata_slice_report["write"][
            "non_target_bytes_unchanged"
        ],
        "first_five_stage_titles_fixed_span": (
            stage_title_slice_report["entry_count"]
            == len(stage_title_decisions)
            and stage_title_slice_report["readback_exact"]
            and stage_title_slice_report["non_target_bytes_unchanged"]
        ),
        "first_five_stage_title_pointer_bytes_unchanged": (
            stage_title_slice_report["pointer_bytes_unchanged"]
        ),
        "opening_profile_fixed_span_readback_exact": opening_profile_report[
            "readback_exact"
        ],
        "all_unit_names_fixed_span_readback_exact": (
            unit_name_report["entry_count"] == len(unit_name_decisions)
            and unit_name_report["readback_exact"]
            and unit_name_report["non_target_bytes_unchanged"]
            and unit_name_report["pointer_bytes_unchanged"]
        ),
        "compdata_codec_round_trip_exact": (
            output_compdata_result.output == compdata_decoded
        ),
        "compdata_flags_preserved": (
            output_compdata_result.flags == decoded_compdata_result.flags
        ),
        "compdata_prefix_ratchet_passed": (
            compressed_common_prefix
            >= codec["minimum_preserved_compressed_prefix"]
        ),
        "font_and_slps_text_offsets_disjoint": not font_text_overlap,
        "non_font_vt1_chunks_preserved_from_p9": (
            preserved_non_font_vt1_chunk_count
            == len(base_vt1_offsets) - 2
        ),
        "vt1_archive_size_preserved_from_p9": (
            len(output_vt1) == len(base_payloads["vt1"])
        ),
        "decoded_font_matches_p10_extension": (
            sha256_bytes(final_font)
            == font_manifest["font_component"]["decoded_sha256"]
        ),
        "selected_targets_reread_exact": True,
        "mtv_pros_byte_exact_from_p9": (
            output_payloads["mtv_pros"] == base_payloads["mtv_pros"]
        ),
        "runtime_not_claimed": True,
    }
    if not all(acceptance.values()):
        raise UiDatabaseCandidateError(
            f"P10 database candidate acceptance failed: {acceptance}"
        )

    manifest_contract = config.get("manifest_contract")
    if not isinstance(manifest_contract, dict) or not isinstance(
        manifest_contract.get("status"),
        str,
    ):
        raise UiDatabaseCandidateError(
            "UI database manifest contract is invalid"
        )
    runtime = config.get("runtime")
    if (
        not isinstance(runtime, dict)
        or not isinstance(runtime.get("required_routes"), list)
        or not runtime["required_routes"]
        or not isinstance(runtime.get("pending_gates"), list)
        or not runtime["pending_gates"]
    ):
        raise UiDatabaseCandidateError(
            "UI database runtime contract is invalid"
        )

    family_counts = {}
    for family_ids in entry_families.values():
        for family_id in family_ids:
            family_counts[family_id] = family_counts.get(family_id, 0) + 1
    family_report = [
        {
            **family,
            "entry_count": family_counts[family["runtime_scene_id"]],
        }
        for family in selection_manifest["selection"]["families"]
    ]
    report = {
        "schema_version": 1,
        "status": manifest_contract["status"],
        "content_policy": (
            "Hashes, offsets, stable IDs and counts only; no game bytes, "
            "Japanese source text or localized database strings are embedded."
        ),
        "profile_id": profile_id,
        "scope": config["scope"],
        "inputs": {
            "config": _file_lock(root, config_path),
            "database_selection": {
                "config": _file_lock(root, selection_config_path),
                "manifest": _file_lock(root, selection_manifest_path),
                "selection_id": selection_manifest["selection_id"],
                "status": selection_manifest["status"],
                "reproduced_exact": True,
            },
            "font_extension": {
                "manifest": _file_lock(root, font_manifest_path),
                "font_profile_id": font_manifest["font_profile_id"],
                "status": font_manifest["status"],
                "slps": _file_lock(root, font_slps_path),
                "vt1": _file_lock(root, font_vt1_path),
            },
            "base_ui_core": {
                "manifest": _file_lock(root, base_manifest_path),
                "component_id": base_reference["component_id"],
                "profile_id": base_manifest["profile_id"],
                "status": base_manifest["status"],
                "runtime_status": base_manifest["runtime"]["status"],
                "outputs": {
                    output_id: _file_lock(root, base_paths[output_id])
                    for output_id in base_paths
                },
            },
            "writer_baseline_config": _file_lock(
                root,
                writer_config_path,
            ),
            "menu_descriptor": _file_lock(root, descriptor_path),
            "text_table": _file_lock(root, table_path),
            "first_five_polish": {
                "stage_titles": _file_lock(root, stage_title_path),
                "opening_profile": _file_lock(root, opening_profile_path),
            },
            "unit_names": {
                "corpus": _file_lock(root, unit_corpus_path),
                "structure_config": _file_lock(root, unit_structure_path),
                "selection": unit_name_selection,
            },
            "codebook": codebook_report,
        },
        "selection": {
            "entry_count": len(decisions),
            "slps_entry_count": len(slps_decisions),
            "compdata_entry_count": len(compdata_decisions),
            "entry_ids_sha256": selection_metadata[
                "selected_entry_ids_sha256"
            ],
            "decisions_sha256": selection_metadata[
                "selected_decisions_sha256"
            ],
            "families": family_report,
            "deferred_entry_count": selection_metadata[
                "deferred_entry_count"
            ],
            "protected_exclusions": selection_metadata[
                "protected_exclusions"
            ],
        },
        "fixed_span": {
            "slps": slps_slice_report,
            "compdata": compdata_slice_report,
            "first_five_stage_titles": stage_title_slice_report,
            "opening_profile": opening_profile_report,
            "unit_names": unit_name_report,
        },
        "composition": {
            "slps_text_changed_byte_count": len(
                slps_text_changed_offsets
            ),
            "slps_text_difference_range_count": _difference_range_count(
                slps_text_changed_offsets
            ),
            "slps_text_changed_offsets_sha256": _stable_hash(
                slps_text_changed_offsets
            ),
            "font_offset_changed_byte_count": len(
                font_offset_changed_offsets
            ),
            "font_offset_changed_offsets_sha256": _stable_hash(
                font_offset_changed_offsets
            ),
            "font_and_slps_text_overlap_byte_count": 0,
            "final_slps_changed_byte_count": len(
                final_slps_changed_offsets
            ),
            "final_slps_difference_range_count": _difference_range_count(
                final_slps_changed_offsets
            ),
            "final_slps_changed_offsets_sha256": _stable_hash(
                final_slps_changed_offsets
            ),
            "font_chunk_index": chunk_index,
            "font_padding_size": font_padding_size,
            "font_borrowed_preceding_zero_slack": (
                font_borrowed_zero_slack
            ),
            "vt1_archive_size_preserved": (
                len(output_vt1) == len(base_payloads["vt1"])
            ),
            "vt1_chunk_count": len(base_vt1_offsets) - 1,
            "preserved_non_font_vt1_chunk_count": (
                preserved_non_font_vt1_chunk_count
            ),
            "zero_slack_donor_chunk_index": zero_slack_donor_chunk_index,
            "decoded_font_sha256": sha256_bytes(final_font),
            "compdata_decoded_changed_byte_count": len(
                compdata_changed_offsets
            ),
            "compdata_database_changed_byte_count": len(
                database_compdata_changed_offsets
            ),
            "compdata_stage_title_changed_byte_count": len(
                stage_title_changed_offsets
            ),
            "compdata_opening_profile_changed_byte_count": len(
                opening_profile_changed_offsets
            ),
            "compdata_unit_name_changed_byte_count": len(
                unit_name_changed_offsets
            ),
            "compdata_decoded_difference_range_count": (
                _difference_range_count(compdata_changed_offsets)
            ),
            "compdata_decoded_changed_offsets_sha256": _stable_hash(
                compdata_changed_offsets
            ),
            "compdata_source_compressed_size": len(
                base_payloads["compdata"]
            ),
            "compdata_output_compressed_size": len(output_compdata),
            "compdata_compressed_common_prefix": compressed_common_prefix,
            "compdata_flags": output_compdata_result.flags,
            "compdata_codec": {
                "strategy": codec["strategy"],
                "min_match_length": codec["min_match_length"],
                "max_match_chain": codec["max_match_chain"],
                "lazy_matching": codec["lazy_matching"],
                "output_size": len(output_compdata),
                "maximum_output_size": max_output_size,
                "sector_size": sector_size,
                "maximum_sectors": max_sectors,
                "sector_count": (
                    len(output_compdata) + sector_size - 1
                )
                // sector_size,
                "within_sector_budget": (
                    len(output_compdata) <= max_output_size
                ),
                "budget_headroom": max_output_size - len(output_compdata),
                "decoded_round_trip_exact": True,
                "flags_preserved": True,
                "fully_consumed": True,
            },
        },
        "outputs": output_report,
        "ratchet": {
            "expected": ratchet,
            "actual": actual_ratchet,
            "checks": ratchet_checks,
            "passed": True,
        },
        "acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "required_routes": runtime["required_routes"],
            "pending_gates": runtime["pending_gates"],
        },
    }
    return {
        member_paths[output_id]: payload
        for output_id, payload in output_payloads.items()
    }, report


__all__ = [
    "UiDatabaseCandidateError",
    "build_ui_database_candidate",
]
