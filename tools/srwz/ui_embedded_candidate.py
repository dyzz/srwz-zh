"""Build the first fixed-span embedded UI slice on top of the P2 core."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .font import decode_vt1_font_segment
from .text import augment_text_table, decode_text
from .ui_embedded_scenes import (
    UiEmbeddedSceneError,
    load_embedded_scene_config,
    load_embedded_writeback_baseline,
)
from .ui_inventory import UiInventoryError, expand_selector
from .ui_menu import UiMenuError, build_fixed_slps_slice


class UiEmbeddedCandidateError(ValueError):
    """The promoted embedded UI slice or its P2 composition has drifted."""


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
    """Return the four-member P3 UI core with a promoted fresh-boot slice."""

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
    decisions: dict[str, dict] = {}
    selected_group_reports = []
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
            or readiness.get("status") != "fixed_span_ready"
            or readiness.get("excluded_entry_count") != 0
        ):
            raise UiEmbeddedCandidateError(
                f"selected group is not fixed-span ready: {scene_id}"
            )
        try:
            entries = expand_selector(root, group["selector"])
        except UiInventoryError as error:
            raise UiEmbeddedCandidateError(str(error)) from error
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
                "entry_ids_sha256": manifest_group["entry_ids_sha256"],
                "readiness_status": readiness["status"],
                "runtime_status": manifest_group["runtime_status"],
            }
        )

    try:
        (
            readiness_slps,
            readiness_vt1,
            readiness_parsed,
            readiness_table,
            readiness_overrides,
            readiness_sources,
        ) = load_embedded_writeback_baseline(
            root,
            scene_config["writeback_readiness"],
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
    base_manifest_path, base_manifest = _verified_json_reference(
        root,
        base_reference["manifest"],
        label="P2 UI core manifest",
    )
    output_references = base_reference.get("outputs")
    if not isinstance(output_references, dict):
        raise UiEmbeddedCandidateError("P2 UI core outputs are missing")
    base_paths: dict[str, Path] = {}
    base_payloads: dict[str, bytes] = {}
    for output_id in ("slps", "vt1", "compdata", "mtv_pros"):
        reference = output_references.get(output_id)
        if not isinstance(reference, dict):
            raise UiEmbeddedCandidateError(
                f"P2 UI core output is missing: {output_id}"
            )
        path, payload = _verified_payload(
            root,
            reference,
            label=f"P2 UI core {output_id}",
        )
        if _payload_lock(payload) != base_manifest.get("outputs", {}).get(
            output_id
        ):
            raise UiEmbeddedCandidateError(
                f"P2 UI core manifest output drift: {output_id}"
            )
        base_paths[output_id] = path
        base_payloads[output_id] = payload

    base_slps = base_payloads["slps"]
    if len(base_slps) != len(readiness_slps):
        raise UiEmbeddedCandidateError("P2 core and readiness SLPS sizes differ")
    slice_changed_offsets = slice_report.pop("changed_offsets")
    base_changed_offsets = _changed_offsets(readiness_slps, base_slps)
    overlap = sorted(set(slice_changed_offsets) & set(base_changed_offsets))
    if overlap:
        raise UiEmbeddedCandidateError(
            f"fresh-boot slice overlaps P2 core changes: {overlap[:16]!r}"
        )
    if any(
        base_slps[offset] != readiness_slps[offset]
        for offset in slice_changed_offsets
    ):
        raise UiEmbeddedCandidateError(
            "P2 core preimage differs at a fresh-boot slice offset"
        )
    merged_slps = bytearray(base_slps)
    for offset in slice_changed_offsets:
        merged_slps[offset] = slice_output[offset]
    final_slps = bytes(merged_slps)
    final_changed_offsets = _changed_offsets(base_slps, final_slps)
    if final_changed_offsets != slice_changed_offsets:
        raise UiEmbeddedCandidateError(
            "P3 core delta differs from the fixed-span slice"
        )

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
                    f"final P3 SLPS reread differs for {entry_id}"
                )

    base_font_hash = _sha256_bytes(
        decode_vt1_font_segment(base_slps, base_payloads["vt1"]).decoded
    )
    final_font_hash = _sha256_bytes(
        decode_vt1_font_segment(final_slps, base_payloads["vt1"]).decoded
    )
    if final_font_hash != base_font_hash:
        raise UiEmbeddedCandidateError("P3 fresh-boot slice changed the font")

    outputs_config = config.get("outputs")
    if not isinstance(outputs_config, dict):
        raise UiEmbeddedCandidateError("embedded UI candidate outputs are missing")
    component_root = _project_path(
        root,
        outputs_config.get("component_root"),
    )
    output_payloads = {
        "slps": final_slps,
        "vt1": base_payloads["vt1"],
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
    checks = {
        "selected_scene_count": len(selected_scene_ids)
        == ratchet.get("selected_scene_count"),
        "selected_entry_count": len(decisions)
        == ratchet.get("selected_entry_count"),
        "no_op_entry_count": selection["no_op_entry_count"]
        == ratchet.get("no_op_entry_count"),
        "selected_write_entry_count": selection["selected_write_entry_count"]
        == ratchet.get("selected_write_entry_count"),
        "selected_write_target_count": selection["selected_write_target_count"]
        == ratchet.get("selected_write_target_count"),
        "fixed_covered_entry_count": selection["fixed_covered_entry_count"]
        == ratchet.get("fixed_covered_entry_count"),
        "excluded_entry_count": selection["excluded_entry_count"]
        == ratchet.get("excluded_entry_count"),
        "slice_changed_byte_count": len(slice_changed_offsets)
        == ratchet.get("slice_changed_byte_count"),
        "slice_difference_range_count": slice_report["component"][
            "difference_range_count"
        ]
        == ratchet.get("slice_difference_range_count"),
    }
    if not all(checks.values()):
        raise UiEmbeddedCandidateError(
            f"fresh-boot UI candidate ratchet failed: {checks}"
        )

    acceptance = {
        "selected_groups_fixed_span_ready": all(
            group["readiness_status"] == "fixed_span_ready"
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
        "decoded_font_unchanged": final_font_hash == base_font_hash,
        "vt1_byte_exact_from_p2": output_payloads["vt1"]
        == base_payloads["vt1"],
        "compdata_byte_exact_from_p2": output_payloads["compdata"]
        == base_payloads["compdata"],
        "mtv_pros_byte_exact_from_p2": output_payloads["mtv_pros"]
        == base_payloads["mtv_pros"],
    }
    if not all(acceptance.values()):
        raise UiEmbeddedCandidateError(
            f"fresh-boot UI candidate acceptance failed: {acceptance}"
        )

    report = {
        "schema_version": 1,
        "status": (
            "integrated_ui_p3_fresh_boot_component_"
            "validated_iso_runtime_pending"
        ),
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
            },
        },
        "selection": {
            "scene_count": len(selected_scene_ids),
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
                "fresh_boot_tutorial_unit_stat_and_terrain_legend",
                "fresh_boot_default_protagonist_labels_both_routes",
            ],
            "pending_gates": [
                "exact_iso_static_binding",
                "fresh_process_boot",
                "both_protagonist_routes",
                "tutorial_stat_and_terrain_pages",
                "no_clipping_overlap_or_missing_glyphs",
                "zero_tlb_miss",
            ],
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
