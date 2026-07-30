"""Compose independently validated UI components without losing ownership."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .canary import rebuild_archive_with_replacement
from .codec import decode
from .iso_layout import (
    CORE_ARCHIVE_SPECS,
    read_executable_archive_offsets,
)
from .patch_audit import changed_offsets, sha256_bytes, summarize_diff
from .summary import parse_summary
from .text import augment_text_table, load_text_table
from .tim2 import scan_tim2
from .tim2_writeback import render_vt1_title_rgba
from .ui_menu import load_ui_font_overrides
from .writers import build_executable_offset_patch_plan


class UiIntegrationError(ValueError):
    """Validated UI components cannot be composed without a conflict."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiIntegrationError(
            f"cannot load JSON object {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise UiIntegrationError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiIntegrationError("project path must be a non-empty string")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiIntegrationError(
            f"path escapes project root: {raw}"
        ) from error
    return path


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_lock(path: Path, project_root: Path) -> dict:
    return {
        "path": str(path.relative_to(project_root)),
        "size": path.stat().st_size,
        "sha256": _sha256_path(path),
    }


def _payload_lock(payload: bytes) -> dict:
    return {
        "size": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _verify_json_reference(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, dict]:
    path = _project_path(project_root, reference.get("path"))
    if not path.is_file():
        raise UiIntegrationError(f"{label} is missing: {path}")
    actual_hash = _sha256_path(path)
    if actual_hash != reference.get("sha256"):
        raise UiIntegrationError(f"{label} SHA-256 drift")
    value = _json_object(path)
    required_status = reference.get("required_status")
    if (
        required_status is not None
        and value.get("status") != required_status
    ):
        raise UiIntegrationError(
            f"{label} status is {value.get('status')!r}, "
            f"expected {required_status!r}"
        )
    return path, value


def _verified_payload(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, bytes]:
    path = _project_path(project_root, reference.get("path"))
    if not path.is_file():
        raise UiIntegrationError(f"{label} is missing: {path}")
    payload = path.read_bytes()
    expected = {
        "size": reference.get("size"),
        "sha256": reference.get("sha256"),
    }
    if _payload_lock(payload) != expected:
        raise UiIntegrationError(f"{label} size or SHA-256 drift")
    return path, payload


def _apply_three_way_menu_patch(
    p0_font_slps: bytes,
    p0_fixed_slps: bytes,
    world_slps: bytes,
    composition: Mapping[str, object],
) -> tuple[bytes, dict]:
    if not (
        len(p0_font_slps)
        == len(p0_fixed_slps)
        == len(world_slps)
    ):
        raise UiIntegrationError("SLPS components have different sizes")
    menu_offsets = changed_offsets(p0_font_slps, p0_fixed_slps)
    world_offsets = changed_offsets(p0_font_slps, world_slps)
    overlap = tuple(sorted(set(menu_offsets) & set(world_offsets)))
    expected = {
        "mode": "three-way-byte-patch",
        "expected_changed_byte_count": len(menu_offsets),
        "expected_changed_range_count": summarize_diff(
            p0_font_slps,
            p0_fixed_slps,
        ).range_count,
        "expected_base_overlap_count": len(overlap),
    }
    if dict(composition) != expected:
        raise UiIntegrationError(
            f"SLPS three-way composition ratchet drift: {expected}"
        )
    if overlap:
        raise UiIntegrationError(
            "P0 menu patch overlaps P1/world-history SLPS changes"
        )

    output = bytearray(world_slps)
    for offset in menu_offsets:
        output[offset] = p0_fixed_slps[offset]
    result = bytes(output)
    menu_offset_set = set(menu_offsets)
    if any(result[offset] != p0_fixed_slps[offset] for offset in menu_offsets):
        raise UiIntegrationError("P0 menu bytes were not applied exactly")
    if any(
        result[offset] != world_slps[offset]
        for offset in range(len(result))
        if offset not in menu_offset_set
    ):
        raise UiIntegrationError("three-way patch changed an unowned SLPS byte")
    return result, {
        "mode": "three-way-byte-patch",
        "menu_diff": summarize_diff(
            p0_font_slps,
            p0_fixed_slps,
        ).to_mapping(),
        "world_base_diff": summarize_diff(
            p0_font_slps,
            world_slps,
        ).to_mapping(),
        "overlap_count": 0,
        "menu_bytes_exact": True,
        "world_bytes_outside_menu_exact": True,
        "changed_offsets": menu_offsets,
    }


def _decode_chunk(
    archive: bytes,
    offsets: tuple[int, ...],
    chunk_index: int,
    *,
    label: str,
) -> bytes:
    stored = archive[offsets[chunk_index] : offsets[chunk_index + 1]]
    result = decode(stored)
    if any(stored[result.consumed :]):
        raise UiIntegrationError(f"{label} has nonzero stream padding")
    return result.output


def _compose_title_menu(
    world_slps: bytes,
    world_vt1: bytes,
    title_slps: bytes,
    title_vt1: bytes,
    composition: Mapping[str, object],
) -> tuple[bytes, bytes, dict]:
    if composition.get("archive") != "VT1.BIN":
        raise UiIntegrationError("title integration must target VT1.BIN")
    chunk_index = composition.get("chunk_index")
    record_index = composition.get("record_index")
    picture_index = composition.get("picture_index")
    if (
        not isinstance(chunk_index, int)
        or not isinstance(record_index, int)
        or picture_index != 0
    ):
        raise UiIntegrationError("invalid title target coordinates")

    spec = CORE_ARCHIVE_SPECS["VT1.BIN"]
    world_offsets = read_executable_archive_offsets(
        world_slps,
        spec,
        len(world_vt1),
    )
    title_offsets = read_executable_archive_offsets(
        title_slps,
        spec,
        len(title_vt1),
    )
    if not 0 <= chunk_index < len(world_offsets) - 1:
        raise UiIntegrationError("title chunk index is outside VT1")

    world_decoded = _decode_chunk(
        world_vt1,
        world_offsets,
        chunk_index,
        label="P1 VT1 title chunk",
    )
    title_decoded = _decode_chunk(
        title_vt1,
        title_offsets,
        chunk_index,
        label="localized VT1 title chunk",
    )
    world_records = scan_tim2(world_decoded)
    title_records = scan_tim2(title_decoded)
    if len(world_records) != len(title_records):
        raise UiIntegrationError("title chunk TIM2 record count drift")
    if not 0 <= record_index < len(world_records):
        raise UiIntegrationError("title record index is outside chunk")
    world_record = world_records[record_index]
    title_record = title_records[record_index]
    if (
        world_record.offset,
        world_record.size,
    ) != (
        title_record.offset,
        title_record.size,
    ):
        raise UiIntegrationError("title TIM2 record geometry drift")
    source_record = world_decoded[world_record.offset : world_record.end]
    localized_record = title_decoded[
        title_record.offset : title_record.end
    ]
    if sha256_bytes(source_record) != composition.get(
        "source_record_sha256"
    ):
        raise UiIntegrationError("P1 title source record SHA-256 drift")
    if sha256_bytes(localized_record) != composition.get(
        "localized_record_sha256"
    ):
        raise UiIntegrationError("localized title record SHA-256 drift")
    if (
        world_decoded[: world_record.offset]
        != title_decoded[: title_record.offset]
        or world_decoded[world_record.end :]
        != title_decoded[title_record.end :]
    ):
        raise UiIntegrationError(
            "localized title component changed decoded bytes "
            "outside the target TIM2 record"
        )
    preview_rgba = render_vt1_title_rgba(localized_record)
    if sha256_bytes(preview_rgba) != composition.get(
        "preview_rgba_sha256"
    ):
        raise UiIntegrationError("localized title RGBA preview drift")

    modified_decoded = (
        world_decoded[: world_record.offset]
        + localized_record
        + world_decoded[world_record.end :]
    )
    codec = composition.get("codec")
    if not isinstance(codec, Mapping):
        raise UiIntegrationError("missing UI integration codec")
    strategy = codec.get("strategy")
    source_strategy = codec.get("source_strategy")
    alignment = codec.get("archive_alignment")
    fixed_allocation = codec.get("fixed_allocation")
    if (
        strategy != "precompressed-fixed-span"
        or source_strategy != "rust-maximum"
        or alignment != 16
        or not isinstance(fixed_allocation, int)
        or isinstance(fixed_allocation, bool)
        or fixed_allocation <= 0
    ):
        raise UiIntegrationError("unsupported UI integration codec")
    title_stored = title_vt1[
        title_offsets[chunk_index] : title_offsets[chunk_index + 1]
    ]
    if (
        len(title_stored) != fixed_allocation
        or len(title_stored)
        != world_offsets[chunk_index + 1] - world_offsets[chunk_index]
    ):
        raise UiIntegrationError(
            "precompressed title chunk does not preserve its allocation"
        )
    round_trip = decode(title_stored)
    if (
        round_trip.output != modified_decoded
        or any(title_stored[round_trip.consumed :])
    ):
        raise UiIntegrationError(
            "precompressed title stream does not decode exactly"
        )

    rebuilt_vt1, new_offsets, padding_size = (
        rebuild_archive_with_replacement(
            world_vt1,
            world_offsets,
            chunk_index=chunk_index,
            encoded_replacement=title_stored,
            alignment=alignment,
            minimum_allocation=fixed_allocation,
        )
    )
    unchanged_chunk_count = 0
    for index, (
        world_start,
        world_end,
        new_start,
        new_end,
    ) in enumerate(
        zip(
            world_offsets,
            world_offsets[1:],
            new_offsets,
            new_offsets[1:],
        )
    ):
        if index == chunk_index:
            continue
        if (
            world_vt1[world_start:world_end]
            != rebuilt_vt1[new_start:new_end]
        ):
            raise UiIntegrationError(
                f"non-title VT1 chunk {index} changed"
            )
        unchanged_chunk_count += 1

    offset_plan = build_executable_offset_patch_plan(
        world_slps,
        spec,
        new_offsets,
    )
    rebuilt_slps = offset_plan.apply(world_slps)
    if (
        read_executable_archive_offsets(
            rebuilt_slps,
            spec,
            len(rebuilt_vt1),
        )
        != new_offsets
    ):
        raise UiIntegrationError("final VT1 offsets fail SLPS reread")
    final_decoded = _decode_chunk(
        rebuilt_vt1,
        new_offsets,
        chunk_index,
        label="integrated VT1 title chunk",
    )
    final_records = scan_tim2(final_decoded)
    final_record = final_records[record_index]
    final_payload = final_decoded[final_record.offset : final_record.end]
    if final_payload != localized_record:
        raise UiIntegrationError("integrated title record is not exact")

    return rebuilt_slps, rebuilt_vt1, {
        "archive": "DATA/VT1.BIN",
        "chunk_index": chunk_index,
        "record_index": record_index,
        "picture_index": picture_index,
        "source_record": _payload_lock(source_record),
        "localized_record": _payload_lock(localized_record),
        "changed_pixel_count": sum(
            before != after
            for before, after in zip(source_record, localized_record)
        ),
        "preview_rgba_sha256": sha256_bytes(preview_rgba),
        "codec_strategy": source_strategy,
        "encoded_size": round_trip.consumed,
        "encoded_sha256": sha256_bytes(
            title_stored[: round_trip.consumed]
        ),
        "padding_size": len(title_stored) - round_trip.consumed,
        "rebuild_padding_size": padding_size,
        "fixed_allocation": fixed_allocation,
        "decoded_round_trip_exact": True,
        "chunk_count": len(world_offsets) - 1,
        "unchanged_chunk_count": unchanged_chunk_count,
        "offset_patch_plan": offset_plan.to_metadata(),
        "offset_reread_exact": True,
        "final_record_exact": True,
    }


def _audit_world_history(
    project_root: Path,
    world_config: Mapping[str, object],
    slps: bytes,
    mtv_pros: bytes,
) -> dict:
    font_reference = world_config.get("font_candidate")
    if not isinstance(font_reference, Mapping):
        raise UiIntegrationError("world-history font reference is missing")
    font_path = _project_path(
        project_root,
        font_reference.get("manifest"),
    )
    if _sha256_path(font_path) != font_reference.get("sha256"):
        raise UiIntegrationError("world-history font manifest drift")
    font_manifest = _json_object(font_path)
    overrides, _ = load_ui_font_overrides(
        project_root,
        world_config,
        font_manifest,
    )
    source = world_config.get("source")
    if not isinstance(source, Mapping):
        raise UiIntegrationError("world-history source is missing")
    table_reference = source.get("text_table")
    if not isinstance(table_reference, Mapping):
        raise UiIntegrationError("world-history text table is missing")
    table_path = _project_path(
        project_root,
        table_reference.get("path"),
    )
    if _sha256_path(table_path) != table_reference.get("sha256"):
        raise UiIntegrationError("world-history text-table drift")
    table = augment_text_table(load_text_table(table_path), overrides)

    translation_reference = world_config.get("translation_source")
    if not isinstance(translation_reference, Mapping):
        raise UiIntegrationError("world-history translations are missing")
    translation_path = _project_path(
        project_root,
        translation_reference.get("path"),
    )
    if _sha256_path(translation_path) != translation_reference.get(
        "sha256"
    ):
        raise UiIntegrationError("world-history translation-source drift")
    translations = _json_object(translation_path).get("entries")
    if not isinstance(translations, list):
        raise UiIntegrationError(
            "world-history translation entries are missing"
        )
    expected = {
        entry["id"]: entry["translation"] for entry in translations
    }

    offsets = read_executable_archive_offsets(
        slps,
        CORE_ARCHIVE_SPECS["MTV_PROS.BIN"],
        len(mtv_pros),
    )
    actual = {}
    decoded_hashes = []
    unknown_count = 0
    for chunk_index, (start, end) in enumerate(
        zip(offsets, offsets[1:])
    ):
        stored = mtv_pros[start:end]
        result = decode(stored)
        if any(stored[result.consumed :]):
            raise UiIntegrationError(
                f"integrated MTV_PROS chunk {chunk_index} has "
                "nonzero padding"
            )
        parsed = parse_summary(
            result.output,
            table,
            chunk_index=chunk_index,
        )
        unknown_count += parsed.unknown_code_count
        actual.update(
            {entry.entry_id: entry.text for entry in parsed.entries}
        )
        decoded_hashes.append(sha256_bytes(result.output))
    if actual != expected:
        raise UiIntegrationError(
            "integrated world-history text reread mismatch"
        )
    if unknown_count:
        raise UiIntegrationError(
            "integrated world-history contains unknown text codes"
        )
    return {
        "entry_count": len(actual),
        "chunk_count": len(offsets) - 1,
        "all_texts_exact": True,
        "unknown_code_count": 0,
        "decoded_chunk_signature_sha256": sha256_bytes(
            "".join(decoded_hashes).encode("ascii")
        ),
    }


def build_ui_p1_core_component(
    project_root: Path,
    config_path: Path,
    *,
    enforce_expected_outputs: bool = True,
) -> tuple[dict[str, bytes], dict]:
    """Compose the validated title, text, name, font and history layers."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiIntegrationError("unsupported UI integration schema")
    components = config.get("components")
    if not isinstance(components, Mapping):
        raise UiIntegrationError("UI integration components are missing")

    loaded_json = {}
    loaded_paths = {}
    payloads = {}
    payload_paths = {}
    for component_name, component in components.items():
        if not isinstance(component, Mapping):
            raise UiIntegrationError(
                f"component {component_name} must be an object"
            )
        for reference_name in ("config", "manifest"):
            reference = component.get(reference_name)
            if reference is None:
                continue
            if not isinstance(reference, Mapping):
                raise UiIntegrationError(
                    f"{component_name}.{reference_name} must be an object"
                )
            path, value = _verify_json_reference(
                root,
                reference,
                label=f"{component_name} {reference_name}",
            )
            loaded_json[(component_name, reference_name)] = value
            loaded_paths[(component_name, reference_name)] = path
        for payload_name in (
            "slps",
            "vt1",
            "mtv_pros",
            "compdata",
        ):
            reference = component.get(payload_name)
            if reference is None:
                continue
            if not isinstance(reference, Mapping):
                raise UiIntegrationError(
                    f"{component_name}.{payload_name} must be an object"
                )
            path, payload = _verified_payload(
                root,
                reference,
                label=f"{component_name} {payload_name}",
            )
            payloads[(component_name, payload_name)] = payload
            payload_paths[(component_name, payload_name)] = path

    composition = config.get("composition")
    if not isinstance(composition, Mapping):
        raise UiIntegrationError("UI integration composition is missing")
    menu_slps, menu_report = _apply_three_way_menu_patch(
        payloads[("p0_font_base", "slps")],
        payloads[("p0_fixed_slps", "slps")],
        payloads[("world_history", "slps")],
        composition["slps_menu_patch"],
    )
    title_composition = {
        **composition["title_menu"],
        "codec": composition["codec"],
    }
    final_slps, final_vt1, title_report = _compose_title_menu(
        menu_slps,
        payloads[("world_history", "vt1")],
        payloads[("title_menu", "slps")],
        payloads[("title_menu", "vt1")],
        title_composition,
    )
    vt1_table = CORE_ARCHIVE_SPECS["VT1.BIN"]
    menu_offsets = set(menu_report.pop("changed_offsets"))
    vt1_table_offsets = set(
        range(vt1_table.table_start, vt1_table.table_end + 1)
    )
    if menu_offsets & vt1_table_offsets:
        raise UiIntegrationError(
            "P0 menu patch overlaps the final VT1 offset table"
        )

    final_mtv = payloads[("world_history", "mtv_pros")]
    final_compdata = payloads[("p0_display_names", "compdata")]
    world_config = loaded_json[("world_history", "config")]
    world_audit = _audit_world_history(
        root,
        world_config,
        final_slps,
        final_mtv,
    )

    outputs = {
        "slps": final_slps,
        "vt1": final_vt1,
        "mtv_pros": final_mtv,
        "compdata": final_compdata,
    }
    expected_outputs = config.get("expected_outputs")
    if not isinstance(expected_outputs, Mapping):
        raise UiIntegrationError(
            "UI integration expected outputs are missing"
        )
    if enforce_expected_outputs:
        for name, payload in outputs.items():
            if _payload_lock(payload) != expected_outputs.get(name):
                raise UiIntegrationError(
                    f"integrated output lock drift: {name}"
                )

    fixed_slps_manifest = loaded_json[
        ("p0_fixed_slps", "manifest")
    ]
    display_manifest = loaded_json[
        ("p0_display_names", "manifest")
    ]
    title_manifest = loaded_json[("title_menu", "manifest")]
    actual_ratchet = {
        "p0_slps_covered_entry_count": fixed_slps_manifest[
            "selection"
        ]["fixed_covered_entry_count"],
        "p0_slps_changed_byte_count": menu_report["menu_diff"][
            "diff_count"
        ],
        "p0_slps_changed_range_count": menu_report["menu_diff"][
            "range_count"
        ],
        "p0_display_name_entry_count": display_manifest["selection"][
            "translation_entry_count"
        ],
        "world_history_entry_count": world_audit["entry_count"],
        "vt1_chunk_count": title_report["chunk_count"],
        "vt1_unchanged_chunk_count": title_report[
            "unchanged_chunk_count"
        ],
        "title_changed_pixel_count": title_manifest[
            "component_build"
        ]["injection"]["changed_pixel_count"],
        "slps_component_overlap_count": menu_report["overlap_count"],
    }
    if actual_ratchet != config.get("ratchet"):
        raise UiIntegrationError(
            f"UI integration ratchet drift: {actual_ratchet}"
        )

    input_report = {}
    for component_name, component in components.items():
        component_report = {}
        for reference_name in ("config", "manifest"):
            path = loaded_paths.get((component_name, reference_name))
            if path is not None:
                component_report[reference_name] = _file_lock(path, root)
        for payload_name in (
            "slps",
            "vt1",
            "mtv_pros",
            "compdata",
        ):
            path = payload_paths.get((component_name, payload_name))
            if path is not None:
                component_report[payload_name] = _file_lock(path, root)
        input_report[component_name] = component_report

    report = {
        "schema_version": 1,
        "status": "integrated_component_validated_iso_runtime_pending",
        "profile_id": config["profile_id"],
        "scope": config["scope"],
        "content_policy": (
            "Hashes, sizes, counts and diff summaries only; no game bytes "
            "or localized text are embedded."
        ),
        "inputs": {
            "config": _file_lock(config_path, root),
            "components": input_report,
        },
        "composition": {
            "slps_menu": menu_report,
            "title_menu": title_report,
            "mtv_pros": {
                "source_component_exact": True,
                **world_audit,
            },
            "compdata": {
                "display_name_component_exact": True,
                "entry_count": display_manifest["selection"][
                    "translation_entry_count"
                ],
            },
        },
        "outputs": {
            name: _payload_lock(payload)
            for name, payload in outputs.items()
        },
        "ratchet": {
            "expected": config["ratchet"],
            "actual": actual_ratchet,
            "passed": True,
        },
        "acceptance": {
            "all_input_hashes_locked": True,
            "p0_menu_patch_applied_exactly": True,
            "slps_owner_overlap_count_zero": True,
            "p1_vt1_non_title_chunks_exact": True,
            "localized_title_record_and_preview_exact": True,
            "vt1_offset_table_reread_exact": True,
            "all_28_world_history_texts_reread_exact": True,
            "display_name_compdata_exact": True,
            "all_output_locks_exact": True,
        },
        "runtime": {
            "status": "not_tested",
            "pending_gates": [
                "fresh_process_boot_exact_iso",
                "title_selected_and_unselected_states",
                "opening_player_setup_and_dynamic_name",
                "p0_menu_routes_and_information_pages",
                "world_history_scroll_start_middle_end",
                "new_raw_trail_glyph_classes",
                "zero_tlb_miss",
            ],
        },
    }
    return outputs, report


__all__ = [
    "UiIntegrationError",
    "build_ui_p1_core_component",
]
