"""Build one layered fixed-span embedded UI slice on a validated UI core."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .canary import CanaryError, rebuild_archive_with_replacement
from .codec import decode
from .font import decode_vt1_font_segment
from .iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from .text import augment_text_table, decode_text
from .ui_embedded_scenes import (
    UiEmbeddedSceneError,
    load_embedded_scene_config,
    load_embedded_writeback_baseline,
)
from .ui_inventory import UiInventoryError, expand_selector
from .ui_menu import UiMenuError, build_fixed_slps_slice
from .writers import build_executable_offset_patch_plan


class UiEmbeddedCandidateError(ValueError):
    """The promoted embedded UI slice or its base composition has drifted."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiEmbeddedCandidateError(
            f"cannot load JSON object {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise UiEmbeddedCandidateError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiEmbeddedCandidateError("project path must be non-empty text")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiEmbeddedCandidateError(f"path escapes project root: {raw}") from error
    return path


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
        "sha256": _sha256_bytes(payload),
    }


def _verified_json_reference(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, dict]:
    path = _project_path(project_root, reference.get("path"))
    if _sha256_path(path) != reference.get("sha256"):
        raise UiEmbeddedCandidateError(f"{label} SHA-256 drift")
    value = _json_object(path)
    required_status = reference.get("required_status")
    if required_status is not None and value.get("status") != required_status:
        raise UiEmbeddedCandidateError(f"{label} status drift")
    required_profile_id = reference.get("required_profile_id")
    if (
        required_profile_id is not None
        and value.get("profile_id") != required_profile_id
    ):
        raise UiEmbeddedCandidateError(f"{label} profile drift")
    required_runtime_status = reference.get("required_runtime_status")
    if required_runtime_status is not None and value.get("runtime", {}).get(
        "status"
    ) != required_runtime_status:
        raise UiEmbeddedCandidateError(f"{label} runtime status drift")
    return path, value


def _verified_payload(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, bytes]:
    path = _project_path(project_root, reference.get("path"))
    payload = path.read_bytes()
    expected = {
        "size": reference.get("size"),
        "sha256": reference.get("sha256"),
    }
    if _payload_lock(payload) != expected:
        raise UiEmbeddedCandidateError(f"{label} size or SHA-256 drift")
    return path, payload


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    if len(before) != len(after):
        raise UiEmbeddedCandidateError("SLPS composition changed member size")
    return [
        offset
        for offset, (source_byte, output_byte) in enumerate(zip(before, after))
        if source_byte != output_byte
    ]


def _stable_hash(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def build_ui_embedded_candidate(
    project_root: Path,
    config_path: Path,
) -> tuple[dict[str, bytes], dict]:
    """Return one four-member UI core with a promoted embedded fixed-span slice."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiEmbeddedCandidateError("unsupported embedded UI candidate schema")
    profile_id = config.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise UiEmbeddedCandidateError("embedded UI candidate needs a profile_id")

    scene_reference = config.get("scene_map")
    if not isinstance(scene_reference, dict):
        raise UiEmbeddedCandidateError("embedded UI candidate lacks scene_map")
    scene_config_path, _ = _verified_json_reference(
        root,
        scene_reference["config"],
        label="embedded UI scene config",
    )
    scene_manifest_path, scene_manifest = _verified_json_reference(
        root,
        scene_reference["manifest"],
        label="embedded UI scene manifest",
    )
    try:
        scene_config = load_embedded_scene_config(scene_config_path)
    except UiEmbeddedSceneError as error:
        raise UiEmbeddedCandidateError(str(error)) from error
    selected_scene_ids = scene_reference.get("selected_scene_ids")
    if (
        not isinstance(selected_scene_ids, list)
        or not selected_scene_ids
        or any(not isinstance(scene_id, str) for scene_id in selected_scene_ids)
        or len(selected_scene_ids) != len(set(selected_scene_ids))
    ):
        raise UiEmbeddedCandidateError("selected embedded scene IDs are invalid")
    groups_by_id = {
        group["scene_id"]: group for group in scene_config["groups"]
    }
    manifest_groups_by_id = {
        group["scene_id"]: group for group in scene_manifest["groups"]
    }
    missing_groups = sorted(set(selected_scene_ids) - set(groups_by_id))
    if missing_groups:
        raise UiEmbeddedCandidateError(
            f"selected embedded scenes are absent: {missing_groups!r}"
        )
    raw_entry_subsets = scene_reference.get(
        "selected_entry_subsets",
        {},
    )
    if not isinstance(raw_entry_subsets, dict):
        raise UiEmbeddedCandidateError(
            "selected embedded entry subsets must be an object"
        )
    unknown_subset_scenes = sorted(
        set(raw_entry_subsets) - set(selected_scene_ids)
    )
    if unknown_subset_scenes:
        raise UiEmbeddedCandidateError(
            "entry subsets reference unselected scenes: "
            f"{unknown_subset_scenes!r}"
        )
    runtime_subset_scene_ids = []
    for scene_id, subset in raw_entry_subsets.items():
        if not isinstance(subset, dict):
            raise UiEmbeddedCandidateError(
                f"entry subset is invalid: {scene_id}"
            )
        runtime_scene_id = subset.get("runtime_scene_id")
        entry_ids = subset.get("entry_ids")
        if (
            not isinstance(runtime_scene_id, str)
            or not runtime_scene_id
            or not isinstance(entry_ids, list)
            or not entry_ids
            or any(
                not isinstance(entry_id, str) or not entry_id
                for entry_id in entry_ids
            )
            or len(entry_ids) != len(set(entry_ids))
        ):
            raise UiEmbeddedCandidateError(
                f"entry subset contract is invalid: {scene_id}"
            )
        runtime_subset_scene_ids.append(runtime_scene_id)
    if len(runtime_subset_scene_ids) != len(set(runtime_subset_scene_ids)):
        raise UiEmbeddedCandidateError(
            "entry subset runtime scene IDs are duplicated"
        )
    decisions: dict[str, dict] = {}
    selected_group_reports = []
    required_scene_readiness = scene_reference.get(
        "required_writeback_status",
        "fixed_span_ready",
    )
    if (
        not isinstance(required_scene_readiness, str)
        or not required_scene_readiness
    ):
        raise UiEmbeddedCandidateError(
            "selected embedded scene readiness status is invalid"
        )
    for scene_id in selected_scene_ids:
        group = groups_by_id[scene_id]
        manifest_group = manifest_groups_by_id.get(scene_id)
        if not isinstance(manifest_group, dict):
            raise UiEmbeddedCandidateError(
                f"scene manifest lacks selected group: {scene_id}"
            )
        readiness = manifest_group.get("writeback_readiness")
        if (
            not isinstance(readiness, dict)
            or readiness.get("status") != required_scene_readiness
            or (
                required_scene_readiness == "fixed_span_ready"
                and readiness.get("excluded_entry_count") != 0
            )
        ):
            raise UiEmbeddedCandidateError(
                "selected group does not match required scene-map readiness: "
                f"{scene_id}"
            )
        try:
            group_entries = expand_selector(root, group["selector"])
        except UiInventoryError as error:
            raise UiEmbeddedCandidateError(str(error)) from error
        subset = raw_entry_subsets.get(scene_id)
        subset_report = {}
        if subset is None:
            entries = group_entries
        else:
            if group.get("classification") != "mixed_user_and_diagnostic":
                raise UiEmbeddedCandidateError(
                    "entry subsets are only allowed for mixed UI groups: "
                    f"{scene_id}"
                )
            requested_entry_ids = subset["entry_ids"]
            group_entries_by_id = {
                entry["id"]: entry for entry in group_entries
            }
            missing_entry_ids = sorted(
                set(requested_entry_ids) - set(group_entries_by_id)
            )
            if missing_entry_ids:
                raise UiEmbeddedCandidateError(
                    f"entry subset {scene_id} has foreign IDs: "
                    f"{missing_entry_ids!r}"
                )
            source_order = [
                entry["id"]
                for entry in group_entries
                if entry["id"] in set(requested_entry_ids)
            ]
            if requested_entry_ids != source_order:
                raise UiEmbeddedCandidateError(
                    f"entry subset {scene_id} is not in source order"
                )
            if len(requested_entry_ids) >= len(group_entries):
                raise UiEmbeddedCandidateError(
                    f"entry subset {scene_id} does not leave a remainder"
                )
            entries = tuple(
                group_entries_by_id[entry_id]
                for entry_id in requested_entry_ids
            )
            subset_report = {
                "selection_mode": "entry_subset",
                "runtime_scene_id": subset["runtime_scene_id"],
                "source_group_entry_count": len(group_entries),
                "source_group_entry_ids_sha256": manifest_group[
                    "entry_ids_sha256"
                ],
            }
        for entry in entries:
            entry_id = entry["id"]
            if entry_id in decisions:
                raise UiEmbeddedCandidateError(
                    f"selected groups overlap at {entry_id}"
                )
            decisions[entry_id] = entry
        selected_group_reports.append(
            {
                "scene_id": scene_id,
                "entry_count": len(entries),
                "fixture_id": group["fixture_id"],
                "entry_ids_sha256": (
                    _stable_hash([entry["id"] for entry in entries])
                    if subset is not None
                    else manifest_group["entry_ids_sha256"]
                ),
                "readiness_status": readiness["status"],
                "runtime_status": manifest_group["runtime_status"],
                **subset_report,
            }
        )

    try:
        writeback_reference = config.get(
            "writeback_readiness",
            scene_config["writeback_readiness"],
        )
        if not isinstance(writeback_reference, dict):
            raise UiEmbeddedCandidateError(
                "embedded UI writeback readiness is invalid"
            )
        (
            readiness_slps,
            readiness_vt1,
            readiness_parsed,
            readiness_table,
            readiness_overrides,
            readiness_sources,
        ) = load_embedded_writeback_baseline(
            root,
            writeback_reference,
        )
        slice_output, slice_report = build_fixed_slps_slice(
            readiness_slps,
            readiness_vt1,
            readiness_parsed,
            readiness_table,
            decisions=decisions,
            overrides=readiness_overrides,
            source_name="P2 font readiness SLPS_258.87",
        )
    except (UiEmbeddedSceneError, UiMenuError) as error:
        raise UiEmbeddedCandidateError(str(error)) from error

    base_reference = config.get("base_ui_core")
    if not isinstance(base_reference, dict):
        raise UiEmbeddedCandidateError("embedded UI candidate lacks base_ui_core")
    base_component_id = base_reference.get("component_id", "ui-p2-core")
    if not isinstance(base_component_id, str) or not base_component_id:
        raise UiEmbeddedCandidateError("embedded UI base component ID is invalid")
    base_manifest_path, base_manifest = _verified_json_reference(
        root,
        base_reference["manifest"],
        label="base UI core manifest",
    )
    output_references = base_reference.get("outputs")
    if not isinstance(output_references, dict):
        raise UiEmbeddedCandidateError("base UI core outputs are missing")
    base_paths: dict[str, Path] = {}
    base_payloads: dict[str, bytes] = {}
    for output_id in ("slps", "vt1", "compdata", "mtv_pros"):
        reference = output_references.get(output_id)
        if not isinstance(reference, dict):
            raise UiEmbeddedCandidateError(
                f"base UI core output is missing: {output_id}"
            )
        path, payload = _verified_payload(
            root,
            reference,
            label=f"base UI core {output_id}",
        )
        manifest_output = base_manifest.get("outputs", {}).get(output_id)
        if not isinstance(manifest_output, dict) or _payload_lock(payload) != {
            "size": manifest_output.get("size"),
            "sha256": manifest_output.get("sha256"),
        }:
            raise UiEmbeddedCandidateError(
                f"base UI core manifest output drift: {output_id}"
            )
        base_paths[output_id] = path
        base_payloads[output_id] = payload

    base_slps = base_payloads["slps"]
    required_localized_entries = base_reference.get(
        "required_localized_entries",
        {},
    )
    if (
        not isinstance(required_localized_entries, dict)
        or any(
            not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(translation, str)
            or not translation
            for entry_id, translation in required_localized_entries.items()
        )
    ):
        raise UiEmbeddedCandidateError(
            "base UI required localized entries are invalid"
        )
    readiness_entries_by_id = {
        entry.entry_id: entry for entry in readiness_parsed.entries
    }
    readiness_output_table = augment_text_table(
        readiness_table,
        readiness_overrides,
    )
    required_localized_target_count = 0
    for entry_id, translation in required_localized_entries.items():
        parsed_entry = readiness_entries_by_id.get(entry_id)
        if parsed_entry is None or not parsed_entry.target_offsets:
            raise UiEmbeddedCandidateError(
                f"base UI required entry has no parsed target: {entry_id}"
            )
        target_offsets = set(parsed_entry.target_offsets)
        required_localized_target_count += len(target_offsets)
        for target_offset in target_offsets:
            decoded = decode_text(
                base_slps,
                target_offset,
                readiness_output_table,
            )
            if decoded.text != translation:
                raise UiEmbeddedCandidateError(
                    "base UI required localized entry reread differs: "
                    f"{entry_id}"
                )
    required_localized_report = {
        "entry_count": len(required_localized_entries),
        "entry_ids_sha256": _stable_hash(
            sorted(required_localized_entries)
        ),
        "target_count": required_localized_target_count,
        "reread_exact": True,
    }
    slice_changed_offsets = slice_report.pop("changed_offsets")
    font_extension = config.get("font_extension")
    if font_extension is None:
        if len(base_slps) != len(readiness_slps):
            raise UiEmbeddedCandidateError(
                "base core and readiness SLPS sizes differ"
            )
        base_changed_offsets = _changed_offsets(readiness_slps, base_slps)
        overlap = sorted(
            set(slice_changed_offsets) & set(base_changed_offsets)
        )
        if overlap:
            raise UiEmbeddedCandidateError(
                "embedded UI slice overlaps base core changes: "
                f"{overlap[:16]!r}"
            )
        if any(
            base_slps[offset] != readiness_slps[offset]
            for offset in slice_changed_offsets
        ):
            raise UiEmbeddedCandidateError(
                "base core preimage differs at an embedded UI slice offset"
            )
        merged_slps = bytearray(base_slps)
        for offset in slice_changed_offsets:
            merged_slps[offset] = slice_output[offset]
        final_slps = bytes(merged_slps)
        final_vt1 = base_payloads["vt1"]
        final_changed_offsets = _changed_offsets(base_slps, final_slps)
        if final_changed_offsets != slice_changed_offsets:
            raise UiEmbeddedCandidateError(
                "embedded UI core delta differs from the fixed-span slice"
            )
        font_composition = None
    else:
        if (
            not isinstance(font_extension, dict)
            or font_extension.get("mode")
            != "replace-vt1-and-compose-slps-offset-delta"
        ):
            raise UiEmbeddedCandidateError(
                "embedded UI font-extension mode is invalid"
            )
        try:
            (
                font_base_slps,
                font_base_vt1,
                _font_base_parsed,
                _font_base_table,
                _font_base_overrides,
                font_base_sources,
            ) = load_embedded_writeback_baseline(
                root,
                scene_config["writeback_readiness"],
            )
        except UiEmbeddedSceneError as error:
            raise UiEmbeddedCandidateError(str(error)) from error
        if not (
            len(font_base_slps)
            == len(readiness_slps)
            == len(base_slps)
        ):
            raise UiEmbeddedCandidateError(
                "font baseline, extension and base core SLPS sizes differ"
            )
        font_base_hash = _sha256_bytes(
            decode_vt1_font_segment(
                font_base_slps,
                font_base_vt1,
            ).decoded
        )
        base_core_font_hash = _sha256_bytes(
            decode_vt1_font_segment(
                base_slps,
                base_payloads["vt1"],
            ).decoded
        )
        if base_core_font_hash != font_base_hash:
            raise UiEmbeddedCandidateError(
                "base core decoded font differs from the scene-map baseline"
            )
        chunk_index = font_extension.get("chunk_index")
        alignment = font_extension.get("archive_alignment")
        if (
            chunk_index != 2
            or alignment != 16
        ):
            raise UiEmbeddedCandidateError(
                "embedded UI font-extension archive contract is invalid"
            )
        spec = CORE_ARCHIVE_SPECS["VT1.BIN"]
        base_vt1_offsets = read_executable_archive_offsets(
            base_slps,
            spec,
            len(base_payloads["vt1"]),
        )
        readiness_vt1_offsets = read_executable_archive_offsets(
            readiness_slps,
            spec,
            len(readiness_vt1),
        )
        stored_font = readiness_vt1[
            readiness_vt1_offsets[chunk_index]:
            readiness_vt1_offsets[chunk_index + 1]
        ]
        decoded_font = decode(stored_font)
        if any(stored_font[decoded_font.consumed:]):
            raise UiEmbeddedCandidateError(
                "extended VT1 font stream has nonzero padding"
            )
        try:
            (
                final_vt1,
                final_vt1_offsets,
                font_padding_size,
            ) = rebuild_archive_with_replacement(
                base_payloads["vt1"],
                base_vt1_offsets,
                chunk_index=chunk_index,
                encoded_replacement=stored_font[:decoded_font.consumed],
                alignment=alignment,
            )
        except CanaryError as error:
            raise UiEmbeddedCandidateError(str(error)) from error
        font_offset_plan = build_executable_offset_patch_plan(
            base_slps,
            spec,
            final_vt1_offsets,
        )
        font_rebased_slps = font_offset_plan.apply(base_slps)
        if (
            read_executable_archive_offsets(
                font_rebased_slps,
                spec,
                len(final_vt1),
            )
            != final_vt1_offsets
        ):
            raise UiEmbeddedCandidateError(
                "rebased VT1 offsets fail SLPS reread"
            )
        unchanged_vt1_chunk_count = 0
        for index, (
            base_start,
            base_end,
            final_start,
            final_end,
        ) in enumerate(
            zip(
                base_vt1_offsets,
                base_vt1_offsets[1:],
                final_vt1_offsets,
                final_vt1_offsets[1:],
            )
        ):
            if index == chunk_index:
                continue
            if (
                base_payloads["vt1"][base_start:base_end]
                != final_vt1[final_start:final_end]
            ):
                raise UiEmbeddedCandidateError(
                    f"non-font VT1 chunk {index} changed"
                )
            unchanged_vt1_chunk_count += 1
        font_changed_offsets = _changed_offsets(
            base_slps,
            font_rebased_slps,
        )
        base_changed_offsets = _changed_offsets(font_base_slps, base_slps)
        font_slice_overlap = sorted(
            set(font_changed_offsets) & set(slice_changed_offsets)
        )
        candidate_changed_offsets = sorted(
            {*font_changed_offsets, *slice_changed_offsets}
        )
        overlap = sorted(
            set(slice_changed_offsets) & set(base_changed_offsets)
        )
        if font_slice_overlap:
            raise UiEmbeddedCandidateError(
                "font SLPS offsets overlap selected UI text: "
                f"{font_slice_overlap[:16]!r}"
            )
        if overlap:
            raise UiEmbeddedCandidateError(
                "selected UI text overlaps base core changes: "
                f"{overlap[:16]!r}"
            )
        if any(
            base_slps[offset] != readiness_slps[offset]
            for offset in slice_changed_offsets
        ):
            raise UiEmbeddedCandidateError(
                "base core preimage differs at a selected UI text offset"
            )
        merged_slps = bytearray(font_rebased_slps)
        for offset in slice_changed_offsets:
            merged_slps[offset] = slice_output[offset]
        final_slps = bytes(merged_slps)
        final_changed_offsets = _changed_offsets(base_slps, final_slps)
        if final_changed_offsets != candidate_changed_offsets:
            raise UiEmbeddedCandidateError(
                "font/text core delta differs from the owned candidate bytes"
            )
        font_composition = {
            "mode": font_extension["mode"],
            "base_readiness": font_base_sources,
            "font_changed_byte_count": len(font_changed_offsets),
            "font_changed_offsets_sha256": _stable_hash(
                font_changed_offsets
            ),
            "font_and_slice_overlap_byte_count": 0,
            "candidate_changed_byte_count": len(
                candidate_changed_offsets
            ),
            "candidate_changed_offsets_sha256": _stable_hash(
                candidate_changed_offsets
            ),
            "font_chunk_index": chunk_index,
            "font_padding_size": font_padding_size,
            "vt1_chunk_count": len(base_vt1_offsets) - 1,
            "unchanged_vt1_chunk_count": unchanged_vt1_chunk_count,
            "base_core_decoded_font_matches_scene_baseline": True,
        }

    parsed_entries = {
        entry.entry_id: entry for entry in readiness_parsed.entries
    }
    output_table = augment_text_table(readiness_table, readiness_overrides)
    for entry_id, decision in decisions.items():
        parsed_entry = parsed_entries.get(entry_id)
        if parsed_entry is None or not parsed_entry.target_offsets:
            raise UiEmbeddedCandidateError(
                f"selected entry has no parsed target: {entry_id}"
            )
        for target_offset in set(parsed_entry.target_offsets):
            decoded = decode_text(final_slps, target_offset, output_table)
            if decoded.text != decision["translation"]:
                raise UiEmbeddedCandidateError(
                    f"final layered SLPS reread differs for {entry_id}"
                )

    base_font_hash = _sha256_bytes(
        decode_vt1_font_segment(base_slps, base_payloads["vt1"]).decoded
    )
    readiness_font_hash = _sha256_bytes(
        decode_vt1_font_segment(readiness_slps, readiness_vt1).decoded
    )
    final_font_hash = _sha256_bytes(
        decode_vt1_font_segment(final_slps, final_vt1).decoded
    )
    if font_extension is None:
        if final_font_hash != base_font_hash:
            raise UiEmbeddedCandidateError(
                "embedded UI slice changed the font"
            )
    elif final_font_hash != readiness_font_hash:
        raise UiEmbeddedCandidateError(
            "final embedded UI font differs from the extension component"
        )

    outputs_config = config.get("outputs")
    if not isinstance(outputs_config, dict):
        raise UiEmbeddedCandidateError("embedded UI candidate outputs are missing")
    component_root = _project_path(
        root,
        outputs_config.get("component_root"),
    )
    output_payloads = {
        "slps": final_slps,
        "vt1": final_vt1,
        "compdata": base_payloads["compdata"],
        "mtv_pros": base_payloads["mtv_pros"],
    }
    member_paths = {
        "slps": "SLPS_258.87",
        "vt1": "DATA/VT1.BIN",
        "compdata": "DATA/COMPDATA.BN",
        "mtv_pros": "DATA/MTV_PROS.BIN",
    }
    output_report = {
        output_id: {
            "path": str((component_root / member).relative_to(root)),
            **_payload_lock(output_payloads[output_id]),
        }
        for output_id, member in member_paths.items()
    }

    selection = slice_report["selection"]
    ratchet = config.get("ratchet")
    if not isinstance(ratchet, dict):
        raise UiEmbeddedCandidateError("embedded UI candidate lacks ratchet")
    actual_ratchet = {
        "selected_scene_count": len(selected_scene_ids),
        "selected_entry_count": len(decisions),
        "no_op_entry_count": selection["no_op_entry_count"],
        "selected_write_entry_count": selection["selected_write_entry_count"],
        "selected_write_target_count": selection["selected_write_target_count"],
        "fixed_covered_entry_count": selection["fixed_covered_entry_count"],
        "excluded_entry_count": selection["excluded_entry_count"],
        "slice_changed_byte_count": len(slice_changed_offsets),
        "slice_difference_range_count": slice_report["component"][
            "difference_range_count"
        ],
    }
    checks = {
        key: actual == ratchet.get(key)
        for key, actual in actual_ratchet.items()
    }
    if not all(checks.values()):
        raise UiEmbeddedCandidateError(
            "embedded UI candidate ratchet failed: "
            f"actual={actual_ratchet} checks={checks}"
        )

    if base_component_id == "ui-p2-core":
        unchanged_member_acceptance = {
            "compdata_byte_exact_from_p2": output_payloads["compdata"]
            == base_payloads["compdata"],
            "mtv_pros_byte_exact_from_p2": output_payloads["mtv_pros"]
            == base_payloads["mtv_pros"],
        }
        if font_extension is None:
            unchanged_member_acceptance["vt1_byte_exact_from_p2"] = (
                output_payloads["vt1"] == base_payloads["vt1"]
            )
    else:
        unchanged_member_acceptance = {
            "compdata_byte_exact_from_base": output_payloads["compdata"]
            == base_payloads["compdata"],
            "mtv_pros_byte_exact_from_base": output_payloads["mtv_pros"]
            == base_payloads["mtv_pros"],
        }
        if font_extension is None:
            unchanged_member_acceptance["vt1_byte_exact_from_base"] = (
                output_payloads["vt1"] == base_payloads["vt1"]
            )
    acceptance = {
        (
            "selected_groups_fixed_span_ready"
            if required_scene_readiness == "fixed_span_ready"
            else "selected_groups_match_required_scene_readiness"
        ): all(
            group["readiness_status"] == required_scene_readiness
            for group in selected_group_reports
        ),
        "all_selected_entries_covered": (
            selection["fixed_covered_entry_count"] == len(decisions)
            and selection["excluded_entry_count"] == 0
        ),
        "slice_and_base_changes_disjoint": not overlap,
        "base_preimage_exact_at_slice_offsets": True,
        "pointer_bytes_unchanged": slice_report["write"][
            "pointer_bytes_unchanged"
        ],
        "non_target_bytes_unchanged": slice_report["write"][
            "non_target_bytes_unchanged"
        ],
        "selected_targets_reread_exact": True,
        **(
            {
                "base_required_localized_entries_reread_exact": (
                    required_localized_report["reread_exact"]
                )
            }
            if required_localized_entries
            else {}
        ),
        **unchanged_member_acceptance,
    }
    if font_extension is None:
        acceptance["decoded_font_unchanged"] = (
            final_font_hash == base_font_hash
        )
    else:
        acceptance["font_and_slice_offsets_disjoint"] = (
            font_composition["font_and_slice_overlap_byte_count"] == 0
        )
        acceptance["base_core_decoded_font_matches_scene_baseline"] = (
            base_core_font_hash == font_base_hash
        )
        acceptance["non_font_vt1_chunks_byte_exact_from_base"] = (
            font_composition["unchanged_vt1_chunk_count"]
            == font_composition["vt1_chunk_count"] - 1
        )
        acceptance["decoded_font_matches_extension"] = (
            final_font_hash == readiness_font_hash
        )
    if not all(acceptance.values()):
        raise UiEmbeddedCandidateError(
            f"embedded UI candidate acceptance failed: {acceptance}"
        )

    manifest_contract = config.get("manifest_contract", {})
    if not isinstance(manifest_contract, dict):
        raise UiEmbeddedCandidateError("embedded UI manifest contract is invalid")
    report_status = manifest_contract.get(
        "status",
        (
            "integrated_ui_p3_fresh_boot_component_"
            "validated_iso_runtime_pending"
        ),
    )
    if not isinstance(report_status, str) or not report_status:
        raise UiEmbeddedCandidateError("embedded UI manifest status is invalid")
    runtime_contract = config.get("runtime", {})
    if not isinstance(runtime_contract, dict):
        raise UiEmbeddedCandidateError("embedded UI runtime contract is invalid")
    required_routes = runtime_contract.get(
        "required_routes",
        [
            "fresh_boot_tutorial_unit_stat_and_terrain_legend",
            "fresh_boot_default_protagonist_labels_both_routes",
        ],
    )
    pending_gates = runtime_contract.get(
        "pending_gates",
        [
            "exact_iso_static_binding",
            "fresh_process_boot",
            "both_protagonist_routes",
            "tutorial_stat_and_terrain_pages",
            "no_clipping_overlap_or_missing_glyphs",
            "zero_tlb_miss",
        ],
    )
    if (
        not isinstance(required_routes, list)
        or not required_routes
        or any(not isinstance(value, str) or not value for value in required_routes)
        or not isinstance(pending_gates, list)
        or not pending_gates
        or any(not isinstance(value, str) or not value for value in pending_gates)
    ):
        raise UiEmbeddedCandidateError("embedded UI runtime gates are invalid")
    report = {
        "schema_version": 1,
        "status": report_status,
        "content_policy": (
            "Hashes, offsets, stable IDs and counts only; no game bytes, "
            "Japanese source text or localized UI strings are embedded."
        ),
        "profile_id": profile_id,
        "scope": config["scope"],
        "inputs": {
            "config": _file_lock(root, config_path),
            "scene_map": {
                "config": _file_lock(root, scene_config_path),
                "manifest": _file_lock(root, scene_manifest_path),
                "map_id": scene_manifest["map_id"],
            },
            "readiness_baseline": readiness_sources,
            "base_ui_core": {
                "manifest": _file_lock(root, base_manifest_path),
                "profile_id": base_manifest["profile_id"],
                "status": base_manifest["status"],
                "runtime_status": base_manifest["runtime"]["status"],
                "outputs": {
                    output_id: _file_lock(root, base_paths[output_id])
                    for output_id in member_paths
                },
                **(
                    {
                        "required_localized_entries": (
                            required_localized_report
                        )
                    }
                    if required_localized_entries
                    else {}
                ),
            },
        },
        "selection": {
            "scene_count": len(selected_scene_ids),
            **(
                {
                    "entry_subset_scene_count": len(
                        raw_entry_subsets
                    ),
                    "runtime_scene_ids": runtime_subset_scene_ids,
                }
                if raw_entry_subsets
                else {}
            ),
            "scenes": selected_group_reports,
            "entry_count": len(decisions),
            "entry_ids_sha256": _stable_hash(sorted(decisions)),
            "decision_sha256": _stable_hash(
                [
                    {
                        "id": entry_id,
                        "source_text_sha256": decisions[entry_id][
                            "source_text_sha256"
                        ],
                        "translation": decisions[entry_id]["translation"],
                    }
                    for entry_id in sorted(decisions)
                ]
            ),
            **selection,
        },
        "slice": {
            **slice_report,
            "changed_offsets_sha256": _stable_hash(slice_changed_offsets),
        },
        "composition": {
            "base_changed_byte_count": len(base_changed_offsets),
            "base_changed_offsets_sha256": _stable_hash(base_changed_offsets),
            "slice_changed_byte_count": len(slice_changed_offsets),
            "slice_changed_offsets_sha256": _stable_hash(slice_changed_offsets),
            "overlap_byte_count": 0,
            "base_preimage_exact_at_slice_offsets": True,
            "final_changed_from_base_byte_count": len(final_changed_offsets),
            "final_changed_from_base_offsets_sha256": _stable_hash(
                final_changed_offsets
            ),
            "decoded_font_sha256": final_font_hash,
            **(
                {"font_extension": font_composition}
                if font_composition is not None
                else {}
            ),
        },
        "outputs": output_report,
        "ratchet": {
            "expected": ratchet,
            "checks": checks,
            "passed": True,
        },
        "acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "required_routes": [
                *required_routes,
            ],
            "pending_gates": [*pending_gates],
        },
    }
    return {
        member_paths[output_id]: payload
        for output_id, payload in output_payloads.items()
    }, report


__all__ = [
    "UiEmbeddedCandidateError",
    "build_ui_embedded_candidate",
]
