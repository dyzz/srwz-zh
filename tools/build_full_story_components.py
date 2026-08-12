#!/usr/bin/env python3
"""Compose the release UI, global font, story, overview, and battle components."""

from __future__ import annotations

import argparse
import json
import re
import struct
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from srwz.auto_demo import (
        AutoDemoError,
        discover_auto_demo_name_slots,
        rewrite_auto_demo_names,
    )
    from srwz.codec import decode_production as decode, encode, reencode_changed_suffix
    from srwz.compressed_workspace import CompressedStreamWorkspace
    from srwz.diagnostics import require_work_output
    from srwz.display_names import (
        DisplayNameError,
        load_display_name_source,
        load_full_unit_name_corpus,
        parse_display_names,
    )
    from srwz.font import (
        ascii_glyph_index,
        decode_glyph,
        decode_vt1_font_segment,
        sha256_bytes,
    )
    from srwz.menu import parse_menu_file
    from srwz.intermission_font_geometry import (
        IntermissionFontGeometryError,
        IntermissionFontGeometryMetrics,
        apply_intermission_font_geometry_patch,
    )
    from srwz.iso_layout import (
        CORE_ARCHIVE_SPECS,
        ExecutableOffsetSpec,
        read_executable_archive_offsets,
    )
    from srwz.image_export import parse_seg_offsets
    from srwz.psmt4 import swizzle_psmt4, unswizzle_psmt4
    from srwz.hsfc_overview import replace_hsfc_overviews_in_place
    from srwz.srvc import (
        parse_srvc_archive,
        parse_srvc_archive_with_layout,
        rebuild_srvc_archive,
    )
    from srwz.stage_overview import replace_stage_overviews_in_place
    from srwz.stage_formations import (
        STAGE_OFFSET_SPEC,
        formation_inventory_sha256,
        load_locked_stage_default_formations,
    )
    from srwz.stage import parse_stage_system_dialogues
    from srwz.stage_title_graphics import (
        GLYPH_SIZE as STAGE_TITLE_GLYPH_SIZE,
        TITLE_HEIGHT as STAGE_TITLE_HEIGHT,
        TITLE_IMAGE_SIZE as STAGE_TITLE_IMAGE_SIZE,
        TITLE_WIDTH as STAGE_TITLE_WIDTH,
        pack_linear_4bpp,
        render_stage_title,
        unpack_linear_4bpp,
    )
    from srwz.tim2 import scan_tim2
    from srwz.terrain_names import TerrainNameError, build_terrain_names
    from srwz.text import (
        PreparedTextEncoder,
        SrwzTextEncodeError,
        control_notation_tokens,
        decode_text,
        encode_text,
        load_text_table,
        normalize_original_fullwidth_ascii,
        original_fullwidth_ascii_overrides,
        project_runtime_text_table,
    )
    from srwz.writeback import replace_archive_chunk_with_preceding_zero_slack
    from srwz.world_map_titles import (
        WorldMapTitleError,
        build_world_map_titles,
    )
    from srwz.writers import (
        WritebackError,
        build_executable_offset_patch_plan,
        replace_menu_texts_in_place,
        replace_stage_system_dialogues_in_place,
    )
except ModuleNotFoundError:
    from tools.srwz.auto_demo import (
        AutoDemoError,
        discover_auto_demo_name_slots,
        rewrite_auto_demo_names,
    )
    from tools.srwz.codec import (
        decode_production as decode,
        encode,
        reencode_changed_suffix,
    )
    from tools.srwz.compressed_workspace import CompressedStreamWorkspace
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.display_names import (
        DisplayNameError,
        load_display_name_source,
        load_full_unit_name_corpus,
        parse_display_names,
    )
    from tools.srwz.font import (
        ascii_glyph_index,
        decode_glyph,
        decode_vt1_font_segment,
        sha256_bytes,
    )
    from tools.srwz.menu import parse_menu_file
    from tools.srwz.intermission_font_geometry import (
        IntermissionFontGeometryError,
        IntermissionFontGeometryMetrics,
        apply_intermission_font_geometry_patch,
    )
    from tools.srwz.iso_layout import (
        CORE_ARCHIVE_SPECS,
        ExecutableOffsetSpec,
        read_executable_archive_offsets,
    )
    from tools.srwz.image_export import parse_seg_offsets
    from tools.srwz.psmt4 import swizzle_psmt4, unswizzle_psmt4
    from tools.srwz.hsfc_overview import replace_hsfc_overviews_in_place
    from tools.srwz.srvc import (
        parse_srvc_archive,
        parse_srvc_archive_with_layout,
        rebuild_srvc_archive,
    )
    from tools.srwz.stage_overview import replace_stage_overviews_in_place
    from tools.srwz.stage_formations import (
        STAGE_OFFSET_SPEC,
        formation_inventory_sha256,
        load_locked_stage_default_formations,
    )
    from tools.srwz.stage import parse_stage_system_dialogues
    from tools.srwz.stage_title_graphics import (
        GLYPH_SIZE as STAGE_TITLE_GLYPH_SIZE,
        TITLE_HEIGHT as STAGE_TITLE_HEIGHT,
        TITLE_IMAGE_SIZE as STAGE_TITLE_IMAGE_SIZE,
        TITLE_WIDTH as STAGE_TITLE_WIDTH,
        pack_linear_4bpp,
        render_stage_title,
        unpack_linear_4bpp,
    )
    from tools.srwz.tim2 import scan_tim2
    from tools.srwz.terrain_names import TerrainNameError, build_terrain_names
    from tools.srwz.text import (
        PreparedTextEncoder,
        SrwzTextEncodeError,
        control_notation_tokens,
        decode_text,
        encode_text,
        load_text_table,
        normalize_original_fullwidth_ascii,
        original_fullwidth_ascii_overrides,
        project_runtime_text_table,
    )
    from tools.srwz.writeback import (
        replace_archive_chunk_with_preceding_zero_slack,
    )
    from tools.srwz.world_map_titles import (
        WorldMapTitleError,
        build_world_map_titles,
    )
    from tools.srwz.writers import (
        WritebackError,
        build_executable_offset_patch_plan,
        replace_menu_texts_in_place,
        replace_stage_system_dialogues_in_place,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/full-story-components.json"


class FullStoryComponentError(ValueError):
    """A locked input or composition invariant failed."""


def _commit_compdata_stage(
    stored_compdata: bytes,
    decoded_output: bytes,
    decoded_input,
    codec: dict,
    *,
    label: str,
    workspace: CompressedStreamWorkspace | None,
) -> bytes:
    """Commit one decoded write stage or perform the legacy standalone rebuild."""

    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError(f"{label} codec policy is invalid")
    if workspace is not None:
        if stored_compdata != workspace.stored:
            raise FullStoryComponentError(f"{label} workspace source drift")
        if decoded_input.output != workspace.current:
            raise FullStoryComponentError(f"{label} workspace ordering drift")
        try:
            workspace.replace(decoded_output, stage=label)
        except ValueError as error:
            raise FullStoryComponentError(str(error)) from error
        return decoded_output
    try:
        rebuilt = reencode_changed_suffix(
            stored_compdata,
            decoded_output,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=codec["max_output_size"],
            original_result=decoded_input,
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(f"{label} compression failed: {error}") from error
    round_trip = decode(rebuilt)
    if (
        round_trip.consumed != len(rebuilt)
        or round_trip.output != decoded_output
        or round_trip.flags != decoded_input.flags
    ):
        raise FullStoryComponentError(f"{label} round-trip failed")
    return rebuilt


def _count_span_groups_containing_offsets(
    span_groups: list[list[tuple[int, int]]],
    changed_offsets: set[int],
) -> int:
    """Count span groups touched by at least one changed byte offset."""

    sorted_changed_offsets = sorted(changed_offsets)

    def span_contains_change(start: int, end: int) -> bool:
        index = bisect_left(sorted_changed_offsets, start)
        return (
            index < len(sorted_changed_offsets)
            and sorted_changed_offsets[index] < end
        )

    return sum(
        any(span_contains_change(start, end) for start, end in spans)
        for spans in span_groups
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Compare the current inputs with the last fully validated state, "
            "rebuild only affected component members, and reject unknown "
            "dependency changes."
        ),
    )
    return parser.parse_args()


def _project_path(raw: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise FullStoryComponentError("project path must be non-empty")
    root = PROJECT_ROOT.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise FullStoryComponentError(f"path escapes project root: {raw}") from error
    return path


def _json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FullStoryComponentError(f"cannot read JSON: {path}") from error
    if not isinstance(document, dict):
        raise FullStoryComponentError(f"JSON root is not an object: {path}")
    return document


def _locked_file(reference: dict, *, label: str) -> tuple[Path, bytes]:
    if not isinstance(reference, dict):
        raise FullStoryComponentError(f"{label} lock is invalid")
    path = _project_path(reference.get("path"))
    data = path.read_bytes()
    expected_size = reference.get("size")
    expected_hash = reference.get("sha256")
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or len(data) != expected_size
        or sha256_bytes(data) != expected_hash
    ):
        raise FullStoryComponentError(f"{label} lock drift")
    return path, data


def _file_lock(path: Path, data: bytes) -> dict:
    return {
        "path": str(path.relative_to(PROJECT_ROOT.resolve())),
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def _manifest(reference: dict, *, label: str) -> tuple[Path, dict]:
    path, data = _locked_file(reference, label=label)
    return path, json.loads(data.decode("utf-8"))


def _output_lock(path: Path, data: bytes) -> dict:
    return {
        "path": str(path.relative_to(PROJECT_ROOT.resolve())),
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def _incremental_state_path(output_root: Path) -> Path:
    return output_root / "incremental-state.json"


SLPS_MEMBER = "SLPS_258.87"
VT1_MEMBER = "DATA/VT1.BIN"
COMPDATA_MEMBER = "DATA/COMPDATA.BN"
NISVDATA_MEMBER = "DATA/NISVDATA.BIN"
MTV_PROS_MEMBER = "DATA/MTV_PROS.BIN"
STAGE_MEMBER = "DATA/STAGE.BIN"
HSFC_MEMBER = "DATA/HSFC.BIN"
HB_MEMBER = "HEDBDY/HB.BIN"
KVMDATA_MEMBER = "KURODATA/KVMDATA.BIN"
SRVC_MEMBERS = frozenset({"BTL/SRVC.BIN", "BTL/SRVC.SEG"})
VEFF_MEMBER = "EFF/VEFF2DX.BIN"
MAPMODEL_MEMBER = "MAP/MAPMODEL.BIN"
AUTO_DEMO_MEMBERS = frozenset(
    {"BTL/OP0.BIN", "BTL/OP1.BIN", "BTL/OP2.BIN"}
)
ALL_COMPONENT_MEMBERS = frozenset(
    {
        SLPS_MEMBER,
        VT1_MEMBER,
        COMPDATA_MEMBER,
        NISVDATA_MEMBER,
        MTV_PROS_MEMBER,
        STAGE_MEMBER,
        HSFC_MEMBER,
        HB_MEMBER,
        KVMDATA_MEMBER,
        *SRVC_MEMBERS,
        VEFF_MEMBER,
        MAPMODEL_MEMBER,
        *AUTO_DEMO_MEMBERS,
    }
)


CONFIG_SECTION_IMPACTS = {
    "base_ui": {
        SLPS_MEMBER,
        VT1_MEMBER,
        COMPDATA_MEMBER,
        MTV_PROS_MEMBER,
        NISVDATA_MEMBER,
        HSFC_MEMBER,
        VEFF_MEMBER,
    },
    "full_story_font": ALL_COMPONENT_MEMBERS
    - {MTV_PROS_MEMBER, HB_MEMBER, KVMDATA_MEMBER},
    "full_story_stage": {STAGE_MEMBER, HB_MEMBER},
    "full_pilot_names": {COMPDATA_MEMBER, STAGE_MEMBER, HSFC_MEMBER},
    "auto_demo_overlays": {SLPS_MEMBER, *AUTO_DEMO_MEMBERS},
    "compdata_battle_lines": {COMPDATA_MEMBER},
    "reviewed_weapons": {COMPDATA_MEMBER},
    "full_stage_titles": {SLPS_MEMBER, VT1_MEMBER, COMPDATA_MEMBER},
    "stage_overviews": {STAGE_MEMBER},
    "hsfc_overviews": {HSFC_MEMBER},
    "remaining_ui": {SLPS_MEMBER, COMPDATA_MEMBER, STAGE_MEMBER},
    "nisv_effect_names": {NISVDATA_MEMBER},
    "srvc_battle_text": set(SRVC_MEMBERS),
    "scenario_select_effect": {SLPS_MEMBER, VEFF_MEMBER},
    "mode_select_effect": {VEFF_MEMBER},
    "kvmdata": {KVMDATA_MEMBER},
    "world_map_titles": {MAPMODEL_MEMBER},
    "composition": {SLPS_MEMBER, VT1_MEMBER},
    "intermission_list_font_geometry": {SLPS_MEMBER},
}


INPUT_IMPACTS = {
    "base_ui_manifest": CONFIG_SECTION_IMPACTS["base_ui"],
    "full_story_font_manifest": CONFIG_SECTION_IMPACTS["full_story_font"],
    "full_story_stage_report": {STAGE_MEMBER, HB_MEMBER},
    "pilot_name_structure": {COMPDATA_MEMBER},
    "story_speakers": {COMPDATA_MEMBER, *AUTO_DEMO_MEMBERS},
    "full_unit_names": {COMPDATA_MEMBER, SLPS_MEMBER, *AUTO_DEMO_MEMBERS},
    "full_story_font_proposal": CONFIG_SECTION_IMPACTS["full_story_font"],
    "stage_names": {SLPS_MEMBER, VT1_MEMBER, COMPDATA_MEMBER},
    "stage_title_format": {COMPDATA_MEMBER},
    "stage_overviews": {STAGE_MEMBER},
    "stage_system_dialogue": {STAGE_MEMBER},
    "hsfc_overviews": {HSFC_MEMBER},
    "original_hsfc": {HSFC_MEMBER},
    "menu_descriptor": {SLPS_MEMBER, COMPDATA_MEMBER},
    "stage_default_formation_corpus": {STAGE_MEMBER},
    "stage_default_formation_inventory": {STAGE_MEMBER},
    "remaining_ui_parts": {COMPDATA_MEMBER},
    "reviewed_weapons": {COMPDATA_MEMBER},
    "compdata_battle_lines": {COMPDATA_MEMBER},
    "original_compdata": {COMPDATA_MEMBER},
    "original_nisvdata": {NISVDATA_MEMBER},
    "original_slps": {
        SLPS_MEMBER,
        NISVDATA_MEMBER,
        HSFC_MEMBER,
        VEFF_MEMBER,
        MAPMODEL_MEMBER,
        *AUTO_DEMO_MEMBERS,
    },
    "original_stage": {STAGE_MEMBER},
    "srvc_battle_text_corpus": set(SRVC_MEMBERS),
    "original_srvc_bin": set(SRVC_MEMBERS),
    "original_srvc_seg": set(SRVC_MEMBERS),
    "font_slps": CONFIG_SECTION_IMPACTS["full_story_font"],
    "font_vt1": CONFIG_SECTION_IMPACTS["full_story_font"],
    "font_component_report": CONFIG_SECTION_IMPACTS["full_story_font"],
    "stage": {STAGE_MEMBER},
    "hb": {STAGE_MEMBER, HB_MEMBER},
    "kvmdata": {KVMDATA_MEMBER},
    "original_veff2dx": {VEFF_MEMBER},
    "world_map_title_corpus": {MAPMODEL_MEMBER},
    "world_map_title_render_snapshot": {MAPMODEL_MEMBER},
    "world_map_original_slps": {MAPMODEL_MEMBER},
    "world_map_original_archive": {MAPMODEL_MEMBER},
    "terrain_name_corpus": {MAPMODEL_MEMBER},
    "terrain_name_inventory": {MAPMODEL_MEMBER},
    "auto_demo_title_corpus": {SLPS_MEMBER},
    "auto_demo_original_slps": {SLPS_MEMBER},
    "auto_demo_story_speakers": set(AUTO_DEMO_MEMBERS),
    "auto_demo_unit_names": {SLPS_MEMBER, *AUTO_DEMO_MEMBERS},
}


REMAINING_UI_IMPACTS = {
    "compdata_direct_by_offset": {COMPDATA_MEMBER},
    "compdata_context_help_by_offset": {COMPDATA_MEMBER},
    "compdata_inline_by_offset": {COMPDATA_MEMBER},
    "leadership_effect_by_offset": {COMPDATA_MEMBER},
    "slps_context_ui_by_offset": {SLPS_MEMBER},
    "slps_by_offset": {SLPS_MEMBER},
    "nisv_effect_names": {NISVDATA_MEMBER},
    "stage_fixed_formation_by_offset": {STAGE_MEMBER},
    "display_names_by_source_text": {COMPDATA_MEMBER, *AUTO_DEMO_MEMBERS},
    # This inventory is currently validation-only, but recomputing COMPDATA
    # keeps policy changes fail-closed instead of silently accepting them.
    "atlas_by_source_text": {COMPDATA_MEMBER},
    "policy": {SLPS_MEMBER, COMPDATA_MEMBER},
    "editorial_status": {SLPS_MEMBER, COMPDATA_MEMBER},
}


def _normalized_binary_config(value: object) -> object:
    """Drop locks and ratchets that validate a build but do not create bytes."""

    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key in {"size", "sha256", "expected"}:
                continue
            result[key] = _normalized_binary_config(child)
        return result
    if isinstance(value, list):
        return [_normalized_binary_config(child) for child in value]
    return value


def _changed_remaining_ui_impacts(
    baseline: dict,
    current: dict,
) -> tuple[set[str], list[str]]:
    affected = set()
    reasons = []
    changed_keys = {
        key
        for key in set(baseline) | set(current)
        if baseline.get(key) != current.get(key)
    }
    metadata_keys = {"schema_version", "translation_id", "language"}
    unknown = changed_keys - set(REMAINING_UI_IMPACTS) - metadata_keys - {
        "accepted_current_preimages_by_offset"
    }
    if unknown:
        raise FullStoryComponentError(
            "incremental build has no remaining-UI dependency rule for: "
            + ", ".join(sorted(unknown))
        )
    for key in sorted(changed_keys & set(REMAINING_UI_IMPACTS)):
        affected.update(REMAINING_UI_IMPACTS[key])
        reasons.append(f"remaining-ui:{key}")
    if "accepted_current_preimages_by_offset" in changed_keys:
        paired = set()
        if changed_keys & {
            "compdata_direct_by_offset",
            "compdata_context_help_by_offset",
            "compdata_inline_by_offset",
            "leadership_effect_by_offset",
        }:
            paired.add(COMPDATA_MEMBER)
        if changed_keys & {"slps_context_ui_by_offset", "slps_by_offset"}:
            paired.add(SLPS_MEMBER)
        if not paired:
            raise FullStoryComponentError(
                "accepted-current preimage changed without a matching text map"
            )
        affected.update(paired)
        reasons.append("remaining-ui:accepted_current_preimages_by_offset")
    return affected, reasons


def _load_or_seed_incremental_state(
    *,
    config_path: Path,
    config: dict,
    output_root: Path,
    manifest_path: Path,
    manifest: dict,
    remaining_ui_path: Path,
    remaining_ui: dict,
) -> dict:
    state_path = _incremental_state_path(output_root)
    manifest_data = manifest_path.read_bytes()
    if state_path.is_file():
        state = _json(state_path)
        if (
            state.get("schema_version") in {1, 2}
            and state.get("component_manifest")
            == _file_lock(manifest_path, manifest_data)
            and isinstance(state.get("config"), dict)
            and isinstance(state.get("remaining_ui"), dict)
        ):
            return state

    current_config_lock = _file_lock(config_path, config_path.read_bytes())
    current_remaining_lock = _file_lock(
        remaining_ui_path,
        remaining_ui_path.read_bytes(),
    )
    prior_inputs = manifest.get("inputs", {})
    matching_remaining_locks = [
        lock
        for lock in prior_inputs.values()
        if isinstance(lock, dict) and lock.get("path") == current_remaining_lock["path"]
    ]
    if (
        prior_inputs.get("config") != current_config_lock
        or not matching_remaining_locks
        or any(lock != current_remaining_lock for lock in matching_remaining_locks)
    ):
        raise FullStoryComponentError(
            "incremental state is missing or stale; run one full component build"
        )
    return {
        "schema_version": 2,
        "component_manifest": _file_lock(manifest_path, manifest_data),
        "config": config,
        "remaining_ui": remaining_ui,
    }


def _write_incremental_state(
    *,
    config_path: Path,
    config: dict,
    output_root: Path,
    manifest_path: Path,
) -> None:
    remaining_reference = config.get("remaining_ui", {}).get("translations")
    remaining_ui_path, remaining_data = _locked_file(
        remaining_reference,
        label="remaining UI translations",
    )
    state = {
        "schema_version": 2,
        "component_manifest": _file_lock(
            manifest_path,
            manifest_path.read_bytes(),
        ),
        "config_path": str(config_path.relative_to(PROJECT_ROOT.resolve())),
        "config": config,
        "remaining_ui_path": str(
            remaining_ui_path.relative_to(PROJECT_ROOT.resolve())
        ),
        "remaining_ui": json.loads(remaining_data.decode("utf-8")),
    }
    state_path = _incremental_state_path(output_root)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _validate_prior_component_outputs(
    output_root: Path,
    manifest: dict,
) -> None:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != ALL_COMPONENT_MEMBERS:
        raise FullStoryComponentError(
            "prior component manifest has an incomplete output member set"
        )
    for member, lock in outputs.items():
        if not isinstance(lock, dict):
            raise FullStoryComponentError(
                f"prior component output lock is invalid: {member}"
            )
        path = output_root / member
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise FullStoryComponentError(
                f"prior component output is missing: {member}"
            ) from error
        if _output_lock(path, payload) != lock:
            raise FullStoryComponentError(
                f"incremental build refused because component drifted: {member}"
            )


def _prior_input_path(prior_report: dict, label: str) -> Path:
    lock = prior_report.get("inputs", {}).get(label)
    if not isinstance(lock, dict):
        raise FullStoryComponentError(
            f"prior component input lock is missing: {label}"
        )
    return _project_path(lock.get("path"))


def _prior_output_payload(
    output_root: Path,
    member: str,
) -> bytes:
    try:
        return (output_root / member).read_bytes()
    except OSError as error:
        raise FullStoryComponentError(
            f"prior component output is missing: {member}"
        ) from error


def _plan_incremental_members(
    *,
    baseline_config: dict,
    current_config: dict,
    baseline_remaining_ui: dict,
    current_remaining_ui: dict,
    prior_report: dict,
) -> tuple[set[str], list[str]]:
    """Resolve input drift to binary members; reject every unknown edge."""

    affected = set()
    reasons = []
    baseline_binary = _normalized_binary_config(baseline_config)
    current_binary = _normalized_binary_config(current_config)
    metadata_sections = {
        "schema_version",
        "profile_id",
        "scope",
        "outputs",
    }
    changed_sections = {
        key
        for key in set(baseline_binary) | set(current_binary)
        if baseline_binary.get(key) != current_binary.get(key)
    }
    unknown_sections = changed_sections - set(CONFIG_SECTION_IMPACTS) - metadata_sections
    if unknown_sections:
        raise FullStoryComponentError(
            "incremental build has no config dependency rule for: "
            + ", ".join(sorted(unknown_sections))
        )
    for section in sorted(changed_sections & set(CONFIG_SECTION_IMPACTS)):
        affected.update(CONFIG_SECTION_IMPACTS[section])
        reasons.append(f"config:{section}")

    prior_inputs = prior_report.get("inputs")
    if not isinstance(prior_inputs, dict):
        raise FullStoryComponentError("prior component input locks are missing")
    remaining_path = current_config.get("remaining_ui", {}).get(
        "translations", {}
    ).get("path")
    remaining_labels = {
        "remaining_display_names",
        "remaining_ui_translations",
        "auto_demo_residual_names",
    }
    changed_input_labels = []
    for label, lock in prior_inputs.items():
        if label == "config":
            continue
        if not isinstance(lock, dict) or not isinstance(lock.get("path"), str):
            raise FullStoryComponentError(
                f"prior component input lock is invalid: {label}"
            )
        path = _project_path(lock["path"])
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise FullStoryComponentError(
                f"incremental input is missing: {label}"
            ) from error
        if _file_lock(path, payload) != lock:
            changed_input_labels.append(label)

    remaining_changed = any(
        label in remaining_labels
        and prior_inputs[label].get("path") == remaining_path
        for label in changed_input_labels
    )
    if remaining_changed:
        remaining_affected, remaining_reasons = _changed_remaining_ui_impacts(
            baseline_remaining_ui,
            current_remaining_ui,
        )
        affected.update(remaining_affected)
        reasons.extend(remaining_reasons)

    for label in sorted(changed_input_labels):
        if label in remaining_labels and prior_inputs[label].get("path") == remaining_path:
            continue
        impact = INPUT_IMPACTS.get(label)
        if impact is None and label.startswith("auto_demo_original_op") and (
            label.endswith("_bin") or label.endswith("_seg")
        ):
            stem = label.removeprefix("auto_demo_original_").removesuffix(
                "_bin" if label.endswith("_bin") else "_seg"
            )
            impact = {f"BTL/{stem.upper()}.BIN"}
        if impact is None:
            raise FullStoryComponentError(
                f"incremental build has no input dependency rule for: {label}"
            )
        affected.update(impact)
        reasons.append(f"input:{label}")

    if not affected <= ALL_COMPONENT_MEMBERS:
        raise FullStoryComponentError("incremental dependency graph emitted an unknown member")
    return affected, reasons


def _sha_locked_json(reference: dict, *, label: str) -> tuple[Path, dict]:
    if not isinstance(reference, dict):
        raise FullStoryComponentError(f"{label} lock is invalid")
    path = _project_path(reference.get("path"))
    data = path.read_bytes()
    if sha256_bytes(data) != reference.get("sha256"):
        raise FullStoryComponentError(f"{label} SHA-256 drift")
    return path, _json(path)


def _full_story_overrides(
    font_manifest: dict,
) -> tuple[Path, dict[str, int], dict[str, int], dict]:
    proposal_path, proposal = _sha_locked_json(
        font_manifest.get("proposal"),
        label="full-story font proposal",
    )
    assignments = proposal.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        raise FullStoryComponentError("full-story font proposal has no assignments")
    overrides = {}
    seen_codes = set()
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise FullStoryComponentError("full-story font assignment is malformed")
        character = assignment.get("character")
        try:
            code = int(assignment.get("code"), 16)
        except (TypeError, ValueError) as error:
            raise FullStoryComponentError(
                "full-story font assignment code is malformed"
            ) from error
        if (
            not isinstance(character, str)
            or len(character) != 1
            or character in overrides
            or code in seen_codes
        ):
            raise FullStoryComponentError(
                "full-story font assignments are not one-to-one"
            )
        overrides[character] = code
        seen_codes.add(code)
    raw_aliases = proposal.get("surface_alias_assignments", [])
    if not isinstance(raw_aliases, list):
        raise FullStoryComponentError(
            "full-story surface alias assignments are malformed"
        )
    surface_aliases = {}
    for assignment in raw_aliases:
        if not isinstance(assignment, dict):
            raise FullStoryComponentError(
                "full-story surface alias assignment is malformed"
            )
        character = assignment.get("character")
        primary_code = assignment.get("primary_code")
        try:
            code = int(assignment.get("code"), 16)
        except (TypeError, ValueError) as error:
            raise FullStoryComponentError(
                "full-story surface alias code is malformed"
            ) from error
        if (
            not isinstance(character, str)
            or len(character) != 1
            or character in surface_aliases
            or character not in overrides
            or primary_code != f"{overrides[character]:04X}"
            or not (0x8140 <= overrides[character] < 0x889F)
            or 0x8140 <= code < 0x889F
            or code in seen_codes
        ):
            raise FullStoryComponentError(
                "full-story surface aliases are not safe one-to-one mappings"
            )
        surface_aliases[character] = code
        seen_codes.add(code)
    alias_report = proposal.get("surface_safe_aliases", {})
    if raw_aliases and (
        not isinstance(alias_report, dict)
        or alias_report.get("assignment_count") != len(raw_aliases)
        or alias_report.get("alias_codes_default_width_only") is not True
        or alias_report.get("primary_codes_preserved") is not True
    ):
        raise FullStoryComponentError("full-story surface alias report drift")
    return proposal_path, overrides, surface_aliases, alias_report


def _stored_text_overrides(
    table,
    primary: dict[str, int],
    aliases: dict[str, int] | None = None,
) -> dict[str, int]:
    """Build the production codebook for stored visible text.

    Localized CJK keeps its assigned or surface-safe code.  Printable ASCII
    deliberately replaces every proposal-era ASCII assignment with the
    original game's two-byte fullwidth code so the renderer never sees a raw
    visible byte sequence.
    """

    overrides = dict(primary)
    if aliases:
        overrides.update(aliases)
    overrides.update(original_fullwidth_ascii_overrides(table))
    overrides[" "] = ord(" ")
    return overrides


def _two_byte_visible_spaces(text: str) -> str:
    """Store visible word separators through the stock 0x8140 glyph."""

    if not isinstance(text, str):
        raise TypeError("visible text must be a string")
    return text.replace(" ", "\u3000")


def _apply_full_pilot_names(
    stored_compdata: bytes,
    reference: dict,
    font_manifest: dict,
    *,
    workspace: CompressedStreamWorkspace | None = None,
) -> tuple[bytes, dict, Path, Path, Path, Path, Path]:
    if not isinstance(reference, dict):
        raise FullStoryComponentError("full pilot-name configuration is invalid")
    structure_path, structure_data = _locked_file(
        reference.get("structure"),
        label="display-name structure config",
    )
    speaker_path, speaker_data = _locked_file(
        reference.get("story_speakers"),
        label="story speaker corpus",
    )
    residual_path, residual_data = _locked_file(
        reference.get("residual_names"),
        label="remaining display-name translations",
    )
    unit_path, _unit_data = _locked_file(
        reference.get("unit_names"),
        label="full unit-name corpus",
    )
    (
        proposal_path,
        overrides,
        surface_aliases,
        surface_alias_report,
    ) = _full_story_overrides(font_manifest)
    if not surface_aliases:
        raise FullStoryComponentError(
            "full-story font has no safe intermission display-name aliases"
        )
    try:
        structure, _original_data, original_names, _context = (
            load_display_name_source(
                PROJECT_ROOT,
                structure_path,
                decoder=decode,
            )
        )
        unit_decisions, unit_corpus_report = load_full_unit_name_corpus(
            PROJECT_ROOT,
            unit_path,
            original_names.unit_entries,
        )
    except DisplayNameError as error:
        raise FullStoryComponentError(str(error)) from error
    speaker_document = json.loads(speaker_data.decode("utf-8"))
    speaker_entries = speaker_document.get("entries")
    if not isinstance(speaker_entries, list) or not speaker_entries:
        raise FullStoryComponentError("story speaker corpus has no entries")
    story_by_source: dict[str, str] = {}
    for entry in speaker_entries:
        if not isinstance(entry, dict):
            raise FullStoryComponentError("story speaker entry is malformed")
        source_hash = entry.get("source_text_sha256")
        translation = entry.get("translation")
        if (
            not isinstance(source_hash, str)
            or len(source_hash) != 64
            or not isinstance(translation, str)
        ):
            raise FullStoryComponentError("story speaker decision is invalid")
        if not translation:
            continue
        previous = story_by_source.setdefault(source_hash, translation)
        if previous != translation:
            raise FullStoryComponentError(
                f"conflicting story speaker translation: {source_hash}"
            )

    residual_document = json.loads(residual_data.decode("utf-8"))
    residual_by_text = residual_document.get("display_names_by_source_text")
    if (
        residual_document.get("editorial_status") != "reviewed"
        or not isinstance(residual_by_text, dict)
        or not residual_by_text
        or any(
            not isinstance(source, str)
            or not source
            or not isinstance(translation, str)
            or not translation
            for source, translation in residual_by_text.items()
        )
    ):
        raise FullStoryComponentError(
            "remaining display-name translations are invalid"
        )

    include_fields = reference.get("include_fields")
    if (
        not isinstance(include_fields, list)
        or not include_fields
        or any(field not in {"display", "family", "given"} for field in include_fields)
        or len(set(include_fields)) != len(include_fields)
    ):
        raise FullStoryComponentError("full pilot-name field selection is invalid")
    residual_by_source = {}
    residual_matched_texts = set()
    for entry in original_names.pilot_entries:
        if entry.field not in include_fields or entry.text not in residual_by_text:
            continue
        residual_matched_texts.add(entry.text)
        translation = residual_by_text[entry.text]
        previous = residual_by_source.setdefault(
            entry.source_text_sha256, translation
        )
        if previous != translation:
            raise FullStoryComponentError(
                f"conflicting residual pilot translation: {entry.text!r}"
            )
    if residual_matched_texts != set(residual_by_text):
        missing = sorted(set(residual_by_text) - residual_matched_texts)
        raise FullStoryComponentError(
            f"remaining display-name source coverage drift: {missing[:10]!r}"
        )
    if set(story_by_source) & set(residual_by_source):
        raise FullStoryComponentError(
            "story and remaining display-name selections overlap"
        )
    by_source = {**story_by_source, **residual_by_source}
    selected = [
        entry
        for entry in original_names.pilot_entries
        if (
            entry.field in include_fields
            and entry.text
            and entry.source_text_sha256 in by_source
        )
    ]
    field_counts = {}
    for entry in selected:
        field_counts[entry.field] = field_counts.get(entry.field, 0) + 1
    expected = reference.get("expected")
    if not isinstance(expected, dict) or (
        len(story_by_source) != expected.get("story_unique_source_count")
        or len(residual_by_text)
        != expected.get("residual_unique_source_count")
        or len(by_source) != expected.get("unique_source_count")
        or len(selected) != expected.get("selected_entry_count")
        or field_counts != expected.get("field_entry_counts")
        or len(unit_decisions) != expected.get("unit_name_entry_count")
    ):
        raise FullStoryComponentError("full display-name selection drift")

    decoded = workspace.view() if workspace is not None else decode(stored_compdata)
    if decoded.consumed != len(stored_compdata):
        raise FullStoryComponentError("base COMPDATA has trailing compressed bytes")
    table_path = _project_path(structure["text_table"]["path"])
    table = load_text_table(table_path)
    source_table = project_runtime_text_table(table, overrides)
    encoding_overrides = _stored_text_overrides(table, overrides)
    unit_space_code = table.inverse_characters.get("\u3000")
    if unit_space_code is None or unit_space_code < 0x8000:
        raise FullStoryComponentError(
            "unit-name two-byte space code is absent from the stock text table"
        )
    unit_space_payload = unit_space_code.to_bytes(2, "big")
    unit_encoding_overrides = dict(encoding_overrides)
    # The intermission unit-name renderer advances in two-byte glyph cells.
    # A raw 0x20 shifts every following Latin glyph by one byte, so retain an
    # ordinary space in the review corpus but store the stock two-byte space.
    unit_encoding_overrides[" "] = unit_space_code
    output_table = project_runtime_text_table(
        source_table, original_fullwidth_ascii_overrides(table)
    )
    try:
        current_names = parse_display_names(
            decoded.output,
            source_table,
            structure,
            verify_text_preimages=False,
        )
    except DisplayNameError as error:
        raise FullStoryComponentError(str(error)) from error
    current_by_id = {entry.entry_id: entry for entry in current_names.entries}
    output = bytearray(decoded.output)
    write_entry_count = 0
    no_op_entry_count = 0
    minimum_headroom = None
    changed_ids = []
    for original in selected:
        current = current_by_id.get(original.entry_id)
        if (
            current is None
            or current.target_offset != original.target_offset
            or current.capacity != original.capacity
        ):
            raise FullStoryComponentError(
                f"pilot-name structure drift: {original.entry_id}"
            )
        translation = normalize_original_fullwidth_ascii(
            by_source[original.source_text_sha256]
        )
        try:
            encoded = encode_text(
                translation,
                table,
                overrides=encoding_overrides,
                terminate=True,
            )
        except (SrwzTextEncodeError, ValueError) as error:
            raise FullStoryComponentError(
                f"pilot-name encoding failed: {original.entry_id}: {error}"
            ) from error
        if len(encoded) > original.capacity:
            raise FullStoryComponentError(
                f"pilot-name translation exceeds field: {original.entry_id}"
            )
        headroom = original.capacity - len(encoded)
        minimum_headroom = (
            headroom if minimum_headroom is None else min(minimum_headroom, headroom)
        )
        start = original.target_offset
        end = start + original.capacity
        replacement = encoded + bytes(headroom)
        if output[start:end] == replacement:
            no_op_entry_count += 1
        else:
            output[start:end] = replacement
            write_entry_count += 1
            changed_ids.append(original.entry_id)

    # Unit names share the same pointer-backed COMPDATA string pool.  Their
    # original allocation metadata records only the minimum aligned span of
    # the Japanese preimage, while some explicitly approved Latin names need
    # one additional zero-padded alignment block.  Permit that expansion only
    # inside an already-zero gap before the next validated unit-name target.
    # One explicitly configured in-slot relocation also frees the extra cell
    # needed by ``Drill Spazer`` without changing any unrelated target.
    unit_alignment = structure["unit_table"].get("target_alignment")
    if not isinstance(unit_alignment, int) or unit_alignment <= 0:
        raise FullStoryComponentError("unit-name target alignment is invalid")
    unit_regions = [
        (
            int(str(region["start"]), 0),
            int(str(region["end"]), 0),
        )
        for region in structure["unit_table"].get("allowed_target_regions", [])
    ]
    raw_unit_relocations = reference.get("unit_name_relocations", [])
    if not isinstance(raw_unit_relocations, list):
        raise FullStoryComponentError("unit-name relocations must be an array")
    unit_relocations = {}
    for item in raw_unit_relocations:
        if not isinstance(item, dict):
            raise FullStoryComponentError("unit-name relocation is malformed")
        entry_id = item.get("entry_id")
        if not isinstance(entry_id, str) or entry_id in unit_relocations:
            raise FullStoryComponentError(
                "unit-name relocation ID is missing or duplicated"
            )
        try:
            source_target = int(str(item.get("source_target_offset")), 0)
            target = int(str(item.get("target_offset")), 0)
        except (TypeError, ValueError) as error:
            raise FullStoryComponentError(
                f"unit-name relocation offsets are invalid: {entry_id}"
            ) from error
        unit_relocations[entry_id] = {
            "source_target_offset": source_target,
            "target_offset": target,
            "reason": item.get("reason"),
        }
    original_unit_by_id = {
        entry.entry_id: entry for entry in original_names.unit_entries
    }
    effective_unit_targets = {
        entry.entry_id: entry.target_offset
        for entry in original_names.unit_entries
    }
    for entry_id, relocation in unit_relocations.items():
        original = original_unit_by_id.get(entry_id)
        if (
            original is None
            or original.target_offset != relocation["source_target_offset"]
            or relocation["target_offset"] % unit_alignment
        ):
            raise FullStoryComponentError(
                f"unit-name relocation source or alignment drift: {entry_id}"
            )
        effective_unit_targets[entry_id] = relocation["target_offset"]
    if len(set(effective_unit_targets.values())) != len(effective_unit_targets):
        raise FullStoryComponentError("unit-name relocations overlap a target")
    ordered_units = sorted(
        original_names.unit_entries,
        key=lambda entry: effective_unit_targets[entry.entry_id],
    )
    unit_max_spans = {}
    for index, entry in enumerate(ordered_units):
        effective_target = effective_unit_targets[entry.entry_id]
        region_end = next(
            (
                end
                for start, end in unit_regions
                if start <= effective_target < end
            ),
            None,
        )
        if region_end is None:
            raise FullStoryComponentError(
                f"unit-name target leaves configured regions: {entry.entry_id}"
            )
        next_target = (
            effective_unit_targets[ordered_units[index + 1].entry_id]
            if index + 1 < len(ordered_units)
            and effective_unit_targets[ordered_units[index + 1].entry_id]
            < region_end
            else region_end
        )
        unit_max_spans[entry.entry_id] = next_target - effective_target
        if unit_max_spans[entry.entry_id] <= 0:
            raise FullStoryComponentError(
                f"unit-name relocation order overlaps: {entry.entry_id}"
            )

    # Clear only the original allocations of the explicitly relocated names.
    # The configured target then reuses the aligned tail of the same slot,
    # while the preceding name may consume the released aligned cell.
    for entry_id, relocation in unit_relocations.items():
        original = original_unit_by_id[entry_id]
        current = current_by_id[entry_id]
        old_start = relocation["source_target_offset"]
        old_end = old_start + original.capacity
        target = relocation["target_offset"]
        if (
            current.target_offset != old_start
            or not old_start < target < old_end
        ):
            raise FullStoryComponentError(
                f"unit-name relocation does not stay inside its source slot: {entry_id}"
            )
        output[old_start:old_end] = bytes(old_end - old_start)

    unit_write_entry_count = 0
    unit_no_op_entry_count = 0
    unit_minimum_headroom = None
    unit_changed_ids = []
    unit_expanded_ids = []
    unit_write_spans = {}
    unit_two_byte_space_ids = []
    for original in original_names.unit_entries:
        current = current_by_id.get(original.entry_id)
        decision = unit_decisions.get(original.entry_id)
        if (
            current is None
            or decision is None
            or current.target_offset != original.target_offset
            or current.pointer_offsets != original.pointer_offsets
        ):
            raise FullStoryComponentError(
                f"unit-name structure drift: {original.entry_id}"
            )
        translation = normalize_original_fullwidth_ascii(
            decision["translation"]
        )
        try:
            encoded = encode_text(
                translation,
                table,
                overrides=unit_encoding_overrides,
                terminate=True,
            )
        except (SrwzTextEncodeError, ValueError) as error:
            raise FullStoryComponentError(
                f"unit-name encoding failed: {original.entry_id}: {error}"
            ) from error
        if " " in translation:
            payload = encoded[:-1]
            if (
                b"\x20" in payload
                or payload.count(unit_space_payload) != translation.count(" ")
            ):
                raise FullStoryComponentError(
                    "unit-name space is not stored as one two-byte glyph per "
                    f"separator: {original.entry_id}"
                )
            unit_two_byte_space_ids.append(original.entry_id)
        required_span = (
            (len(encoded) + unit_alignment - 1) // unit_alignment
        ) * unit_alignment
        maximum_span = unit_max_spans[original.entry_id]
        relocated = original.entry_id in unit_relocations
        owned_span = (
            required_span
            if relocated
            else max(current.capacity, required_span)
        )
        if required_span > maximum_span or owned_span > maximum_span:
            raise FullStoryComponentError(
                f"unit-name translation exceeds allocation: {original.entry_id}"
            )
        start = effective_unit_targets[original.entry_id]
        end = start + owned_span
        zero_extension_start = start + current.capacity
        if (
            owned_span > current.capacity
            and any(output[zero_extension_start:end])
        ):
            raise FullStoryComponentError(
                f"unit-name expansion consumes nonzero bytes: {original.entry_id}"
            )
        replacement = encoded + bytes(owned_span - len(encoded))
        if output[start:end] == replacement:
            unit_no_op_entry_count += 1
        else:
            output[start:end] = replacement
            unit_write_entry_count += 1
            unit_changed_ids.append(original.entry_id)
        if required_span > original.capacity:
            unit_expanded_ids.append(original.entry_id)
        unit_write_spans[original.entry_id] = owned_span
        headroom = maximum_span - len(encoded)
        unit_minimum_headroom = (
            headroom
            if unit_minimum_headroom is None
            else min(unit_minimum_headroom, headroom)
        )

    pointer_base_address = int(
        str(structure["unit_table"]["pointer_base_address"]), 0
    )
    relocated_pointer_count = 0
    for entry_id, relocation in unit_relocations.items():
        current = current_by_id[entry_id]
        target = relocation["target_offset"]
        pointer_payload = struct.pack("<I", pointer_base_address + target)
        for pointer_offset in current.pointer_offsets:
            output[pointer_offset : pointer_offset + 4] = pointer_payload
            relocated_pointer_count += 1

    try:
        pre_alias_names = parse_display_names(
            bytes(output),
            output_table,
            structure,
            verify_text_preimages=False,
        )
    except DisplayNameError as error:
        raise FullStoryComponentError(str(error)) from error
    menu_surface_aliases = dict(surface_aliases)
    reused_source_characters = set(
        surface_alias_report.get("source_glyph_reuse_characters", "")
    )
    alias_encoding_overrides = _stored_text_overrides(
        table, overrides, menu_surface_aliases
    )
    alias_output_table = project_runtime_text_table(
        project_runtime_text_table(source_table, menu_surface_aliases),
        original_fullwidth_ascii_overrides(table),
    )
    alias_entries = [
        entry
        for entry in pre_alias_names.entries
        if entry.text
        and any(
            character in menu_surface_aliases
            or character in reused_source_characters
            for character in entry.text
        )
    ]
    alias_entry_ids = []
    alias_field_counts = {}
    alias_character_occurrences = 0
    alias_payload_size_changed_count = 0
    for entry in alias_entries:
        try:
            encoded = encode_text(
                entry.text,
                table,
                overrides=alias_encoding_overrides,
                terminate=True,
            )
        except (SrwzTextEncodeError, ValueError) as error:
            raise FullStoryComponentError(
                f"surface-safe display-name encoding failed: {entry.entry_id}: "
                f"{error}"
            ) from error
        if len(encoded) > entry.capacity:
            raise FullStoryComponentError(
                "surface-safe display-name overflow: "
                f"{entry.entry_id}: text={entry.text!r} "
                f"encoded={len(encoded)} source={entry.encoded_size} "
                f"capacity={entry.capacity}"
            )
        if len(encoded) != entry.encoded_size:
            alias_payload_size_changed_count += 1
        start = entry.target_offset
        end = start + entry.capacity
        replacement = encoded + bytes(entry.capacity - len(encoded))
        if output[start:end] != replacement:
            output[start:end] = replacement
            alias_entry_ids.append(entry.entry_id)
        alias_field_counts[entry.table] = alias_field_counts.get(entry.table, 0) + 1
        alias_character_occurrences += sum(
            character in surface_aliases for character in entry.text
        )
    try:
        reread = parse_display_names(
            bytes(output),
            alias_output_table,
            structure,
            verify_text_preimages=False,
        )
    except DisplayNameError as error:
        raise FullStoryComponentError(str(error)) from error
    if (
        reread.unit_pointer_bytes_sha256
        != pre_alias_names.unit_pointer_bytes_sha256
        or reread.pilot_id_bytes_sha256
        != pre_alias_names.pilot_id_bytes_sha256
    ):
        raise FullStoryComponentError(
            "surface-safe display-name aliases changed IDs or pointers"
        )
    pre_alias_by_id = {
        entry.entry_id: entry for entry in pre_alias_names.entries
    }
    reread_all_by_id = {entry.entry_id: entry for entry in reread.entries}
    for entry in alias_entries:
        reread_entry = reread_all_by_id.get(entry.entry_id)
        if (
            reread_entry is None
            or reread_entry.text != pre_alias_by_id[entry.entry_id].text
        ):
            raise FullStoryComponentError(
                "surface-safe display-name reread mismatch: "
                f"{entry.entry_id}: expected={pre_alias_by_id[entry.entry_id].text!r} "
                f"actual={None if reread_entry is None else reread_entry.text!r}"
            )
    reread_by_id = {entry.entry_id: entry for entry in reread.entries}
    for original in selected:
        if (
            reread_by_id[original.entry_id].text
            != by_source[original.source_text_sha256]
        ):
            raise FullStoryComponentError(
                f"pilot-name readback mismatch: {original.entry_id}"
            )
    for original in original_names.unit_entries:
        if (
            reread_by_id[original.entry_id].text.replace("\u3000", " ")
            != normalize_original_fullwidth_ascii(
                unit_decisions[original.entry_id]["translation"]
            )
        ):
            raise FullStoryComponentError(
                f"unit-name readback mismatch: {original.entry_id}"
            )

    codec = reference.get("codec")
    rebuilt = _commit_compdata_stage(
        stored_compdata,
        bytes(output),
        decoded,
        codec,
        label="full pilot-name COMPDATA",
        workspace=workspace,
    )
    changed_offsets = [
        offset
        for offset, (before, after) in enumerate(zip(decoded.output, output))
        if before != after
    ]
    allowed_offsets = {
        offset
        for entry in selected
        for offset in range(
            entry.target_offset,
            entry.target_offset + entry.capacity,
        )
    }
    allowed_offsets.update(
        offset
        for entry in alias_entries
        for offset in range(
            entry.target_offset,
            entry.target_offset + entry.capacity,
        )
    )
    allowed_offsets.update(
        offset
        for entry in original_names.unit_entries
        for offset in range(
            effective_unit_targets[entry.entry_id],
            effective_unit_targets[entry.entry_id]
            + unit_write_spans[entry.entry_id],
        )
    )
    allowed_offsets.update(
        offset
        for entry_id in unit_relocations
        for pointer_offset in current_by_id[entry_id].pointer_offsets
        for offset in range(pointer_offset, pointer_offset + 4)
    )
    if any(offset not in allowed_offsets for offset in changed_offsets):
        raise FullStoryComponentError("display-name write escaped selected fields")
    return rebuilt, {
        "story_unique_source_count": len(story_by_source),
        "residual_unique_source_count": len(residual_by_text),
        "unique_source_count": len(by_source),
        "included_fields": include_fields,
        "selected_entry_count": len(selected),
        "field_entry_counts": field_counts,
        "write_entry_count": write_entry_count,
        "no_op_entry_count": no_op_entry_count,
        "minimum_output_headroom": minimum_headroom,
        "changed_byte_count": len(changed_offsets),
        "changed_entry_ids_sha256": sha256_bytes(
            json.dumps(changed_ids, separators=(",", ":")).encode("utf-8")
        ),
        "unit_names": {
            "corpus_batch_id": unit_corpus_report["batch_id"],
            "entry_count": len(unit_decisions),
            "write_entry_count": unit_write_entry_count,
            "no_op_entry_count": unit_no_op_entry_count,
            "minimum_writable_headroom": unit_minimum_headroom,
            "expanded_zero_padding_entry_count": len(unit_expanded_ids),
            "expanded_zero_padding_entry_ids": unit_expanded_ids,
            "changed_entry_ids_sha256": sha256_bytes(
                json.dumps(
                    unit_changed_ids,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            "relocated_entry_count": len(unit_relocations),
            "relocated_entry_ids": list(unit_relocations),
            "relocated_pointer_count": relocated_pointer_count,
            "pointer_bytes_unchanged": not unit_relocations,
            "pointer_relocations_exact": True,
            "following_targets_unchanged": True,
            "two_byte_space_code": f"{unit_space_code:04x}",
            "two_byte_space_entry_count": len(unit_two_byte_space_ids),
            "two_byte_space_entry_ids": unit_two_byte_space_ids,
            "raw_single_byte_space_count": 0,
            "two_byte_spaces_exact": True,
            "reread_exact": True,
        },
        "source_compressed_size": len(stored_compdata),
        "output_compressed_size": (
            None if workspace is not None else len(rebuilt)
        ),
        "compressed_sector_budget": codec["max_output_size"],
        "codec": {
            "strategy": codec["strategy"],
            "min_match_length": codec["min_match_length"],
            "max_match_chain": codec["max_match_chain"],
            "lazy_matching": codec["lazy_matching"],
        },
        "codec_round_trip_exact": workspace is None,
        "compression_deferred_to_workspace": workspace is not None,
        "reread_exact": True,
        "changed_bytes_confined_to_selected_fields": True,
        "surface_safe_aliases": {
            "surface_id": surface_alias_report["surface_id"],
            "assignment_count": len(surface_aliases),
            "menu_applicable_assignment_count": len(menu_surface_aliases),
            "eligible_entry_count": len(alias_entries),
            "rewritten_entry_count": len(alias_entry_ids),
            "entry_table_counts": alias_field_counts,
            "character_occurrence_count": alias_character_occurrences,
            "rewritten_entry_ids_sha256": sha256_bytes(
                json.dumps(alias_entry_ids, separators=(",", ":")).encode(
                    "utf-8"
                )
            ),
            "payload_size_changed_entry_count": (
                alias_payload_size_changed_count
            ),
            "fixed_field_capacities_preserved": True,
            "primary_codes_preserved": True,
            "alias_codes_outside_conditional_range": True,
            "pointer_bytes_unchanged": True,
            "reread_exact": True,
        },
    }, structure_path, speaker_path, residual_path, unit_path, proposal_path


def _apply_full_stage_title_graphics(
    slps: bytes,
    vt1: bytes,
    stage_entries: list[dict],
    decoded_compdata: bytes,
    parsed_compdata,
    final_font: bytes,
    release_by_character: dict,
    raw_config: object,
) -> tuple[bytes, dict]:
    """Replace the 107 playable stage-title textures inside VT1 chunk 8."""

    if not isinstance(raw_config, dict):
        raise FullStoryComponentError(
            "full stage-title graphic configuration is invalid"
        )
    archive = raw_config.get("archive")
    mapping = raw_config.get("mapping")
    tim2 = raw_config.get("tim2")
    raster_config = raw_config.get("raster")
    codec = raw_config.get("codec")
    expected = raw_config.get("expected")
    if not all(
        isinstance(value, dict)
        for value in (archive, mapping, tim2, raster_config, codec, expected)
    ):
        raise FullStoryComponentError(
            "full stage-title graphic contract is incomplete"
        )
    try:
        group_index = archive["vt1_group_index"]
        group_start_lock = archive["group_start"]
        group_end_lock = archive["group_end"]
        group_sha256_lock = archive["group_sha256"]
        table_start = int(archive["offset_table_start"], 0)
        table_count = archive["offset_count"]
        table_sha256_lock = archive["offset_table_sha256"]
        texture_entry_count = mapping["texture_entry_count"]
        selector_bias = mapping["selector_bias"]
        loader_table_bias = mapping["loader_table_bias"]
        scenario_records = mapping["scenario_records"]
        text_only_entry_ordinals = mapping["text_only_entry_ordinals"]
        route_choice_entry_ordinals = mapping[
            "route_choice_entry_ordinals"
        ]
        internal_entry_ordinals = mapping["internal_entry_ordinals"]
        decoded_size = tim2["decoded_size"]
        record_offset = tim2["record_offset"]
        record_size = tim2["record_size"]
        doubled_glyph_width = raster_config["doubled_glyph_width"]
        advance = raster_config["advance"]
        raster_y = raster_config["y"]
        quantization_levels = raster_config["quantization_levels"]
        codec_strategy = codec["strategy"]
        codec_min_match_length = codec["min_match_length"]
        codec_max_match_chain = codec["max_match_chain"]
    except (KeyError, TypeError, ValueError) as error:
        raise FullStoryComponentError(
            "full stage-title graphic values are malformed"
        ) from error
    if (
        archive.get("member") != "DATA/VT1.BIN"
        or not isinstance(group_index, int)
        or not isinstance(group_start_lock, int)
        or not isinstance(group_end_lock, int)
        or not isinstance(group_sha256_lock, str)
        or not isinstance(table_count, int)
        or not isinstance(table_sha256_lock, str)
        or texture_entry_count != 107
        or selector_bias != 1
        or loader_table_bias != 8
        or table_count != texture_entry_count + loader_table_bias + 2
        or not isinstance(scenario_records, dict)
        or text_only_entry_ordinals != list(range(107, 122))
        or route_choice_entry_ordinals != list(range(107, 116))
        or internal_entry_ordinals != list(range(116, 122))
        or expected.get("stage_name_entry_count") != 122
        or expected.get("text_only_entry_count") != 15
        or decoded_size != 0x40E0
        or record_offset != 0x20
        or record_size != 0x40C0
        or tim2.get("width") != STAGE_TITLE_WIDTH
        or tim2.get("height") != STAGE_TITLE_HEIGHT
        or tim2.get("image_size") != STAGE_TITLE_IMAGE_SIZE
        or tim2.get("image_type") != 4
        or tim2.get("clut_color_count") != 32
        or tim2.get("storage") != "linear_low_nibble_first_4bpp"
        or doubled_glyph_width != 48
        or advance != 50
        or raster_y != 4
        or not isinstance(quantization_levels, list)
        or quantization_levels != [16, 8]
        or codec_strategy != "rust-fit"
        or codec_min_match_length != 2
        or not isinstance(codec_max_match_chain, int)
        or codec_max_match_chain <= 0
    ):
        raise FullStoryComponentError(
            "full stage-title graphic policy drift"
        )

    try:
        record_base_address = int(scenario_records["base_address"], 0)
        record_start_address = int(scenario_records["start_address"], 0)
        record_count = scenario_records["record_count"]
        record_stride = scenario_records["record_stride"]
        title_pointer_offset = scenario_records["title_pointer_offset"]
        graphic_selector_offset = scenario_records[
            "graphic_selector_offset"
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise FullStoryComponentError(
            "stage-title scenario record contract is malformed"
        ) from error
    record_start = record_start_address - record_base_address
    record_end = record_start + record_count * record_stride
    if (
        record_base_address != 0x6D6800
        or record_start_address != 0x734950
        or record_count != 204
        or record_stride != 48
        or title_pointer_offset != 0
        or graphic_selector_offset != 0x1C
        or not 0 <= record_start < record_end <= len(decoded_compdata)
    ):
        raise FullStoryComponentError(
            "stage-title scenario record policy drift"
        )

    stage_menu_entries = sorted(
        (
            item
            for item in parsed_compdata.entries
            if item.section == "Stage Name"
        ),
        key=lambda item: item.ordinal,
    )
    if (
        len(stage_menu_entries) != len(stage_entries)
        or any(
            item.entry_id != entry["id"]
            for item, entry in zip(stage_menu_entries, stage_entries)
        )
    ):
        raise FullStoryComponentError(
            "stage-title menu entry mapping drift"
        )
    selectors_by_target: dict[int, set[int]] = {}
    record_target_offsets = []
    for record_index in range(record_count):
        scenario_record_offset = record_start + record_index * record_stride
        pointer = struct.unpack_from(
            "<I",
            decoded_compdata,
            scenario_record_offset + title_pointer_offset,
        )[0]
        selector = struct.unpack_from(
            "<h",
            decoded_compdata,
            scenario_record_offset + graphic_selector_offset,
        )[0]
        target_offset = pointer - record_base_address
        if not 0 <= target_offset < len(decoded_compdata):
            raise FullStoryComponentError(
                f"stage-title record pointer is outside COMPDATA: {record_index}"
            )
        selectors_by_target.setdefault(target_offset, set()).add(selector)
        record_target_offsets.append(target_offset)

    selector_sets = []
    for ordinal, item in enumerate(stage_menu_entries):
        selectors = sorted(
            {
                selector
                for target_offset in item.target_offsets
                for selector in selectors_by_target.get(target_offset, set())
            }
        )
        if not selectors:
            raise FullStoryComponentError(
                f"stage-title scenario record is missing: {ordinal}"
            )
        selector_sets.append(selectors)

    graphic_mappings = []
    for ordinal in range(texture_entry_count):
        expected_selector = ordinal + selector_bias
        if selector_sets[ordinal] != [expected_selector]:
            raise FullStoryComponentError(
                f"stage-title selector mapping drift: {ordinal} -> "
                f"{selector_sets[ordinal]}"
            )
        graphic_mappings.append(
            (ordinal, stage_entries[ordinal], expected_selector)
        )
    if [item[2] for item in graphic_mappings] != list(range(1, 108)):
        raise FullStoryComponentError(
            "stage-title graphic selectors are not complete"
        )
    text_only_reports = []
    for ordinal in text_only_entry_ordinals:
        classification = (
            "route_choice_dynamic_text"
            if ordinal in route_choice_entry_ordinals
            else "internal_or_debug_dynamic_text"
        )
        text_only_reports.append(
            {
                "ordinal": ordinal,
                "entry_id": stage_entries[ordinal]["id"],
                "text": stage_entries[ordinal]["translation"],
                "selectors": selector_sets[ordinal],
                "classification": classification,
                "owns_stage_entry_texture": False,
            }
        )

    vt1_offsets = read_executable_archive_offsets(
        slps,
        CORE_ARCHIVE_SPECS["VT1.BIN"],
        len(vt1),
    )
    if not 0 <= group_index < len(vt1_offsets) - 1:
        raise FullStoryComponentError("stage-title VT1 group is missing")
    group_start = vt1_offsets[group_index]
    group_end = vt1_offsets[group_index + 1]
    source_group = vt1[group_start:group_end]
    if (
        group_start != group_start_lock
        or group_end != group_end_lock
        or sha256_bytes(source_group) != group_sha256_lock
    ):
        raise FullStoryComponentError("stage-title VT1 group lock drift")

    table_end = table_start + table_count * 4
    if not 0 <= table_start < table_end <= len(slps):
        raise FullStoryComponentError(
            "stage-title internal offset table is outside SLPS"
        )
    table_bytes = slps[table_start:table_end]
    if sha256_bytes(table_bytes) != table_sha256_lock:
        raise FullStoryComponentError("stage-title offset-table lock drift")
    offsets = tuple(
        int.from_bytes(table_bytes[position : position + 4], "little")
        for position in range(0, len(table_bytes), 4)
    )
    if (
        offsets[0] != 0
        or offsets[-1] != len(source_group)
        or any(
            current >= following
            for current, following in zip(offsets, offsets[1:])
        )
    ):
        raise FullStoryComponentError(
            "stage-title internal offsets are invalid"
        )

    selected_entries = stage_entries[:texture_entry_count]
    if len(selected_entries) != texture_entry_count:
        raise FullStoryComponentError("stage-title texture corpus is incomplete")
    for ordinal, entry in enumerate(selected_entries):
        if entry["id"] != f"menu/Compdata/03/{ordinal:04d}":
            raise FullStoryComponentError(
                "stage-title texture ordinal mapping drift"
            )

    needed_characters = sorted(
        set("".join(entry["translation"] for entry in selected_entries))
    )
    glyphs = {}
    for character in needed_characters:
        if character == " ":
            glyph = bytes(STAGE_TITLE_GLYPH_SIZE)
            glyph_index = None
        elif " " <= character <= "~":
            glyph_index = ascii_glyph_index(ord(character))
            glyph = decode_glyph(final_font, glyph_index)
        else:
            release_mapping = release_by_character.get(character)
            if (
                not isinstance(release_mapping, tuple)
                or len(release_mapping) != 2
                or not isinstance(release_mapping[1], int)
            ):
                raise FullStoryComponentError(
                    f"stage-title release glyph is missing: {character!r}"
                )
            glyph_index = release_mapping[1]
            glyph = decode_glyph(final_font, glyph_index)
        if len(glyph) != STAGE_TITLE_GLYPH_SIZE:
            raise FullStoryComponentError(
                f"stage-title glyph geometry drift: {character!r}"
            )
        glyphs[character] = glyph

    output = bytearray(vt1)
    title_reports = []
    for ordinal, entry, selector in graphic_mappings:
        table_index = selector + loader_table_bias
        relative_start = offsets[table_index]
        relative_end = offsets[table_index + 1]
        stored_start = group_start + relative_start
        stored_end = group_start + relative_end
        stored = vt1[stored_start:stored_end]
        source_decoded = decode(stored)
        if (
            len(source_decoded.output) != decoded_size
            or any(stored[source_decoded.consumed :])
        ):
            raise FullStoryComponentError(
                f"stage-title source stream drift: {ordinal}"
            )
        records = scan_tim2(source_decoded.output)
        if len(records) != 1:
            raise FullStoryComponentError(
                f"stage-title TIM2 count drift: {ordinal}"
            )
        record = records[0]
        if (
            record.offset != record_offset
            or record.size != record_size
            or len(record.pictures) != 1
        ):
            raise FullStoryComponentError(
                f"stage-title TIM2 record drift: {ordinal}"
            )
        picture = record.pictures[0]
        if (
            picture.width != STAGE_TITLE_WIDTH
            or picture.height != STAGE_TITLE_HEIGHT
            or picture.image_size != STAGE_TITLE_IMAGE_SIZE
            or picture.image_type != tim2["image_type"]
            or picture.clut_color_count != tim2["clut_color_count"]
            or picture.uses_shared_clut
        ):
            raise FullStoryComponentError(
                f"stage-title picture layout drift: {ordinal}"
            )
        image_start = picture.offset + picture.header_size
        image_end = image_start + picture.image_size
        source_indexes = unpack_linear_4bpp(
            source_decoded.output[image_start:image_end]
        )
        if not any(source_indexes):
            raise FullStoryComponentError(
                f"stage-title source picture is blank: {ordinal}"
            )

        selected = None
        attempted_sizes = []
        for levels in quantization_levels:
            raster = render_stage_title(
                entry["translation"],
                glyphs,
                doubled_glyph_width=doubled_glyph_width,
                advance=advance,
                y=raster_y,
                quantization_levels=levels,
            )
            packed = pack_linear_4bpp(raster.indexes)
            modified_decoded = (
                source_decoded.output[:image_start]
                + packed
                + source_decoded.output[image_end:]
            )
            encoded = encode(
                modified_decoded,
                strategy=codec_strategy,
                flags=source_decoded.flags,
                header_unknown_0=source_decoded.metadata.get(
                    "header_unknown_0"
                ),
                header_unknown_1=source_decoded.metadata["header_unknown_1"],
                min_match_length=codec_min_match_length,
                max_match_chain=codec_max_match_chain,
            )
            attempted_sizes.append(
                {"quantization_levels": levels, "encoded_size": len(encoded)}
            )
            if len(encoded) <= len(stored):
                selected = (levels, raster, modified_decoded, encoded)
                break
        if selected is None:
            raise FullStoryComponentError(
                f"stage-title stream does not fit slot {ordinal}: "
                f"{attempted_sizes} > {len(stored)}"
            )
        levels, raster, modified_decoded, encoded = selected
        if (
            modified_decoded[:image_start]
            != source_decoded.output[:image_start]
            or modified_decoded[image_end:]
            != source_decoded.output[image_end:]
        ):
            raise FullStoryComponentError(
                f"stage-title non-image bytes changed: {ordinal}"
            )
        padded = encoded + bytes(len(stored) - len(encoded))
        output[stored_start:stored_end] = padded
        reread = decode(output[stored_start:stored_end])
        reread_records = scan_tim2(reread.output)
        reread_picture = reread_records[0].pictures[0]
        reread_image_start = reread_picture.offset + reread_picture.header_size
        reread_image_end = reread_image_start + reread_picture.image_size
        reread_indexes = unpack_linear_4bpp(
            reread.output[reread_image_start:reread_image_end]
        )
        if (
            reread.output != modified_decoded
            or reread_indexes != raster.indexes
            or any(output[stored_start + reread.consumed : stored_end])
        ):
            raise FullStoryComponentError(
                f"stage-title VT1 reread failed: {ordinal}"
            )
        title_reports.append(
            {
                "ordinal": ordinal,
                "entry_id": entry["id"],
                "text": entry["translation"],
                "selector": selector,
                "loader_table_index": table_index,
                "stored_start": stored_start,
                "stored_end": stored_end,
                "stored_size": len(stored),
                "source_consumed": source_decoded.consumed,
                "output_encoded_size": len(encoded),
                "padding_size": len(stored) - len(encoded),
                "quantization_levels": levels,
                "attempted_sizes": attempted_sizes,
                "raster_x": raster.x,
                "raster_y": raster.y,
                "raster_width": raster.width,
                "raster_height": raster.height,
                "natural_width": raster.natural_width,
                "source_indexes_sha256": sha256_bytes(source_indexes),
                "output_indexes_sha256": sha256_bytes(raster.indexes),
            }
        )

    output_bytes = bytes(output)
    first_title_start = group_start + offsets[loader_table_bias + selector_bias]
    if (
        len(output_bytes) != len(vt1)
        or output_bytes[:first_title_start] != vt1[:first_title_start]
        or output_bytes[group_end:] != vt1[group_end:]
        or read_executable_archive_offsets(
            slps,
            CORE_ARCHIVE_SPECS["VT1.BIN"],
            len(output_bytes),
        )
        != vt1_offsets
    ):
        raise FullStoryComponentError(
            "stage-title VT1 archive boundary preservation failed"
        )

    reduced_ordinals = [
        item["ordinal"]
        for item in title_reports
        if item["quantization_levels"] < 16
    ]
    if (
        len(title_reports) != expected.get("texture_entry_count")
        or sum(item["quantization_levels"] == 16 for item in title_reports)
        != expected.get("full_precision_count")
        or reduced_ordinals != expected.get("reduced_precision_ordinals")
    ):
        raise FullStoryComponentError(
            "stage-title graphic output expectation drift"
        )
    stage_37 = title_reports[71]
    stage_38 = title_reports[72]
    if (
        stage_37["text"] != "肃清风暴"
        or stage_37["selector"] != 72
        or stage_37["loader_table_index"] != 80
        or stage_38["text"] != "被安排的决战"
        or stage_38["selector"] != 73
        or stage_38["loader_table_index"] != 81
    ):
        raise FullStoryComponentError(
            "stage 37/38 title graphic mapping drift"
        )
    return output_bytes, {
        "member": archive["member"],
        "vt1_group_index": group_index,
        "group_start": group_start,
        "group_end": group_end,
        "group_size": group_end - group_start,
        "offset_table_start": table_start,
        "offset_count": len(offsets),
        "texture_entry_count": len(title_reports),
        "stage_name_entry_count": len(stage_entries),
        "scenario_record_count": record_count,
        "scenario_record_target_count": len(record_target_offsets),
        "text_only_entry_count": len(text_only_reports),
        "text_only_entries": text_only_reports,
        "all_stage_name_entries_accounted_for": (
            len(title_reports) + len(text_only_reports) == len(stage_entries)
        ),
        "full_precision_count": sum(
            item["quantization_levels"] == 16 for item in title_reports
        ),
        "reduced_precision_ordinals": reduced_ordinals,
        "raster_storage": tim2["storage"],
        "codec": dict(codec),
        "stage_37": stage_37,
        "stage_38": stage_38,
        "titles": title_reports,
        "archive_size_preserved": True,
        "top_level_offsets_preserved": True,
        "internal_offsets_preserved": True,
        "non_title_prefix_preserved_byte_exact": True,
        "tim2_metadata_and_clut_preserved": True,
        "translated_reread_exact": True,
    }


def _apply_full_stage_titles(
    slps: bytes,
    vt1: bytes,
    stored_compdata: bytes,
    reference: dict,
    font_manifest: dict,
    codec: dict,
    final_font: bytes,
    release_by_character: dict,
    *,
    workspace: CompressedStreamWorkspace | None = None,
) -> tuple[bytes, bytes, bytes, dict, tuple[Path, Path, Path]]:
    """Write every fixed-span stage title and the visible title quotes."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError("full stage-title configuration is invalid")
    stage_path, stage_bytes = _locked_file(
        reference.get("stage_names"), label="full stage-title corpus"
    )
    format_path, format_bytes = _locked_file(
        reference.get("title_format"), label="stage-title format corpus"
    )
    descriptor_path, descriptor_bytes = _locked_file(
        reference.get("menu_descriptor"), label="menu descriptor"
    )
    stage_document = json.loads(stage_bytes.decode("utf-8"))
    stage_entries = stage_document.get("entries")
    expected_stage_count = reference["stage_names"].get("expected_entry_count")
    if (
        not isinstance(stage_entries, list)
        or len(stage_entries) != expected_stage_count
        or any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("id"), str)
            or not isinstance(entry.get("translation"), str)
            for entry in stage_entries
        )
    ):
        raise FullStoryComponentError("full stage-title selection drift")
    stage_replacements = {
        entry["id"]: normalize_original_fullwidth_ascii(
            entry["translation"]
        )
        for entry in stage_entries
    }
    if len(stage_replacements) != len(stage_entries):
        raise FullStoryComponentError("full stage-title IDs are not unique")
    stored_stage_replacements = {
        entry_id: _two_byte_visible_spaces(translation)
        for entry_id, translation in stage_replacements.items()
    }

    format_document = json.loads(format_bytes.decode("utf-8"))
    format_id = reference["title_format"].get("entry_id")
    format_translation = normalize_original_fullwidth_ascii(
        reference["title_format"].get("translation")
    )
    format_entry = next(
        (
            entry
            for entry in format_document.get("entries", [])
            if isinstance(entry, dict) and entry.get("id") == format_id
        ),
        None,
    )
    if (
        format_entry is None
        or format_entry.get("translation") != format_translation
        or format_translation != '"%s"'
    ):
        raise FullStoryComponentError("stage-title quote format drift")

    descriptors = json.loads(descriptor_bytes.decode("utf-8"))
    if not isinstance(descriptors, list):
        raise FullStoryComponentError("menu descriptor root is invalid")
    descriptor_by_name = {
        descriptor.get("friendly_name"): descriptor
        for descriptor in descriptors
        if isinstance(descriptor, dict)
    }
    if not {"SLPS", "Compdata"} <= set(descriptor_by_name):
        raise FullStoryComponentError("stage-title menu descriptors are missing")

    _proposal_path, primary_overrides, surface_aliases, _alias_report = (
        _full_story_overrides(font_manifest)
    )
    encoding = reference.get("encoding")
    if not isinstance(encoding, dict) or (
        encoding.get("printable_ascii_passthrough") is not True
        or encoding.get("use_available_surface_safe_aliases") is not True
    ):
        raise FullStoryComponentError("stage-title encoding policy drift")
    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    title_overrides = _stored_text_overrides(
        table, primary_overrides, surface_aliases
    )
    title_overrides.update(
        {
            character: ord(character)
            for character in original_fullwidth_ascii_overrides(table)
            if character not in "12345"
        }
    )
    current_table = project_runtime_text_table(table, primary_overrides)
    current_table = project_runtime_text_table(
        current_table, surface_aliases
    )
    decoded = workspace.view() if workspace is not None else decode(stored_compdata)
    if decoded.consumed != len(stored_compdata):
        raise FullStoryComponentError(
            "stage-title COMPDATA has trailing compressed bytes"
        )
    parsed_compdata = parse_menu_file(
        decoded.output,
        descriptor_by_name["Compdata"],
        current_table,
    )
    parsed_slps = parse_menu_file(
        slps,
        descriptor_by_name["SLPS"],
        current_table,
    )
    try:
        compdata_write = replace_menu_texts_in_place(
            decoded.output,
            parsed_compdata,
            table,
            replacements=stored_stage_replacements,
            overrides=title_overrides,
            source_table=current_table,
            source_name="full-story stage titles",
        )
        slps_write = replace_menu_texts_in_place(
            slps,
            parsed_slps,
            table,
            replacements={format_id: format_translation},
            overrides=title_overrides,
            source_table=current_table,
            source_name="full-story stage-title quotes",
        )
    except (WritebackError, ValueError) as error:
        raise FullStoryComponentError(
            f"full stage-title write failed: {error}"
        ) from error

    rebuilt_compdata = _commit_compdata_stage(
        stored_compdata,
        compdata_write.data,
        decoded,
        codec,
        label="stage-title COMPDATA",
        workspace=workspace,
    )
    example_id = "menu/Compdata/03/0072"
    if stage_replacements.get(example_id) != "被安排的决战":
        raise FullStoryComponentError("stage 38 title decision drift")
    output_vt1, graphic_report = _apply_full_stage_title_graphics(
        slps_write.data,
        vt1,
        stage_entries,
        decoded.output,
        parsed_compdata,
        final_font,
        release_by_character,
        reference.get("graphics"),
    )
    return slps_write.data, output_vt1, rebuilt_compdata, {
        "stage_title_entry_count": len(stage_replacements),
        "title_format_entry_id": format_id,
        "title_format_translation": format_translation,
        "stage_38_title": stage_replacements[example_id],
        "fixed_spans_preserved": True,
        "pointer_bytes_unchanged": True,
        "printable_ascii_passthrough": True,
        "available_surface_safe_aliases_used": True,
        "compdata_source_size": len(stored_compdata),
        "compdata_output_size": (
            None if workspace is not None else len(rebuilt_compdata)
        ),
        "compdata_round_trip_exact": workspace is None,
        "compression_deferred_to_workspace": workspace is not None,
        "slps_size_preserved": len(slps_write.data) == len(slps),
        "graphics": graphic_report,
    }, (stage_path, format_path, descriptor_path)


def _apply_stage_overviews(
    stage: bytes,
    hb: bytes,
    reference: dict,
    font_manifest: dict,
    codec: dict,
    *,
    chunk_workspace: CompressedStreamWorkspace | None = None,
) -> tuple[bytes, dict, Path]:
    """Rewrite reviewed save/load overview strings in fixed STAGE chunk 0."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError("stage-overview configuration is invalid")
    corpus_path, corpus_bytes = _locked_file(
        reference.get("corpus"), label="stage-overview corpus"
    )
    corpus = json.loads(corpus_bytes.decode("utf-8"))
    entries = corpus.get("entries")
    policy = corpus.get("policy")
    expected = reference.get("expected")
    if (
        corpus.get("editorial_status") != "reviewed"
        or not isinstance(entries, list)
        or not isinstance(policy, dict)
        or policy.get("source_text_authority") != "original_disc_only"
        or policy.get("preserve_pointer_table") is not True
        or policy.get("preserve_fixed_allocations") is not True
        or policy.get("preserve_newline_counts") is not True
        or not isinstance(expected, dict)
        or len(entries) != expected.get("translated_entry_count")
        or [entry.get("id") for entry in entries]
        != expected.get("translated_entry_ids")
        or expected.get("chunk_index") != 0
    ):
        raise FullStoryComponentError("stage-overview corpus contract drift")

    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member="HEDBDY/HB.BIN",
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(hb, offset_spec, len(stage))
    if (
        len(offsets) != expected.get("offset_count")
        or offsets[0] != 0
        or offsets[-1] != len(stage)
    ):
        raise FullStoryComponentError("stage-overview HB/STAGE layout drift")
    chunk_end = offsets[1]
    stored = stage[:chunk_end]
    if len(stored) != expected.get("stored_chunk_size"):
        raise FullStoryComponentError("stage-overview chunk size drift")
    decoded = (
        chunk_workspace.view()
        if chunk_workspace is not None
        else decode(stored)
    )
    if (
        chunk_workspace is not None
        and stored[: decoded.consumed] != chunk_workspace.stored
    ):
        raise FullStoryComponentError("stage-overview workspace source drift")
    if any(stored[decoded.consumed:]):
        raise FullStoryComponentError("stage-overview chunk has nonzero padding")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    try:
        rewritten, overview_report = replace_stage_overviews_in_place(
            decoded.output,
            table,
            entries,
            encoding_overrides=encoding_overrides,
        )
    except ValueError as error:
        raise FullStoryComponentError(
            f"stage-overview write failed: {error}"
        ) from error
    if (
        overview_report["inventory_entry_count"]
        != expected.get("inventory_entry_count")
        or overview_report["translated_entry_count"]
        != expected.get("translated_entry_count")
        or overview_report["translated_entry_ids"]
        != expected.get("translated_entry_ids")
    ):
        raise FullStoryComponentError("stage-overview selection drift")
    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError("stage-overview codec policy is invalid")
    if chunk_workspace is not None:
        try:
            chunk_workspace.replace(rewritten, stage="stage overviews")
        except ValueError as error:
            raise FullStoryComponentError(str(error)) from error
        rebuilt = None
        rebuilt_stored = stored
        output = stage
    else:
        try:
            rebuilt = reencode_changed_suffix(
                stored[: decoded.consumed],
                rewritten,
                strategy=codec["strategy"],
                min_match_length=codec["min_match_length"],
                max_match_chain=codec["max_match_chain"],
                lazy_matching=codec["lazy_matching"],
                max_output_size=len(stored),
                original_result=decoded,
            )
        except (RuntimeError, ValueError) as error:
            raise FullStoryComponentError(
                f"stage-overview compression failed: {error}"
            ) from error
        round_trip = decode(rebuilt)
        if (
            round_trip.consumed != len(rebuilt)
            or round_trip.output != rewritten
            or round_trip.flags != decoded.flags
        ):
            raise FullStoryComponentError("stage-overview codec round-trip failed")
        rebuilt_stored = rebuilt + bytes(len(stored) - len(rebuilt))
        output = rebuilt_stored + stage[chunk_end:]
    if (
        len(output) != len(stage)
        or read_executable_archive_offsets(hb, offset_spec, len(output)) != offsets
        or output[chunk_end:] != stage[chunk_end:]
    ):
        raise FullStoryComponentError("stage-overview archive layout changed")
    overview_report.update(
        {
            "chunk_index": 0,
            "source_stored_size": len(stored),
            "source_encoded_size": decoded.consumed,
            "output_encoded_size": (
                None if rebuilt is None else len(rebuilt)
            ),
            "output_encoded_sha256": (
                None if rebuilt is None else sha256_bytes(rebuilt)
            ),
            "output_padding_size": (
                None if rebuilt is None else len(rebuilt_stored) - len(rebuilt)
            ),
            "codec_round_trip_exact": chunk_workspace is None,
            "compression_deferred_to_workspace": chunk_workspace is not None,
            "archive_size_preserved": True,
            "hb_offsets_preserved": True,
            "non_target_chunks_preserved_byte_exact": True,
        }
    )
    return output, overview_report, corpus_path


def _apply_stage_fixed_formation_names(
    stage: bytes,
    hb: bytes,
    reference: dict,
    translation_path: Path,
    font_manifest: dict,
    codec: dict,
) -> tuple[bytes, dict, Path]:
    """Rewrite the nine fixed default-squad names in STAGE chunk 101."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError("remaining UI configuration is invalid")
    original_stage_path, original_stage = _locked_file(
        reference.get("original_stage"), label="original STAGE"
    )
    translations = json.loads(translation_path.read_text(encoding="utf-8"))
    replacements = translations.get("stage_fixed_formation_by_offset")
    expected = reference.get("expected")
    if (
        not isinstance(expected, dict)
        or not isinstance(replacements, dict)
        or len(replacements)
        != expected.get("stage_fixed_formation_entry_count")
    ):
        raise FullStoryComponentError(
            "fixed formation-name selection drift"
        )
    chunk_index = expected.get("stage_fixed_formation_chunk_index")
    if not isinstance(chunk_index, int) or chunk_index < 0:
        raise FullStoryComponentError(
            "fixed formation-name chunk index is invalid"
        )
    if len(original_stage) != len(stage):
        raise FullStoryComponentError(
            "fixed formation-name STAGE size drift"
        )

    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member="HEDBDY/HB.BIN",
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(hb, offset_spec, len(stage))
    if chunk_index + 1 >= len(offsets):
        raise FullStoryComponentError(
            "fixed formation-name STAGE chunk is missing"
        )
    start, end = offsets[chunk_index : chunk_index + 2]
    stored = stage[start:end]
    original_stored = original_stage[start:end]
    current_decoded = decode(stored)
    original_decoded = decode(original_stored)
    if (
        any(stored[current_decoded.consumed :])
        or any(original_stored[original_decoded.consumed :])
        or len(current_decoded.output) != len(original_decoded.output)
    ):
        raise FullStoryComponentError(
            "fixed formation-name STAGE chunk decode drift"
        )

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    output_table = project_runtime_text_table(table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(table)
    )
    rewritten, fixed_report = _apply_fixed_span_translations(
        current_decoded.output,
        original_decoded.output,
        replacements,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="STAGE fixed formation names",
    )
    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError(
            "fixed formation-name codec policy is invalid"
        )
    try:
        rebuilt = reencode_changed_suffix(
            stored[: current_decoded.consumed],
            rewritten,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=len(stored),
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"fixed formation-name compression failed: {error}"
        ) from error
    round_trip = decode(rebuilt)
    if (
        round_trip.consumed != len(rebuilt)
        or round_trip.output != rewritten
        or round_trip.flags != current_decoded.flags
    ):
        raise FullStoryComponentError(
            "fixed formation-name codec round-trip failed"
        )
    rebuilt_stored = rebuilt + bytes(len(stored) - len(rebuilt))
    output = stage[:start] + rebuilt_stored + stage[end:]
    if (
        len(output) != len(stage)
        or read_executable_archive_offsets(hb, offset_spec, len(output))
        != offsets
        or output[:start] != stage[:start]
        or output[end:] != stage[end:]
    ):
        raise FullStoryComponentError(
            "fixed formation-name STAGE archive layout changed"
        )
    fixed_report.update(
        {
            "chunk_index": chunk_index,
            "source_text": "別働隊",
            "translation": "别动队",
            "source_stored_size": len(stored),
            "source_encoded_size": current_decoded.consumed,
            "output_encoded_size": len(rebuilt),
            "output_encoded_sha256": sha256_bytes(rebuilt),
            "output_padding_size": len(rebuilt_stored) - len(rebuilt),
            "codec_strategy": codec["strategy"],
            "codec_round_trip_exact": True,
            "archive_size_preserved": True,
            "hb_offsets_preserved": True,
            "non_target_chunks_preserved_byte_exact": True,
        }
    )
    return output, fixed_report, original_stage_path


def _apply_stage_default_formation_names(
    stage: bytes,
    hb: bytes,
    reference: dict,
    font_manifest: dict,
    codec: dict,
) -> tuple[bytes, dict, dict, Path, Path, Path]:
    """Rewrite only reviewed, fixed-position default formation names."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError("remaining UI configuration is invalid")
    original_stage_path, original_stage = _locked_file(
        reference.get("original_stage"), label="original STAGE"
    )
    _fixed_path, fixed_data = _locked_file(
        reference.get("translations"),
        label="remaining UI translations",
    )
    corpus_path, corpus_data = _locked_file(
        reference.get("stage_default_formations"),
        label="default formation-name corpus",
    )
    inventory_path, inventory_data = _locked_file(
        reference.get("stage_default_formation_inventory"),
        label="default formation-name position inventory",
    )
    document = json.loads(corpus_data.decode("utf-8"))
    inventory_document = json.loads(inventory_data.decode("utf-8"))
    fixed_document = json.loads(fixed_data.decode("utf-8"))
    translations_by_source = document.get("translations_by_source_text")
    expected = reference.get("expected")
    if (
        document.get("schema_version") != 1
        or document.get("language") != "zh-Hans"
        or document.get("editorial_status") != "reviewed"
        or document.get("policy", {}).get("source_text_authority")
        != "original_disc_only"
        or document.get("policy", {}).get("build_selection_authority")
        != "locked_occurrence_inventory"
        or not document.get("policy", {}).get(
            "scan_only_when_explicitly_refreezing"
        )
        or not document.get("policy", {}).get("require_locked_source_coverage")
        or not document.get("policy", {}).get("preserve_record_metadata")
        or not isinstance(translations_by_source, dict)
        or not translations_by_source
        or not isinstance(expected, dict)
        or len(original_stage) != len(stage)
    ):
        raise FullStoryComponentError("default formation-name corpus drift")

    offsets = read_executable_archive_offsets(
        hb, STAGE_OFFSET_SPEC, len(stage)
    )
    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    original_decoded_cache = {}
    try:
        groups = load_locked_stage_default_formations(
            original_stage,
            hb,
            table,
            inventory_document,
            decoded_cache=original_decoded_cache,
        )
    except ValueError as error:
        raise FullStoryComponentError(str(error)) from error
    locked_source_texts = {
        cell.source_text for group in groups for cell in group.cells
    }
    if set(translations_by_source) != locked_source_texts:
        missing = sorted(locked_source_texts - set(translations_by_source))
        extra = sorted(set(translations_by_source) - locked_source_texts)
        raise FullStoryComponentError(
            "default formation-name locked source coverage drift: "
            f"missing={missing!r} extra={extra!r}"
        )
    entry_count = sum(len(group.cells) for group in groups)
    stage_indices = {group.stage_index for group in groups}
    source_texts = {
        cell.source_text for group in groups for cell in group.cells
    }
    layout_counts = {
        layout: sum(group.layout == layout for group in groups)
        for layout in ("formation18+33+1", "record6+23", "slot32")
    }
    record_metadata_count = sum(
        len(group.cells) for group in groups if group.layout == "record6+23"
    )
    inventory_sha256 = formation_inventory_sha256(groups)
    if (
        len(groups) != expected.get("stage_default_formation_group_count")
        or entry_count
        != expected.get("stage_default_formation_entry_count")
        or len(stage_indices)
        != expected.get("stage_default_formation_stage_count")
        or len(source_texts)
        != expected.get("stage_default_formation_unique_source_count")
        or record_metadata_count
        != expected.get("stage_default_formation_record_metadata_count")
        or inventory_sha256
        != expected.get("stage_default_formation_inventory_sha256")
        or set(translations_by_source) != source_texts
        or len(translations_by_source) != len(source_texts)
        or any(
            not isinstance(source, str)
            or not source
            or not isinstance(translation, str)
            or not translation
            for source, translation in translations_by_source.items()
        )
    ):
        raise FullStoryComponentError("default formation-name inventory drift")

    fixed_stage_index = expected.get("stage_fixed_formation_chunk_index")
    raw_fixed_replacements = fixed_document.get(
        "stage_fixed_formation_by_offset"
    )
    if (
        not isinstance(fixed_stage_index, int)
        or fixed_stage_index < 0
        or not isinstance(raw_fixed_replacements, dict)
        or len(raw_fixed_replacements)
        != expected.get("stage_fixed_formation_entry_count")
    ):
        raise FullStoryComponentError("fixed formation-name fusion drift")
    try:
        fixed_replacements = {
            int(raw_offset, 16): normalize_original_fullwidth_ascii(translation)
            for raw_offset, translation in raw_fixed_replacements.items()
        }
    except (TypeError, ValueError) as error:
        raise FullStoryComponentError(
            "fixed formation-name fusion offsets are invalid"
        ) from error
    fixed_cells = {
        cell.offset: cell
        for group in groups
        if group.stage_index == fixed_stage_index
        for cell in group.cells
        if cell.offset in fixed_replacements
    }
    if (
        set(fixed_cells) != set(fixed_replacements)
        or any(cell.source_text != "別働隊" for cell in fixed_cells.values())
        or any(
            translation != normalize_original_fullwidth_ascii(
                translations_by_source["別働隊"]
            )
            for translation in fixed_replacements.values()
        )
    ):
        raise FullStoryComponentError(
            "fixed formation names are not covered by the locked default inventory"
        )

    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    text_encoder = PreparedTextEncoder(table, encoding_overrides)
    output_table = project_runtime_text_table(table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(table)
    )
    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError(
            "default formation-name codec policy is invalid"
        )

    groups_by_stage = {}
    for group in groups:
        groups_by_stage.setdefault(group.stage_index, []).append(group)

    output = bytearray(stage)
    chunk_reports = []
    minimum_headroom = None
    changed_byte_count = 0
    translations = set()
    fixed_changed_byte_count = 0
    fixed_write_entry_count = 0
    fixed_no_op_entry_count = 0
    fixed_minimum_headroom = None
    fixed_chunk_report = None
    compression_executor = ThreadPoolExecutor(
        max_workers=min(4, len(groups_by_stage)),
        thread_name_prefix="srwz-formation",
    )
    pending_chunks = []
    for stage_index, stage_groups in sorted(groups_by_stage.items()):
        if stage_index + 1 >= len(offsets):
            raise FullStoryComponentError(
                f"default formation-name STAGE chunk is missing: {stage_index}"
            )
        start, end = offsets[stage_index : stage_index + 2]
        stored = bytes(output[start:end])
        original_stored = original_stage[start:end]
        current_decoded = decode(stored)
        original_decoded = original_decoded_cache[stage_index]
        if (
            any(stored[current_decoded.consumed :])
            or any(original_stored[original_decoded.consumed :])
            or len(current_decoded.output) != len(original_decoded.output)
        ):
            raise FullStoryComponentError(
                f"default formation-name STAGE decode drift: {stage_index}"
            )
        rewritten = bytearray(current_decoded.output)
        ranges = []
        chunk_entry_count = 0
        chunk_metadata = []
        stage_cells = sorted(
            (
                (group, cell)
                for group in stage_groups
                for cell in group.cells
            ),
            key=lambda item: item[1].offset,
        )
        for group, cell in stage_cells:
            slot_size = group.slot_size
            decoded_offset = cell.offset
            raw_offset = f"0x{decoded_offset:X}"
            slot_end = decoded_offset + slot_size
            if slot_end > len(rewritten) or (
                ranges and decoded_offset < ranges[-1][1]
            ):
                raise FullStoryComponentError(
                    f"default formation-name slots overlap at {raw_offset}"
                )
            ranges.append((decoded_offset, slot_end))
            source = decode_text(
                original_decoded.output,
                decoded_offset,
                table,
                end=slot_end,
            )
            if (
                source.text != cell.source_text
                or source.consumed != cell.source_consumed
                or any(
                    original_decoded.output[
                        decoded_offset + source.consumed : slot_end
                    ]
                )
            ):
                raise FullStoryComponentError(
                    f"default formation-name source or slot drift at "
                    f"stage {stage_index} {raw_offset}"
                )
            translation = normalize_original_fullwidth_ascii(
                translations_by_source[source.text]
            )
            if _control_signature(source.text) != _control_signature(
                translation
            ):
                raise FullStoryComponentError(
                    f"default formation-name control drift at {raw_offset}"
                )
            try:
                encoded = text_encoder.encode(
                    translation,
                    terminate=True,
                )
            except (SrwzTextEncodeError, ValueError) as error:
                raise FullStoryComponentError(
                    f"default formation-name encoding failed at "
                    f"{raw_offset}: {error}"
                ) from error
            if len(encoded) > slot_size:
                raise FullStoryComponentError(
                    f"default formation-name overflow at {raw_offset}: "
                    f"need {len(encoded)}, capacity {slot_size}"
                )
            replacement = encoded + bytes(slot_size - len(encoded))
            source_slot = original_decoded.output[decoded_offset:slot_end]
            current_slot = bytes(rewritten[decoded_offset:slot_end])
            if current_slot not in {source_slot, replacement}:
                raise FullStoryComponentError(
                    f"default formation-name current preimage drift at "
                    f"stage {stage_index} {raw_offset}"
                )
            changed_byte_count += sum(
                before != after
                for before, after in zip(current_slot, replacement)
            )
            if (
                stage_index == fixed_stage_index
                and decoded_offset in fixed_replacements
            ):
                fixed_changed_byte_count += sum(
                    before != after
                    for before, after in zip(current_slot, replacement)
                )
                fixed_write_entry_count += current_slot != replacement
                fixed_no_op_entry_count += current_slot == replacement
                fixed_headroom = slot_size - len(encoded)
                fixed_minimum_headroom = (
                    fixed_headroom
                    if fixed_minimum_headroom is None
                    else min(fixed_minimum_headroom, fixed_headroom)
                )
            rewritten[decoded_offset:slot_end] = replacement
            if group.layout in {"record6+23", "formation18+33+1"}:
                prefix_size = 6 if group.layout == "record6+23" else 18
                metadata_start = decoded_offset - prefix_size
                metadata_end = decoded_offset
                expected_metadata = bytes.fromhex(cell.prefix_hex)
                original_metadata = original_decoded.output[
                    metadata_start:metadata_end
                ]
                current_metadata = current_decoded.output[
                    metadata_start:metadata_end
                ]
                if (
                    metadata_start < 0
                    or len(expected_metadata) != prefix_size
                    or original_metadata != expected_metadata
                    or current_metadata != expected_metadata
                ):
                    raise FullStoryComponentError(
                        "default formation-name metadata drift at "
                        f"stage {stage_index} {raw_offset}"
                    )
                chunk_metadata.append(
                    (metadata_start, metadata_end, expected_metadata)
                )
                if group.layout == "formation18+33+1":
                    trailer_start = slot_end
                    trailer_end = trailer_start + 1
                    expected_trailer = bytes.fromhex(cell.trailer_hex)
                    if (
                        len(expected_trailer) != 1
                        or original_decoded.output[
                            trailer_start:trailer_end
                        ]
                        != expected_trailer
                        or current_decoded.output[
                            trailer_start:trailer_end
                        ]
                        != expected_trailer
                    ):
                        raise FullStoryComponentError(
                            "default formation-name trailer drift at "
                            f"stage {stage_index} {raw_offset}"
                        )
                    chunk_metadata.append(
                        (trailer_start, trailer_end, expected_trailer)
                    )
            reread = decode_text(bytes(rewritten), decoded_offset, output_table)
            if (
                reread.text != translation
                or reread.consumed > slot_size
                or any(rewritten[decoded_offset + reread.consumed : slot_end])
            ):
                raise FullStoryComponentError(
                    f"default formation-name readback drift at {raw_offset}"
                )
            headroom = slot_size - len(encoded)
            minimum_headroom = (
                headroom
                if minimum_headroom is None
                else min(minimum_headroom, headroom)
            )
            translations.add((source.text, translation))
            chunk_entry_count += 1
        if any(
            bytes(rewritten[start_offset:end_offset]) != expected_trailer
            for start_offset, end_offset, expected_trailer in chunk_metadata
        ):
            raise FullStoryComponentError(
                f"default formation-name metadata changed: {stage_index}"
            )
        rewritten_bytes = bytes(rewritten)
        compression_future = compression_executor.submit(
            reencode_changed_suffix,
            stored[: current_decoded.consumed],
            rewritten_bytes,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=len(stored),
            original_result=current_decoded,
        )
        pending_chunks.append(
            (
                stage_index,
                start,
                end,
                stored,
                current_decoded,
                rewritten_bytes,
                chunk_entry_count,
                compression_future,
            )
        )

    for (
        stage_index,
        start,
        end,
        stored,
        current_decoded,
        rewritten_bytes,
        chunk_entry_count,
        compression_future,
    ) in pending_chunks:
        try:
            rebuilt = compression_future.result()
        except (RuntimeError, ValueError) as error:
            raise FullStoryComponentError(
                f"default formation-name compression failed for stage "
                f"{stage_index}: {error}"
            ) from error
        rebuilt_stored = rebuilt + bytes(len(stored) - len(rebuilt))
        output[start:end] = rebuilt_stored
        chunk_report = {
            "stage_index": stage_index,
            "entry_count": chunk_entry_count,
            "source_stored_size": len(stored),
            "source_encoded_size": current_decoded.consumed,
            "output_encoded_size": len(rebuilt),
            "output_encoded_sha256": sha256_bytes(rebuilt),
            "output_padding_size": len(rebuilt_stored) - len(rebuilt),
            "codec_round_trip_exact": True,
        }
        chunk_reports.append(chunk_report)
        if stage_index == fixed_stage_index:
            fixed_chunk_report = chunk_report
    compression_executor.shutdown(wait=True, cancel_futures=True)

    result = bytes(output)
    if (
        len(result) != len(stage)
        or read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(result))
        != offsets
    ):
        raise FullStoryComponentError(
            "default formation-name STAGE archive layout changed"
        )
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        if index not in groups_by_stage and result[start:end] != stage[start:end]:
            raise FullStoryComponentError(
                f"default formation-name changed non-target chunk: {index}"
            )
    if fixed_chunk_report is None:
        raise FullStoryComponentError("fixed formation-name fused chunk is missing")
    fixed_report = {
        "entry_count": len(fixed_replacements),
        "write_entry_count": fixed_write_entry_count,
        "no_op_entry_count": fixed_no_op_entry_count,
        "minimum_output_headroom": fixed_minimum_headroom,
        "changed_byte_count": fixed_changed_byte_count,
        "fixed_spans_preserved": True,
        "pointer_bytes_unchanged": True,
        "placeholder_control_tokens_preserved": True,
        "reread_exact": True,
        "chunk_index": fixed_stage_index,
        "source_text": "別働隊",
        "translation": translations_by_source["別働隊"],
        "source_stored_size": fixed_chunk_report["source_stored_size"],
        "source_encoded_size": fixed_chunk_report["source_encoded_size"],
        "output_encoded_size": fixed_chunk_report["output_encoded_size"],
        "output_encoded_sha256": fixed_chunk_report["output_encoded_sha256"],
        "output_padding_size": fixed_chunk_report["output_padding_size"],
        "codec_strategy": codec["strategy"],
        "codec_round_trip_exact": True,
        "archive_size_preserved": True,
        "hb_offsets_preserved": True,
        "non_target_chunks_preserved_byte_exact": True,
        "fused_into_default_formation_pass": True,
    }
    default_report = {
        "group_count": len(groups),
        "stage_count": len(groups_by_stage),
        "stage_indices": sorted(groups_by_stage),
        "entry_count": entry_count,
        "unique_source_count": len(source_texts),
        "layout_group_counts": layout_counts,
        "record_metadata_count": record_metadata_count,
        "inventory_sha256": inventory_sha256,
        "translations": [
            {"source": source, "translation": translation}
            for source, translation in sorted(translations)
        ],
        "minimum_slot_headroom": minimum_headroom,
        "changed_byte_count": changed_byte_count,
        "chunks": chunk_reports,
        "source_preimages_exact": True,
        "fixed_allocations_preserved": True,
        "record_metadata_preserved_byte_exact": True,
        "slot_padding_zero": True,
        "reread_exact": True,
        "codec_strategy": codec["strategy"],
        "codec_round_trip_exact": True,
        "archive_size_preserved": True,
        "hb_offsets_preserved": True,
        "non_target_chunks_preserved_byte_exact": True,
        "placeholder_control_tokens_preserved": True,
    }
    return (
        result,
        default_report,
        fixed_report,
        original_stage_path,
        corpus_path,
        inventory_path,
    )


def _apply_stage_system_dialogues(
    stage: bytes,
    hb: bytes,
    reference: dict,
    font_manifest: dict,
    codec: dict,
    *,
    chunk_workspace: CompressedStreamWorkspace | None = None,
) -> tuple[bytes, dict, Path]:
    """Write the reviewed chunk-zero quit scene without moving its pointers."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError("remaining UI configuration is invalid")
    original_stage_path, original_stage = _locked_file(
        reference.get("original_stage"), label="original STAGE"
    )
    corpus_path, corpus_data = _locked_file(
        reference.get("stage_system_dialogue"),
        label="stage system dialogue corpus",
    )
    corpus = json.loads(corpus_data.decode("utf-8"))
    expected = reference.get("expected")
    entries = corpus.get("entries")
    if (
        corpus.get("editorial_status") != "reviewed"
        or not isinstance(expected, dict)
        or not isinstance(entries, list)
        or len(entries) != expected.get("stage_system_dialogue_entry_count")
        or len(original_stage) != len(stage)
    ):
        raise FullStoryComponentError("stage system dialogue selection drift")

    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member="HEDBDY/HB.BIN",
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(hb, offset_spec, len(stage))
    chunk_index = 0
    start, end = offsets[chunk_index : chunk_index + 2]
    stored = stage[start:end]
    original_stored = original_stage[start:end]
    current_decoded = (
        chunk_workspace.view()
        if chunk_workspace is not None
        else decode(stored)
    )
    original_decoded = decode(original_stored)
    if (
        any(stored[current_decoded.consumed :])
        or any(original_stored[original_decoded.consumed :])
        or len(current_decoded.output) != len(original_decoded.output)
        or (
            chunk_workspace is not None
            and stored[: current_decoded.consumed] != chunk_workspace.stored
        )
    ):
        raise FullStoryComponentError("stage system dialogue decode drift")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    source_inventory = parse_stage_system_dialogues(
        original_decoded.output,
        table,
    )
    source_entries = {entry.entry_id: entry for entry in source_inventory}
    if len(source_inventory) != expected.get(
        "stage_system_dialogue_inventory_count"
    ):
        raise FullStoryComponentError("stage system dialogue inventory drift")
    replacements = {}
    selected_pointer_offsets = []
    for item in entries:
        if not isinstance(item, dict):
            raise FullStoryComponentError(
                "stage system dialogue corpus entry is malformed"
            )
        entry_id = item.get("id")
        source = source_entries.get(entry_id)
        speaker = item.get("speaker")
        translation = item.get("translation")
        if (
            source is None
            or item.get("editorial_status") != "reviewed"
            or item.get("source_text_sha256")
            != sha256_bytes(source.text.encode("utf-8"))
            or not isinstance(speaker, str)
            or not speaker
            or not isinstance(translation, str)
            or not translation
        ):
            raise FullStoryComponentError(
                f"stage system dialogue source drift: {entry_id!r}"
            )
        replacements[entry_id] = (
            normalize_original_fullwidth_ascii(speaker),
            normalize_original_fullwidth_ascii(translation),
        )
        selected_pointer_offsets.append(source.pointer_offset)
    inventory_pointer_offsets = [
        entry.pointer_offset for entry in source_inventory
    ]
    if selected_pointer_offsets != inventory_pointer_offsets:
        raise FullStoryComponentError(
            "stage system dialogue pointer selection drift"
        )
    pointer_offsets_sha256 = sha256_bytes(
        json.dumps(
            selected_pointer_offsets,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if pointer_offsets_sha256 != expected.get(
        "stage_system_dialogue_pointer_offsets_sha256"
    ):
        raise FullStoryComponentError(
            "stage system dialogue pointer selection SHA-256 drift"
        )

    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    try:
        write = replace_stage_system_dialogues_in_place(
            current_decoded.output,
            table,
            replacements=replacements,
            overrides=encoding_overrides,
        )
    except (WritebackError, ValueError) as error:
        raise FullStoryComponentError(
            f"stage system dialogue write failed: {error}"
        ) from error
    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError(
            "stage system dialogue codec policy is invalid"
        )
    if chunk_workspace is not None:
        try:
            chunk_workspace.replace(write.data, stage="stage system dialogues")
        except ValueError as error:
            raise FullStoryComponentError(str(error)) from error
        encoded = None
        rebuilt_stored = stored
        output = stage
    else:
        try:
            encoded = reencode_changed_suffix(
                stored[: current_decoded.consumed],
                write.data,
                strategy=codec["strategy"],
                min_match_length=codec["min_match_length"],
                max_match_chain=codec["max_match_chain"],
                lazy_matching=codec["lazy_matching"],
                max_output_size=len(stored),
                original_result=current_decoded,
            )
        except (RuntimeError, ValueError) as error:
            raise FullStoryComponentError(
                f"stage system dialogue compression failed: {error}"
            ) from error
        round_trip = decode(encoded)
        if (
            round_trip.output != write.data
            or round_trip.consumed != len(encoded)
            or round_trip.flags != current_decoded.flags
        ):
            raise FullStoryComponentError(
                "stage system dialogue codec round-trip failed"
            )
        rebuilt_stored = encoded + bytes(len(stored) - len(encoded))
        output = stage[:start] + rebuilt_stored + stage[end:]
    if (
        len(output) != len(stage)
        or read_executable_archive_offsets(hb, offset_spec, len(output)) != offsets
        or output[:start] != stage[:start]
        or output[end:] != stage[end:]
    ):
        raise FullStoryComponentError(
            "stage system dialogue archive layout changed"
        )
    report = write.to_metadata()
    report.update(
        {
            "inventory_entry_count": len(source_entries),
            "selected_entry_count": len(replacements),
            "selected_pointer_offsets": selected_pointer_offsets,
            "selected_pointer_offsets_sha256": pointer_offsets_sha256,
            "source_preimages_sha256_exact": True,
            "pointer_bytes_unchanged": True,
            "reread_exact": True,
            "codec_strategy": codec["strategy"],
            "source_encoded_size": current_decoded.consumed,
            "output_encoded_size": (
                None if encoded is None else len(encoded)
            ),
            "codec_round_trip_exact": chunk_workspace is None,
            "compression_deferred_to_workspace": chunk_workspace is not None,
            "archive_size_preserved": True,
            "hb_offsets_preserved": True,
            "non_target_chunks_preserved_byte_exact": True,
        }
    )
    return output, report, corpus_path


def _apply_hsfc_overviews(
    slps: bytes,
    reference: dict,
    font_manifest: dict,
    codec: dict,
) -> tuple[bytes, dict, tuple[Path, Path]]:
    """Rewrite the actual Scenario Chart summaries in fixed HSFC chunk 0."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError("HSFC-overview configuration is invalid")
    original_path, original = _locked_file(
        reference.get("original"), label="original HSFC.BIN"
    )
    corpus_path, corpus_bytes = _locked_file(
        reference.get("corpus"), label="HSFC-overview corpus"
    )
    corpus = json.loads(corpus_bytes.decode("utf-8"))
    entries = corpus.get("entries")
    policy = corpus.get("policy")
    inventory = corpus.get("inventory")
    expected = reference.get("expected")
    if (
        corpus.get("editorial_status") != "reviewed"
        or not isinstance(entries, list)
        or not isinstance(policy, dict)
        or policy.get("translation_method") != "direct_manual"
        or policy.get("external_model_used") is not False
        or policy.get("source_text_authority") != "original_disc_only"
        or policy.get("preserve_archive_size") is not True
        or policy.get("preserve_archive_offsets") is not True
        or policy.get("preserve_fixed_cells") is not True
        or policy.get("duplicate_sources_share_one_translation") is not True
        or not isinstance(inventory, dict)
        or not isinstance(expected, dict)
        or len(entries) != expected.get("translated_unique_entry_count")
        or inventory.get("record_count") != expected.get("record_count")
        or inventory.get("unique_source_text_count")
        != expected.get("unique_source_text_count")
        or inventory.get("chunk_index") != 0
        or inventory.get("stored_chunk_size")
        != expected.get("stored_chunk_size")
        or inventory.get("decoded_chunk_size")
        != expected.get("decoded_chunk_size")
    ):
        raise FullStoryComponentError("HSFC-overview corpus contract drift")

    spec = ExecutableOffsetSpec(
        name="DATA/HSFC.BIN offsets",
        member="DATA/HSFC.BIN",
        table_start=0x3476A0,
        table_end=0x3476B0,
    )
    offsets = read_executable_archive_offsets(slps, spec, len(original))
    if (
        len(offsets) != expected.get("offset_count")
        or offsets != tuple(expected.get("offsets", []))
        or offsets[-1] != len(original)
    ):
        raise FullStoryComponentError("HSFC executable offset table drift")
    stored = original[offsets[0] : offsets[1]]
    decoded = decode(stored)
    if (
        decoded.consumed != expected.get("source_encoded_size")
        or len(decoded.output) != expected.get("decoded_chunk_size")
        or any(stored[decoded.consumed :])
    ):
        raise FullStoryComponentError("HSFC chunk 0 decode drift")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    try:
        rewritten, overview_report = replace_hsfc_overviews_in_place(
            decoded.output,
            table,
            entries,
            encoding_overrides=encoding_overrides,
        )
    except ValueError as error:
        raise FullStoryComponentError(
            f"HSFC-overview write failed: {error}"
        ) from error
    if (
        overview_report["inventory_record_count"]
        != expected.get("record_count")
        or overview_report["unique_source_text_count"]
        != expected.get("unique_source_text_count")
        or overview_report["translated_unique_entry_count"]
        != expected.get("translated_unique_entry_count")
        or overview_report["translated_occurrence_count"]
        != expected.get("translated_occurrence_count")
    ):
        raise FullStoryComponentError("HSFC-overview selection drift")
    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError("HSFC-overview codec policy is invalid")
    try:
        rebuilt = reencode_changed_suffix(
            stored[: decoded.consumed],
            rewritten,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=len(stored),
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"HSFC-overview compression failed: {error}"
        ) from error
    round_trip = decode(rebuilt)
    if (
        round_trip.consumed != len(rebuilt)
        or round_trip.output != rewritten
        or round_trip.flags != decoded.flags
    ):
        raise FullStoryComponentError("HSFC-overview codec round-trip failed")
    rebuilt_stored = rebuilt + bytes(len(stored) - len(rebuilt))
    output = rebuilt_stored + original[offsets[1] :]
    if (
        len(output) != len(original)
        or read_executable_archive_offsets(slps, spec, len(output)) != offsets
        or output[offsets[1] :] != original[offsets[1] :]
    ):
        raise FullStoryComponentError("HSFC archive layout changed")
    overview_report.update(
        {
            "chunk_index": 0,
            "source_stored_size": len(stored),
            "source_encoded_size": decoded.consumed,
            "output_encoded_size": len(rebuilt),
            "output_padding_size": len(rebuilt_stored) - len(rebuilt),
            "codec_round_trip_exact": True,
            "archive_size_preserved": True,
            "slps_offsets_preserved": True,
            "non_target_chunks_preserved_byte_exact": True,
            "translation_method": "direct_manual",
            "external_model_used": False,
        }
    )
    return output, overview_report, (corpus_path, original_path)


def _control_signature(text: str) -> tuple[tuple[str, str], ...]:
    return tuple((token.kind, token.text) for token in control_notation_tokens(text))


def _apply_fixed_span_translations(
    current: bytes,
    original: bytes,
    replacements: dict,
    *,
    table,
    output_table,
    encoding_overrides: dict[str, int],
    label: str,
    accepted_current_texts: dict[str, str] | None = None,
) -> tuple[bytes, dict]:
    """Write a locked offset map using only original terminated capacities."""

    if not isinstance(replacements, dict) or not replacements:
        raise FullStoryComponentError(f"{label} translation map is invalid")
    output = bytearray(current)
    ranges = []
    write_count = 0
    no_op_count = 0
    minimum_headroom = None
    changed_offsets = set()
    for raw_offset, raw_translation in sorted(
        replacements.items(), key=lambda item: int(item[0], 16)
    ):
        try:
            offset = int(raw_offset, 16)
        except (TypeError, ValueError) as error:
            raise FullStoryComponentError(
                f"{label} offset is invalid: {raw_offset!r}"
            ) from error
        if (
            not isinstance(raw_offset, str)
            or raw_offset != f"0x{offset:X}"
            or not isinstance(raw_translation, str)
            or not raw_translation
        ):
            raise FullStoryComponentError(
                f"{label} translation is invalid at {raw_offset!r}"
            )
        source = decode_text(original, offset, table)
        end = offset + source.consumed
        if end > len(current):
            raise FullStoryComponentError(
                f"{label} span is outside current member: {raw_offset}"
            )
        if ranges and offset < ranges[-1][1]:
            raise FullStoryComponentError(
                f"{label} spans overlap at {raw_offset}"
            )
        ranges.append((offset, end))
        translation = normalize_original_fullwidth_ascii(raw_translation)
        if _control_signature(source.text) != _control_signature(translation):
            raise FullStoryComponentError(
                f"{label} placeholder/control drift at {raw_offset}: "
                f"source={source.text!r} translation={translation!r}"
            )
        try:
            encoded = encode_text(
                translation,
                table,
                overrides=encoding_overrides,
                terminate=True,
            )
        except (SrwzTextEncodeError, ValueError) as error:
            raise FullStoryComponentError(
                f"{label} encoding failed at {raw_offset}: {error}"
            ) from error
        if len(encoded) > source.consumed:
            raise FullStoryComponentError(
                f"{label} overflow at {raw_offset}: need {len(encoded)}, "
                f"capacity {source.consumed}"
            )
        current_span = current[offset:end]
        original_span = original[offset:end]
        replacement = encoded + bytes(source.consumed - len(encoded))
        if current_span != original_span and current_span != replacement:
            current_text = decode_text(current, offset, output_table)
            accepted_current = (
                accepted_current_texts.get(raw_offset)
                if isinstance(accepted_current_texts, dict)
                else None
            )
            if (
                normalize_original_fullwidth_ascii(current_text.text)
                not in {translation, accepted_current}
                or current_text.consumed > source.consumed
            ):
                raise FullStoryComponentError(
                    f"{label} current preimage drift at {raw_offset}: "
                    f"current={current_text.text!r} expected={translation!r}"
                )
        headroom = source.consumed - len(encoded)
        minimum_headroom = (
            headroom
            if minimum_headroom is None
            else min(minimum_headroom, headroom)
        )
        if current_span == replacement:
            no_op_count += 1
        else:
            output[offset:end] = replacement
            write_count += 1
            changed_offsets.update(
                index
                for index, (before, after) in enumerate(
                    zip(current_span, replacement), start=offset
                )
                if before != after
            )
        reread = decode_text(bytes(output), offset, output_table)
        if reread.text != translation:
            raise FullStoryComponentError(
                f"{label} readback mismatch at {raw_offset}: "
                f"expected={translation!r} actual={reread.text!r}"
            )
    return bytes(output), {
        "entry_count": len(replacements),
        "write_entry_count": write_count,
        "no_op_entry_count": no_op_count,
        "minimum_output_headroom": minimum_headroom,
        "changed_byte_count": len(changed_offsets),
        "fixed_spans_preserved": True,
        "pointer_bytes_unchanged": True,
        "placeholder_control_tokens_preserved": True,
        "reread_exact": True,
    }


def _apply_fixed_inline_translations(
    current: bytes,
    original: bytes,
    replacements: dict,
    *,
    table,
    encoding_overrides: dict[str, int],
    label: str,
) -> tuple[bytes, dict]:
    """Replace non-terminated substrings without moving later entry points."""

    if not isinstance(replacements, dict) or not replacements:
        raise FullStoryComponentError(f"{label} translation map is invalid")
    try:
        padding = encode_text("　", table, terminate=False)
    except (SrwzTextEncodeError, ValueError) as error:
        raise FullStoryComponentError(
            f"{label} fullwidth-space encoding failed: {error}"
        ) from error
    if len(padding) != 2:
        raise FullStoryComponentError(
            f"{label} fullwidth-space encoding is not one double-byte glyph"
        )

    output = bytearray(current)
    ranges = []
    write_count = 0
    no_op_count = 0
    minimum_headroom = None
    changed_offsets = set()
    for raw_offset, raw_entry in sorted(
        replacements.items(), key=lambda item: int(item[0], 16)
    ):
        try:
            offset = int(raw_offset, 16)
        except (TypeError, ValueError) as error:
            raise FullStoryComponentError(
                f"{label} offset is invalid: {raw_offset!r}"
            ) from error
        if (
            not isinstance(raw_offset, str)
            or raw_offset != f"0x{offset:X}"
            or not isinstance(raw_entry, dict)
            or set(raw_entry) != {"source", "translation"}
            or not isinstance(raw_entry.get("source"), str)
            or not raw_entry["source"]
            or not isinstance(raw_entry.get("translation"), str)
            or not raw_entry["translation"]
        ):
            raise FullStoryComponentError(
                f"{label} entry is invalid at {raw_offset!r}"
            )
        source = raw_entry["source"]
        translation = normalize_original_fullwidth_ascii(
            raw_entry["translation"]
        )
        if _control_signature(source) != _control_signature(translation):
            raise FullStoryComponentError(
                f"{label} placeholder/control drift at {raw_offset}"
            )
        try:
            source_encoded = encode_text(source, table, terminate=False)
            encoded = encode_text(
                translation,
                table,
                overrides=encoding_overrides,
                terminate=False,
            )
        except (SrwzTextEncodeError, ValueError) as error:
            raise FullStoryComponentError(
                f"{label} encoding failed at {raw_offset}: {error}"
            ) from error
        end = offset + len(source_encoded)
        if end > len(current) or original[offset:end] != source_encoded:
            raise FullStoryComponentError(
                f"{label} source preimage drift at {raw_offset}"
            )
        if ranges and offset < ranges[-1][1]:
            raise FullStoryComponentError(
                f"{label} spans overlap at {raw_offset}"
            )
        ranges.append((offset, end))
        headroom = len(source_encoded) - len(encoded)
        if headroom < 0 or headroom % len(padding):
            raise FullStoryComponentError(
                f"{label} overflow or odd headroom at {raw_offset}: "
                f"need {len(encoded)}, capacity {len(source_encoded)}"
            )
        replacement = encoded + padding * (headroom // len(padding))
        current_span = current[offset:end]
        original_span = original[offset:end]
        if current_span not in {original_span, replacement}:
            raise FullStoryComponentError(
                f"{label} current preimage drift at {raw_offset}"
            )
        minimum_headroom = (
            headroom
            if minimum_headroom is None
            else min(minimum_headroom, headroom)
        )
        if current_span == replacement:
            no_op_count += 1
        else:
            output[offset:end] = replacement
            write_count += 1
            changed_offsets.update(
                index
                for index, (before, after) in enumerate(
                    zip(current_span, replacement), start=offset
                )
                if before != after
            )
        if bytes(output[offset:end]) != replacement:
            raise FullStoryComponentError(
                f"{label} byte readback mismatch at {raw_offset}"
            )
    return bytes(output), {
        "entry_count": len(replacements),
        "write_entry_count": write_count,
        "no_op_entry_count": no_op_count,
        "minimum_output_headroom": minimum_headroom,
        "changed_byte_count": len(changed_offsets),
        "fixed_spans_preserved": True,
        "internal_entry_offsets_preserved": True,
        "pointer_bytes_unchanged": True,
        "placeholder_control_tokens_preserved": True,
        "fullwidth_space_padding_only": True,
        "reread_exact": True,
    }


def _apply_remaining_ui(
    slps: bytes,
    stored_compdata: bytes,
    reference: dict,
    descriptor_path: Path,
    font_manifest: dict,
    codec: dict,
    *,
    workspace: CompressedStreamWorkspace | None = None,
    original_decoded=None,
) -> tuple[bytes, bytes, dict, tuple[Path, Path, Path, Path]]:
    """Write the reviewed remaining UI text without touching atlas pixels."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError("remaining UI configuration is invalid")
    translation_path, translation_data = _locked_file(
        reference.get("translations"), label="remaining UI translations"
    )
    parts_path, parts_data = _locked_file(
        reference.get("parts"), label="remaining UI parts translations"
    )
    original_compdata_path, original_compdata = _locked_file(
        reference.get("original_compdata"), label="original COMPDATA"
    )
    original_slps_path, original_slps = _locked_file(
        reference.get("original_slps"), label="original SLPS"
    )
    translations = json.loads(translation_data.decode("utf-8"))
    if (
        translations.get("editorial_status") != "reviewed"
        or translations.get("policy", {}).get("source_text_authority")
        != "original_disc_only"
        or translations.get("policy", {}).get("binary_writeback") is not True
        or translations.get("policy", {}).get("preserve_control_tokens")
        is not True
        or translations.get("policy", {}).get(
            "single_character_atlas_writeback"
        )
        is not False
    ):
        raise FullStoryComponentError("remaining UI translation policy drift")

    expected = reference.get("expected")
    direct = translations.get("compdata_direct_by_offset")
    context_help = translations.get("compdata_context_help_by_offset")
    inline = translations.get("compdata_inline_by_offset")
    leadership = translations.get("leadership_effect_by_offset")
    slps_context = translations.get("slps_context_ui_by_offset")
    slps_map = translations.get("slps_by_offset")
    accepted_current = translations.get("accepted_current_preimages_by_offset")
    atlas = translations.get("atlas_by_source_text")
    display_names = translations.get("display_names_by_source_text")
    parts_document = json.loads(parts_data.decode("utf-8"))
    part_entries = parts_document.get("entries")
    if not isinstance(expected, dict) or (
        not isinstance(direct, dict)
        or len(direct) != expected.get("compdata_direct_entry_count")
        or not isinstance(context_help, dict)
        or len(context_help)
        != expected.get("compdata_context_help_entry_count")
        or not isinstance(inline, dict)
        or len(inline) != expected.get("compdata_inline_entry_count")
        or not isinstance(leadership, dict)
        or len(leadership) != expected.get("leadership_effect_entry_count")
        or not isinstance(slps_context, dict)
        or len(slps_context) != expected.get("slps_context_ui_entry_count")
        or not isinstance(slps_map, dict)
        or len(slps_map) != expected.get("slps_entry_count")
        or not isinstance(accepted_current, dict)
        or len(accepted_current)
        != expected.get("accepted_current_preimage_count")
        or not isinstance(atlas, dict)
        or len(atlas) != expected.get("atlas_entry_count")
        or not isinstance(display_names, dict)
        or len(display_names) != expected.get(
            "residual_display_name_unique_count"
        )
        or not isinstance(part_entries, list)
        or len(part_entries) != expected.get("parts_entry_count")
    ):
        raise FullStoryComponentError("remaining UI selection drift")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    output_table = project_runtime_text_table(table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(table)
    )

    if original_decoded is None:
        original_decoded = decode(original_compdata)
    current_decoded = (
        workspace.view() if workspace is not None else decode(stored_compdata)
    )
    if (
        original_decoded.consumed != len(original_compdata)
        or current_decoded.consumed != len(stored_compdata)
        or len(current_decoded.output) != len(original_decoded.output)
    ):
        raise FullStoryComponentError("remaining UI COMPDATA decode drift")
    compdata_output, direct_report = _apply_fixed_span_translations(
        current_decoded.output,
        original_decoded.output,
        direct,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="remaining COMPDATA UI",
        accepted_current_texts=accepted_current,
    )
    compdata_output, context_help_report = _apply_fixed_span_translations(
        compdata_output,
        original_decoded.output,
        context_help,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="remaining COMPDATA context help",
    )
    compdata_output, inline_report = _apply_fixed_inline_translations(
        compdata_output,
        original_decoded.output,
        inline,
        table=table,
        encoding_overrides=encoding_overrides,
        label="remaining COMPDATA inline UI",
    )
    compdata_output, leadership_report = _apply_fixed_span_translations(
        compdata_output,
        original_decoded.output,
        leadership,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="leadership effects",
    )
    output_slps, slps_context_report = _apply_fixed_span_translations(
        slps,
        original_slps,
        slps_context,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="remaining SLPS context UI",
    )
    output_slps, slps_report = _apply_fixed_span_translations(
        output_slps,
        original_slps,
        slps_map,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="remaining SLPS UI",
        accepted_current_texts=accepted_current,
    )

    descriptors = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor_by_name = {
        descriptor.get("friendly_name"): descriptor
        for descriptor in descriptors
        if isinstance(descriptor, dict)
    }
    compdata_descriptor = descriptor_by_name.get("Compdata")
    if not isinstance(compdata_descriptor, dict):
        raise FullStoryComponentError("remaining UI Compdata descriptor missing")
    original_menu = parse_menu_file(
        original_decoded.output, compdata_descriptor, table
    )
    original_by_id = {entry.entry_id: entry for entry in original_menu.entries}
    part_replacements = {}
    for item in part_entries:
        if not isinstance(item, dict):
            raise FullStoryComponentError("remaining UI part entry is malformed")
        entry_id = item.get("id")
        translation = item.get("translation")
        original_entry = original_by_id.get(entry_id)
        if (
            original_entry is None
            or not isinstance(translation, str)
            or item.get("source_text_sha256")
            != sha256_bytes(original_entry.text.encode("utf-8"))
        ):
            raise FullStoryComponentError(
                f"remaining UI part source drift: {entry_id!r}"
            )
        if item.get("translation_action") == "preserve":
            if translation or original_entry.text:
                raise FullStoryComponentError(
                    f"remaining UI preserved part is not empty: {entry_id}"
                )
            continue
        if not translation:
            raise FullStoryComponentError(
                f"remaining UI part translation is empty: {entry_id}"
            )
        normalized = _two_byte_visible_spaces(
            normalize_original_fullwidth_ascii(translation)
        )
        if _control_signature(original_entry.text) != _control_signature(normalized):
            raise FullStoryComponentError(
                f"remaining UI part control-token drift: {entry_id}"
            )
        if entry_id in part_replacements:
            raise FullStoryComponentError(
                f"duplicate remaining UI part entry: {entry_id}"
            )
        part_replacements[entry_id] = normalized
    source_part_entries = [original_by_id[item["id"]] for item in part_entries]
    source_target_occurrence_count = sum(
        len(entry.target_offsets) for entry in source_part_entries
    )
    source_target_unique_count = len(
        {
            target
            for entry in source_part_entries
            for target in entry.target_offsets
        }
    )
    if (
        source_target_occurrence_count
        != expected.get("parts_source_target_occurrence_count")
        or source_target_unique_count
        != expected.get("parts_source_target_unique_count")
    ):
        raise FullStoryComponentError(
            "remaining UI parts source target-count drift"
        )
    current_menu = parse_menu_file(
        compdata_output, compdata_descriptor, output_table
    )
    try:
        parts_write = replace_menu_texts_in_place(
            compdata_output,
            current_menu,
            table,
            replacements=part_replacements,
            overrides=encoding_overrides,
            source_table=output_table,
            source_name="remaining UI strengthening parts",
        )
    except (WritebackError, ValueError) as error:
        raise FullStoryComponentError(
            f"remaining UI parts write failed: {error}"
        ) from error
    if len(parts_write.targets) != expected.get("parts_write_target_count"):
        raise FullStoryComponentError(
            "remaining UI parts target-count drift: "
            f"actual={len(parts_write.targets)} "
            f"expected={expected.get('parts_write_target_count')}"
        )
    parts_report = parts_write.to_metadata()
    parts_report.update(
        {
            "corpus_entry_count": len(part_entries),
            "preserved_empty_entry_count": len(part_entries)
            - len(part_replacements),
            "source_target_occurrence_count": source_target_occurrence_count,
            "source_target_unique_count": source_target_unique_count,
            "source_preimages_sha256_exact": True,
            "placeholder_control_tokens_preserved": True,
            "fixed_spans_preserved": True,
            "pointer_bytes_unchanged": True,
            "reread_exact": True,
        }
    )

    rebuilt_compdata = _commit_compdata_stage(
        stored_compdata,
        parts_write.data,
        current_decoded,
        codec,
        label="remaining UI COMPDATA",
        workspace=workspace,
    )

    protected = reference.get("atlas_writeback")
    if not isinstance(protected, dict) or (
        protected.get("inherited_dedicated_mask_sources")
        != [
            "バザー",
            "インターミッション",
            "オプション",
            "データ管理",
            "パイロット系",
            "小隊編成",
            "機体系",
            "次のマップへ",
            "新規編成",
            "リザーブへ",
            "小隊群へ",
        ]
        or protected.get("protected_single_character_sources") != ["攻", "反"]
        or len(protected.get("pending_dedicated_mask_sources", []))
        != expected.get("atlas_pending_dedicated_mask_count")
        or set(atlas)
        != set(protected["inherited_dedicated_mask_sources"])
        | set(protected["protected_single_character_sources"])
        | set(protected["pending_dedicated_mask_sources"])
    ):
        raise FullStoryComponentError("remaining UI atlas writeback policy drift")
    return output_slps, rebuilt_compdata, {
        "compdata_direct": direct_report,
        "compdata_context_help": context_help_report,
        "compdata_inline": inline_report,
        "leadership_effects": leadership_report,
        "slps_context_ui": slps_context_report,
        "slps": slps_report,
        "parts": parts_report,
        "residual_display_names": {
            "unique_source_count": len(display_names),
            "written_by_full_pilot_name_stage": True,
        },
        "atlas": {
            "entry_count": len(atlas),
            "inherited_dedicated_mask_sources": protected[
                "inherited_dedicated_mask_sources"
            ],
            "inherited_dedicated_mask_count": len(
                protected["inherited_dedicated_mask_sources"]
            ),
            "pending_dedicated_mask_sources": protected[
                "pending_dedicated_mask_sources"
            ],
            "pending_dedicated_mask_count": len(
                protected["pending_dedicated_mask_sources"]
            ),
            "protected_single_character_sources": protected[
                "protected_single_character_sources"
            ],
            "protected_single_character_count": len(
                protected["protected_single_character_sources"]
            ),
            "single_character_regions_untouched": True,
        },
        "compdata_source_size": len(stored_compdata),
        "compdata_output_size": (
            None if workspace is not None else len(rebuilt_compdata)
        ),
        "compdata_sector_budget": codec["max_output_size"],
        "compdata_round_trip_exact": workspace is None,
        "compression_deferred_to_workspace": workspace is not None,
        "slps_size_preserved": len(output_slps) == len(slps),
    }, (
        translation_path,
        parts_path,
        original_compdata_path,
        original_slps_path,
    )


def _apply_global_safe_aliases(
    slps: bytes,
    stored_compdata: bytes,
    descriptor_path: Path,
    font_manifest: dict,
    codec: dict,
    *,
    workspace: CompressedStreamWorkspace | None = None,
) -> tuple[bytes, bytes, dict]:
    """Re-encode every parsed localized menu surface with safe aliases."""

    descriptors = json.loads(descriptor_path.read_text(encoding="utf-8"))
    if not isinstance(descriptors, list):
        raise FullStoryComponentError("menu descriptor root is invalid")
    descriptor_by_name = {
        descriptor.get("friendly_name"): descriptor
        for descriptor in descriptors
        if isinstance(descriptor, dict)
    }
    if not {"SLPS", "Compdata"} <= set(descriptor_by_name):
        raise FullStoryComponentError("global alias menu descriptors are missing")
    _proposal_path, primary, aliases, alias_report = _full_story_overrides(
        font_manifest
    )
    conditional_characters = {
        character
        for character, code in primary.items()
        if 0x8140 <= code < 0x889F
    }
    flattened_release = alias_report.get("mode") == "flattened_global_snapshot"
    if (
        (
            set(aliases) > conditional_characters
            if flattened_release
            else set(aliases) != conditional_characters
        )
        or any(0x8140 <= code < 0x889F for code in aliases.values())
        or (
            not flattened_release
            and (
                alias_report.get("all_selected_assignments") is not True
                or alias_report.get("unaliased_conditional_assignment_count")
                != 0
            )
        )
    ):
        raise FullStoryComponentError("global safe-alias contract failed")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    source_table = project_runtime_text_table(table, primary)
    source_table = project_runtime_text_table(source_table, aliases)
    ascii_overrides = original_fullwidth_ascii_overrides(table)
    output_table = project_runtime_text_table(
        source_table, ascii_overrides
    )
    menu_aliases = {
        character: code
        for character, code in aliases.items()
        if not 0x20 <= ord(character) <= 0x7E or character in "12345"
    }
    code_substitutions = {
        primary[character]: alias_code
        for character, alias_code in menu_aliases.items()
    }
    ascii_code_substitutions = {
        primary[character]: ascii_overrides[character]
        for character in set(primary) & set(ascii_overrides)
        if primary[character] >= 0x8000
        and primary[character] != ascii_overrides[character]
    }
    code_substitutions.update(ascii_code_substitutions)
    if any(
        source == target
        or source < 0x8000
        or target < 0x8000
        for source, target in code_substitutions.items()
    ):
        raise FullStoryComponentError("global safe-alias substitution is invalid")

    decoded = workspace.view() if workspace is not None else decode(stored_compdata)
    if decoded.consumed != len(stored_compdata):
        raise FullStoryComponentError(
            "global alias COMPDATA has trailing compressed bytes"
        )

    def rewrite(
        data: bytes,
        descriptor: dict,
        label: str,
    ) -> tuple[bytes, dict]:
        parsed = parse_menu_file(data, descriptor, source_table)
        target_offsets = {
            offset
            for entry in parsed.entries
            for offset in entry.target_offsets
        }
        target_spans = {}
        for offset in sorted(target_offsets):
            decoded_target = decode_text(data, offset, source_table)
            target_spans[offset] = (
                offset,
                offset + decoded_target.consumed,
            )
        merged_ranges = []
        for start, end in target_spans.values():
            if not merged_ranges or start > merged_ranges[-1][1]:
                merged_ranges.append([start, end])
            else:
                merged_ranges[-1][1] = max(merged_ranges[-1][1], end)
        if not merged_ranges:
            return data, {
                "selected_entry_count": 0,
                "selected_target_count": 0,
                "substituted_code_count": 0,
                "size_preserved": True,
                "pointer_bytes_unchanged": True,
                "reread_exact": True,
            }
        output = bytearray(data)
        changed_offsets = set()
        for start, end in merged_ranges:
            cursor = start
            while cursor < end:
                lead = data[cursor]
                if lead == 0 or lead == 0x0A:
                    cursor += 1
                    continue
                if 0x31 <= lead <= 0x35:
                    cursor += 2
                    continue
                if 0x80 <= lead <= 0x9F or 0xE0 <= lead <= 0xEA:
                    if cursor + 1 >= end:
                        raise FullStoryComponentError(
                            f"truncated menu code in {label}"
                        )
                    code = (lead << 8) | data[cursor + 1]
                    replacement = code_substitutions.get(code)
                    if replacement is not None:
                        output[cursor : cursor + 2] = replacement.to_bytes(
                            2, "big"
                        )
                        changed_offsets.add(cursor)
                    cursor += 2
                    continue
                cursor += 1
        rewritten = bytes(output)
        reread = parse_menu_file(rewritten, descriptor, output_table)
        reread_by_id = {
            entry.entry_id: normalize_original_fullwidth_ascii(entry.text)
            for entry in reread.entries
        }
        expected_by_id = {
            entry.entry_id: normalize_original_fullwidth_ascii(entry.text)
            for entry in parsed.entries
        }
        nested_raw_mismatches = []
        mismatches = [
                (entry_id, expected, reread_by_id.get(entry_id))
                for entry_id, expected in expected_by_id.items()
                if reread_by_id.get(entry_id) != expected
        ]
        invalid_mismatches = []
        entries_by_id = {
            entry.entry_id: entry for entry in parsed.entries
        }
        entry_spans = {
            entry.entry_id: [
                target_spans[offset]
                for offset in entry.target_offsets
            ]
            for entry in parsed.entries
        }
        for mismatch in mismatches:
            entry_id, expected, _actual = mismatch
            spans = entry_spans[entry_id]
            strictly_nested = any(
                other_start < start < other_end
                for start, _end in spans
                for other_id, other_spans in entry_spans.items()
                if other_id != entry_id
                for other_start, other_end in other_spans
            )
            if (
                re.fullmatch(r"(?:\{[0-9A-F]{2}\})+", expected)
                and strictly_nested
            ):
                nested_raw_mismatches.append(mismatch)
            else:
                invalid_mismatches.append(mismatch)
        if invalid_mismatches:
            mismatch_details = []
            for entry_id, _expected, _actual in invalid_mismatches[:10]:
                entry = entries_by_id[entry_id]
                spans = entry_spans[entry_id]
                affected = sorted(
                    changed
                    for changed in changed_offsets
                    if any(
                        changed < end and changed + 2 > start
                        for start, end in spans
                    )
                )
                owners = sorted(
                    (other.entry_id, other.text, list(other.target_offsets))
                    for other in parsed.entries
                    if any(
                        changed < end and changed + 2 > start
                        for changed in affected
                        for start, end in (
                            (
                                offset,
                                entry_spans[other.entry_id][index][1],
                            )
                            for index, offset in enumerate(other.target_offsets)
                        )
                    )
                )
                mismatch_details.append(
                    {
                        "entry_id": entry_id,
                        "affected_offsets": [hex(value) for value in affected],
                        "overlapping_entries": owners,
                    }
                )
            raise FullStoryComponentError(
                f"global safe-alias reread failed for {label}: "
                f"{invalid_mismatches[:10]!r} details={mismatch_details!r}"
            )
        selected_entries = _count_span_groups_containing_offsets(
            [entry_spans[entry.entry_id] for entry in parsed.entries],
            changed_offsets,
        )
        return rewritten, {
            "selected_entry_count": selected_entries,
            "selected_target_count": len(target_offsets),
            "merged_text_range_count": len(merged_ranges),
            "substituted_code_count": len(changed_offsets),
            "nested_raw_overlap_mismatch_count": len(
                nested_raw_mismatches
            ),
            "nested_raw_overlap_entry_ids": [
                item[0] for item in nested_raw_mismatches
            ],
            "size_preserved": len(rewritten) == len(data),
            "pointer_bytes_unchanged": True,
            "reread_exact": True,
        }

    rewritten_slps, slps_report = rewrite(
        slps, descriptor_by_name["SLPS"], "global safe aliases SLPS"
    )
    rewritten_compdata, compdata_report = rewrite(
        decoded.output,
        descriptor_by_name["Compdata"],
        "global safe aliases COMPDATA",
    )
    rebuilt_compdata = _commit_compdata_stage(
        stored_compdata,
        rewritten_compdata,
        decoded,
        codec,
        label="global safe-alias COMPDATA",
        workspace=workspace,
    )
    return rewritten_slps, rebuilt_compdata, {
        "scope": "all-parsed-localized-menu-surfaces",
        "conditional_primary_assignment_count": len(aliases),
        "release_conditional_primary_assignment_count": len(
            conditional_characters
        ),
        "release_only_unaliased_conditional_assignment_count": len(
            conditional_characters - set(aliases)
        ),
        "safe_alias_assignment_count": len(aliases),
        "menu_applicable_safe_alias_assignment_count": len(menu_aliases),
        "original_ascii_code_substitution_count": len(
            ascii_code_substitutions
        ),
        "unaliased_conditional_assignment_count": 0,
        "alias_codes_default_width_only": True,
        "slps": slps_report,
        "compdata": compdata_report,
        "compdata_source_size": len(stored_compdata),
        "compdata_output_size": (
            None if workspace is not None else len(rebuilt_compdata)
        ),
        "compdata_round_trip_exact": workspace is None,
        "compression_deferred_to_workspace": workspace is not None,
    }


def _apply_compdata_battle_lines(
    stored_compdata: bytes,
    reference: dict,
    descriptor_path: Path,
    original_compdata_path: Path,
    font_manifest: dict,
    codec: dict,
    *,
    workspace: CompressedStreamWorkspace | None = None,
    original_decoded=None,
) -> tuple[bytes, dict, Path]:
    """Write the complete map battle/retreat-line corpus into COMPDATA."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError(
            "COMPDATA battle-line configuration is invalid"
        )
    corpus_path, corpus_data = _locked_file(
        reference.get("corpus"), label="COMPDATA battle-line corpus"
    )
    document = json.loads(corpus_data.decode("utf-8"))
    entries = document.get("entries")
    scope = document.get("scope")
    expected = reference.get("expected")
    if (
        document.get("batch_id") != "v1-menu-battle-lines"
        or document.get("language") != "zh-Hans"
        or not isinstance(scope, dict)
        or scope.get("domain") != "menu"
        or scope.get("section") != "Battle Lines"
        or not isinstance(entries, list)
        or not isinstance(expected, dict)
        or len(entries) != expected.get("entry_count")
        or scope.get("entry_count") != len(entries)
        or any(
            not isinstance(item, dict)
            or item.get("editorial_status") != "draft"
            or item.get("translation_action") != "translate"
            or not isinstance(item.get("translation"), str)
            or not item["translation"]
            for item in entries
        )
    ):
        raise FullStoryComponentError(
            "COMPDATA battle-line corpus contract drift"
        )

    descriptors = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor = next(
        (
            row
            for row in descriptors
            if isinstance(row, dict) and row.get("friendly_name") == "Compdata"
        ),
        None,
    )
    if not isinstance(descriptor, dict):
        raise FullStoryComponentError(
            "COMPDATA battle-line menu descriptor missing"
        )
    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    output_table = project_runtime_text_table(table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(table)
    )
    original_compdata = original_compdata_path.read_bytes()
    if original_decoded is None:
        original_decoded = decode(original_compdata)
    current_decoded = (
        workspace.view() if workspace is not None else decode(stored_compdata)
    )
    if (
        original_decoded.consumed != len(original_compdata)
        or current_decoded.consumed != len(stored_compdata)
        or len(original_decoded.output) != len(current_decoded.output)
    ):
        raise FullStoryComponentError(
            "COMPDATA battle-line archive decode drift"
        )
    original_menu = parse_menu_file(original_decoded.output, descriptor, table)
    original_by_id = {item.entry_id: item for item in original_menu.entries}
    replacements: dict[str, str] = {}
    accepted_current: dict[str, str] = {}
    selected_ids = []
    selected_offsets = []
    for ordinal, item in enumerate(entries):
        entry_id = f"menu/Compdata/00/{ordinal:04d}"
        source = original_by_id.get(entry_id)
        translation = _two_byte_visible_spaces(
            normalize_original_fullwidth_ascii(item["translation"])
        )
        if (
            item.get("id") != entry_id
            or source is None
            or source.section != "Battle Lines"
            or item.get("source_text_sha256")
            != sha256_bytes(source.text.encode("utf-8"))
            or not isinstance(item.get("glossary_refs"), list)
            or not source.target_offsets
            or _control_signature(source.text) != _control_signature(translation)
        ):
            raise FullStoryComponentError(
                f"COMPDATA battle-line source/corpus drift: {entry_id}"
            )
        selected_ids.append(entry_id)
        for offset in source.target_offsets:
            raw_offset = f"0x{offset:X}"
            previous = replacements.get(raw_offset)
            if previous is not None and previous != translation:
                raise FullStoryComponentError(
                    f"COMPDATA battle-line shared target conflict: {raw_offset}"
                )
            replacements[raw_offset] = translation
            accepted_current[raw_offset] = normalize_original_fullwidth_ascii(
                decode_text(current_decoded.output, offset, output_table).text
            )
            selected_offsets.append(offset)
    unique_offsets = set(selected_offsets)
    if (
        len(selected_ids) != expected.get("entry_count")
        or len(selected_offsets) != expected.get("target_occurrence_count")
        or len(unique_offsets) != expected.get("unique_target_count")
    ):
        raise FullStoryComponentError(
            "COMPDATA battle-line target inventory drift"
        )

    selected_id_set = set(selected_ids)
    target_owners: dict[int, set[str]] = {}
    for menu_entry in original_menu.entries:
        for offset in set(menu_entry.target_offsets):
            target_owners.setdefault(offset, set()).add(menu_entry.entry_id)
    shared_owners = {
        owner
        for offset in unique_offsets
        for owner in target_owners.get(offset, set())
        if owner not in selected_id_set
    }
    if len(shared_owners) != expected.get("shared_non_battle_owner_count"):
        raise FullStoryComponentError(
            "COMPDATA battle-line shared-owner drift"
        )

    rewritten, write_report = _apply_fixed_span_translations(
        current_decoded.output,
        original_decoded.output,
        replacements,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="COMPDATA battle lines",
        accepted_current_texts=accepted_current,
    )
    mismatches = []
    for raw_offset, expected_translation in replacements.items():
        offset = int(raw_offset, 16)
        actual = normalize_original_fullwidth_ascii(
            decode_text(rewritten, offset, output_table).text
        )
        if actual != expected_translation:
            mismatches.append((raw_offset, expected_translation, actual))
    if mismatches:
        raise FullStoryComponentError(
            "COMPDATA battle-line target-offset reread mismatch: "
            f"{mismatches[:10]!r}"
        )
    rebuilt = _commit_compdata_stage(
        stored_compdata,
        rewritten,
        current_decoded,
        codec,
        label="COMPDATA battle-line",
        workspace=workspace,
    )
    write_report.update(
        {
            "corpus_entry_count": len(entries),
            "target_occurrence_count": len(selected_offsets),
            "unique_target_count": len(unique_offsets),
            "shared_non_battle_owner_count": len(shared_owners),
            "shared_non_battle_owner_ids": sorted(shared_owners),
            "source_preimages_sha256_exact": True,
            "all_editorial_statuses_draft": True,
            "target_offset_reread_exact": True,
            "compdata_source_size": len(stored_compdata),
            "compdata_output_size": (
                None if workspace is not None else len(rebuilt)
            ),
            "compdata_sector_budget": codec["max_output_size"],
            "codec_round_trip_exact": workspace is None,
            "compression_deferred_to_workspace": workspace is not None,
            "reported_kejinan_retreat": {
                "id": "menu/Compdata/00/0216",
                "offset": "0x64100",
                "translation": replacements["0x64100"],
            },
        }
    )
    return rebuilt, write_report, corpus_path


def _apply_reviewed_weapon_names(
    stored_compdata: bytes,
    reference: dict,
    descriptor_path: Path,
    original_compdata_path: Path,
    font_manifest: dict,
    codec: dict,
    *,
    workspace: CompressedStreamWorkspace | None = None,
    original_decoded=None,
) -> tuple[bytes, dict, Path]:
    """Write the complete reviewed weapon corpus into original fixed spans."""

    if not isinstance(reference, dict):
        raise FullStoryComponentError("reviewed weapon configuration is invalid")
    corpus_path, corpus_data = _locked_file(
        reference.get("corpus"), label="reviewed weapon corpus"
    )
    document = json.loads(corpus_data.decode("utf-8"))
    entries = document.get("entries")
    expected = reference.get("expected")
    if (
        document.get("batch_id") != "v1-menu-weapons"
        or document.get("language") != "zh-Hans"
        or not isinstance(entries, list)
        or not isinstance(expected, dict)
        or len(entries) != expected.get("entry_count")
        or document.get("scope", {}).get("entry_count") != len(entries)
        or any(
            not isinstance(item, dict)
            or item.get("editorial_status") != "reviewed"
            or not isinstance(item.get("translation"), str)
            or not item["translation"]
            for item in entries
        )
    ):
        raise FullStoryComponentError("reviewed weapon corpus contract drift")

    descriptors = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor = next(
        (
            row
            for row in descriptors
            if isinstance(row, dict) and row.get("friendly_name") == "Compdata"
        ),
        None,
    )
    if not isinstance(descriptor, dict):
        raise FullStoryComponentError("reviewed weapon menu descriptor missing")
    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    output_table = project_runtime_text_table(table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(table)
    )
    original_compdata = original_compdata_path.read_bytes()
    if original_decoded is None:
        original_decoded = decode(original_compdata)
    current_decoded = (
        workspace.view() if workspace is not None else decode(stored_compdata)
    )
    if (
        original_decoded.consumed != len(original_compdata)
        or current_decoded.consumed != len(stored_compdata)
        or len(original_decoded.output) != len(current_decoded.output)
    ):
        raise FullStoryComponentError("reviewed weapon COMPDATA decode drift")
    original_menu = parse_menu_file(original_decoded.output, descriptor, table)
    original_by_id = {item.entry_id: item for item in original_menu.entries}
    replacements: dict[str, str] = {}
    accepted_current: dict[str, str] = {}
    selected_ids = []
    selected_offsets = []
    for ordinal, item in enumerate(entries):
        entry_id = f"menu/Compdata/02/{ordinal:04d}"
        source = original_by_id.get(entry_id)
        translation = _two_byte_visible_spaces(
            normalize_original_fullwidth_ascii(item["translation"])
        )
        if (
            item.get("id") != entry_id
            or source is None
            or item.get("source_text_sha256")
            != sha256_bytes(source.text.encode("utf-8"))
            or item.get("glossary_refs") is None
            or f"weapon/{ordinal:04d}" not in item["glossary_refs"]
            or not source.target_offsets
            or _control_signature(source.text) != _control_signature(translation)
        ):
            raise FullStoryComponentError(
                f"reviewed weapon source/corpus drift: {entry_id}"
            )
        selected_ids.append(entry_id)
        for offset in source.target_offsets:
            raw_offset = f"0x{offset:X}"
            previous = replacements.get(raw_offset)
            if previous is not None and previous != translation:
                raise FullStoryComponentError(
                    f"reviewed weapon shared target conflict: {raw_offset}"
                )
            replacements[raw_offset] = translation
            accepted_current[raw_offset] = normalize_original_fullwidth_ascii(
                decode_text(current_decoded.output, offset, output_table).text
            )
            selected_offsets.append(offset)
    unique_offsets = set(selected_offsets)
    if (
        len(selected_ids) != expected.get("entry_count")
        or len(selected_offsets) != expected.get("target_occurrence_count")
        or len(unique_offsets) != expected.get("unique_target_count")
    ):
        raise FullStoryComponentError("reviewed weapon target inventory drift")

    target_owners: dict[int, set[str]] = {}
    for menu_entry in original_menu.entries:
        for offset in set(menu_entry.target_offsets):
            target_owners.setdefault(offset, set()).add(menu_entry.entry_id)
    shared_owners = {
        owner
        for offset in unique_offsets
        for owner in target_owners.get(offset, set())
        if owner not in set(selected_ids)
    }
    if len(shared_owners) != expected.get("shared_nonweapon_owner_count"):
        raise FullStoryComponentError("reviewed weapon shared-owner drift")

    rewritten, write_report = _apply_fixed_span_translations(
        current_decoded.output,
        original_decoded.output,
        replacements,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="reviewed weapon names",
        accepted_current_texts=accepted_current,
    )
    # Output parser ordinals are not stable when two reviewed names become
    # identical (records 10 and 11 intentionally both use 终极豪烈特攻), because
    # the upstream menu format groups equal decoded text. Verify the source-
    # bound target offsets instead of pretending output ordinals are identity.
    mismatches = []
    for raw_offset, expected_translation in replacements.items():
        offset = int(raw_offset, 16)
        actual = normalize_original_fullwidth_ascii(
            decode_text(rewritten, offset, output_table).text
        )
        if actual != expected_translation:
            mismatches.append((raw_offset, expected_translation, actual))
    if mismatches:
        raise FullStoryComponentError(
            f"reviewed weapon target-offset reread mismatch: {mismatches[:10]!r}"
        )
    rebuilt = _commit_compdata_stage(
        stored_compdata,
        rewritten,
        current_decoded,
        codec,
        label="reviewed weapon COMPDATA",
        workspace=workspace,
    )
    write_report.update(
        {
            "corpus_entry_count": len(entries),
            "target_occurrence_count": len(selected_offsets),
            "unique_target_count": len(unique_offsets),
            "shared_nonweapon_owner_count": len(shared_owners),
            "shared_nonweapon_owner_ids": sorted(shared_owners),
            "source_preimages_sha256_exact": True,
            "all_editorial_statuses_reviewed": True,
            "target_offset_reread_exact": True,
            "compdata_source_size": len(stored_compdata),
            "compdata_output_size": (
                None if workspace is not None else len(rebuilt)
            ),
            "compdata_sector_budget": codec["max_output_size"],
            "codec_round_trip_exact": workspace is None,
            "compression_deferred_to_workspace": workspace is not None,
        }
    )
    return rebuilt, write_report, corpus_path


def _apply_srvc_battle_text(
    reference: dict,
    font_manifest: dict,
) -> tuple[bytes, bytes, dict, tuple[Path, Path, Path]]:
    if not isinstance(reference, dict):
        raise FullStoryComponentError("SRVC battle-text configuration is invalid")
    corpus_path, corpus_data = _locked_file(
        reference.get("corpus"), label="SRVC production corpus"
    )
    bin_path, source_bin = _locked_file(
        reference.get("original_bin"), label="original SRVC.BIN"
    )
    seg_path, source_seg = _locked_file(
        reference.get("original_seg"), label="original SRVC.SEG"
    )
    corpus = json.loads(corpus_data.decode("utf-8"))
    expected = reference.get("expected")
    policy = corpus.get("policy", {})
    entries = corpus.get("entries")
    if (
        corpus.get("corpus_id") != "srwz-srvc-battle-lines-zh-v1"
        or corpus.get("language") != "zh-Hans"
        or not isinstance(expected, dict)
        or not isinstance(entries, list)
        or len(entries) != expected.get("unique_text_count")
        or corpus.get("unique_text_count") != len(entries)
        or corpus.get("record_count") != expected.get("record_count")
        or policy.get("writeback_mode")
        != "compact_indexed_pool_within_original_chunk"
        or policy.get("preserve_seg_byte_exact") is not True
        or policy.get("preserve_index_structure_and_metadata_byte_exact")
        is not True
        or policy.get("rewrite_only_index_text_offsets") is not True
        or policy.get("preserve_unindexed_tails_byte_exact") is not True
        or policy.get("preserve_control_tokens") is not True
    ):
        raise FullStoryComponentError("SRVC production corpus contract drift")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    offsets = parse_seg_offsets(source_seg, len(source_bin))
    source_chunks = parse_srvc_archive(source_bin, offsets, table)
    source_records = [record for chunk in source_chunks for record in chunk.records]
    first_records: dict[str, object] = {}
    occurrence_counts: dict[str, int] = {}
    for record in source_records:
        first_records.setdefault(record.text, record)
        occurrence_counts[record.text] = occurrence_counts.get(record.text, 0) + 1
    ordered_source_texts = sorted(
        first_records,
        key=lambda text: (first_records[text].archive_text_start, text),
    )
    if (
        len(source_chunks) != expected.get("chunk_count")
        or sum(bool(chunk.records) for chunk in source_chunks)
        != expected.get("indexed_chunk_count")
        or sum(not chunk.records for chunk in source_chunks)
        != expected.get("zero_record_chunk_count")
        or len(source_records) != expected.get("record_count")
        or len(ordered_source_texts) != expected.get("unique_text_count")
        or sum(
            chunk.unindexed_tail_size for chunk in source_chunks if chunk.records
        )
        != expected.get("unindexed_tail_bytes")
    ):
        raise FullStoryComponentError("SRVC source inventory drift")

    translations: dict[str, str] = {}
    source_id_by_text: dict[str, str] = {}
    override_count = 0
    for index, (source_text, entry) in enumerate(zip(ordered_source_texts, entries)):
        entry_id = f"battle:{index:05d}"
        source_hash = sha256_bytes(source_text.encode("utf-8"))
        translation = entry.get("translation") if isinstance(entry, dict) else None
        if (
            not isinstance(entry, dict)
            or entry.get("id") != entry_id
            or entry.get("source_text_sha256") != source_hash
            or entry.get("occurrence_count") != occurrence_counts[source_text]
            or entry.get("editorial_status") != "reviewed"
            or not isinstance(translation, str)
            or not translation
            or not translation.startswith("“")
            or not translation.endswith("”")
            or "{" in translation
            or "}" in translation
            or "\n" in translation
            or translation.count("\\n") != source_text.count("\\n")
            or _control_signature(translation) != _control_signature(source_text)
        ):
            raise FullStoryComponentError(
                f"SRVC corpus entry or control-token drift: {entry_id}"
            )
        translations[source_text] = _two_byte_visible_spaces(translation)
        source_id_by_text[source_text] = entry_id
        override_count += int("production_override" in entry)

    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    output_table = project_runtime_text_table(table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(table)
    )
    try:
        output_bin, original_chunks, pool_report = rebuild_srvc_archive(
            source_bin,
            offsets,
            table,
            translations,
            encoding_overrides=encoding_overrides,
            parsed_chunks=source_chunks,
        )
        output_chunks = parse_srvc_archive_with_layout(
            output_bin, offsets, original_chunks, output_table
        )
    except (SrwzTextEncodeError, ValueError) as error:
        raise FullStoryComponentError(f"SRVC battle-text writeback failed: {error}") from error

    reread_count = 0
    for original, output in zip(original_chunks, output_chunks):
        if (
            original.archive_start != output.archive_start
            or original.archive_end != output.archive_end
            or original.text_record_count != output.text_record_count
            or original.text_index_start != output.text_index_start
            or original.text_pool_start != output.text_pool_start
            or original.header_field_1 != output.header_field_1
            or original.header_field_2 != output.header_field_2
            or [record.metadata for record in original.records]
            != [record.metadata for record in output.records]
        ):
            raise FullStoryComponentError(
                f"SRVC chunk structure drift: {original.chunk_index}"
            )
        if not original.records:
            if source_bin[original.archive_start : original.archive_end] != output_bin[
                original.archive_start : original.archive_end
            ]:
                raise FullStoryComponentError(
                    f"zero-record SRVC chunk changed: {original.chunk_index}"
                )
            continue
        original_tail_start = original.archive_start + original.indexed_text_end
        if (
            source_bin[original.archive_start : original.archive_start + original.text_index_start]
            != output_bin[original.archive_start : original.archive_start + original.text_index_start]
            or source_bin[original_tail_start : original.archive_end]
            != output_bin[original_tail_start : original.archive_end]
        ):
            raise FullStoryComponentError(
                f"SRVC non-indexed bytes changed: {original.chunk_index}"
            )
        for source_record, output_record in zip(original.records, output.records):
            metadata_start = (
                original.archive_start
                + original.text_index_start
                + source_record.record_index * 8
            )
            if source_bin[metadata_start : metadata_start + 4] != output_bin[
                metadata_start : metadata_start + 4
            ]:
                raise FullStoryComponentError(
                    f"SRVC metadata changed: {original.chunk_index}/"
                    f"{source_record.record_index}"
                )
            expected_translation = translations[source_record.text]
            if output_record.text != expected_translation:
                raise FullStoryComponentError(
                    "SRVC translated reread mismatch: "
                    f"{source_id_by_text[source_record.text]}"
                )
            reread_count += 1

    output_seg = source_seg
    report = {
        "corpus_id": corpus["corpus_id"],
        "unique_text_count": len(entries),
        "record_count": len(source_records),
        "production_override_count": override_count,
        "chunk_count": len(source_chunks),
        "indexed_chunk_count": sum(bool(chunk.records) for chunk in source_chunks),
        "zero_record_chunk_count": sum(not chunk.records for chunk in source_chunks),
        "unindexed_tail_bytes": sum(
            chunk.unindexed_tail_size for chunk in source_chunks if chunk.records
        ),
        "pool": pool_report,
        "translated_reread_count": reread_count,
        "translated_reread_exact": reread_count == len(source_records),
        "control_tokens_preserved": True,
        "record_budgets_preserved": pool_report["minimum_record_headroom"] >= 0,
        "chunk_boundaries_preserved": len(output_bin) == len(source_bin),
        "index_structure_preserved": True,
        "metadata_preserved_byte_exact": True,
        "unindexed_tails_preserved_byte_exact": True,
        "zero_record_chunks_preserved_byte_exact": True,
        "seg_preserved_byte_exact": output_seg == source_seg,
    }
    return output_bin, output_seg, report, (corpus_path, bin_path, seg_path)


def _render_title_glyph(
    glyph: bytes,
    *,
    output_width: int,
) -> bytes:
    if len(glyph) != 24 * 24:
        raise FullStoryComponentError("scenario title glyph geometry drift")
    if not 1 <= output_width <= 24:
        raise FullStoryComponentError("scenario title raster policy is invalid")
    crop_x = (24 - output_width) // 2
    output = bytearray(24 * output_width)
    for y in range(24):
        source_start = y * 24 + crop_x
        target_start = y * output_width
        output[target_start : target_start + output_width] = glyph[
            source_start : source_start + output_width
        ]
    return bytes(output)


def _signed_short(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=True)


def _write_signed_short(data: bytearray, offset: int, value: int) -> None:
    if not -0x8000 <= value <= 0x7FFF:
        raise FullStoryComponentError("scenario-select coordinate exceeds s16")
    data[offset : offset + 2] = value.to_bytes(2, "little", signed=True)


def _apply_scenario_description_layout(
    slps: bytes,
    raw_config: object,
) -> tuple[bytes, dict]:
    if not isinstance(raw_config, dict):
        raise FullStoryComponentError("scenario description layout is invalid")
    glyph_advance = raw_config.get("glyph_advance")
    target_center_twice = raw_config.get("target_center_twice")
    entries = raw_config.get("entries")
    if (
        not isinstance(glyph_advance, int)
        or glyph_advance <= 0
        or not isinstance(target_center_twice, int)
        or not isinstance(entries, list)
        or len(entries) != 2
    ):
        raise FullStoryComponentError("scenario description layout policy drift")

    output = bytearray(slps)
    reports = []
    changed_ranges = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise FullStoryComponentError("scenario description entry is invalid")
        try:
            label = entry["label"]
            record_offset = int(entry["record_offset"], 0)
            text_pointer = int(entry["text_pointer"], 0)
            expected_x = entry["expected_x"]
            target_x = entry["target_x"]
            expected_y = entry["expected_y"]
            source_character_count = entry["source_character_count"]
            target_character_count = entry["target_character_count"]
        except (KeyError, TypeError, ValueError) as error:
            raise FullStoryComponentError(
                "scenario description entry values are malformed"
            ) from error
        if (
            not isinstance(label, str)
            or not label
            or not all(
                isinstance(value, int)
                for value in (
                    expected_x,
                    target_x,
                    expected_y,
                    source_character_count,
                    target_character_count,
                )
            )
            or source_character_count <= 0
            or target_character_count <= 0
            or record_offset < 0
            or record_offset + 8 > len(slps)
        ):
            raise FullStoryComponentError(
                "scenario description entry values are invalid"
            )
        actual_pointer = int.from_bytes(
            slps[record_offset : record_offset + 4], "little"
        )
        actual_x = _signed_short(slps, record_offset + 4)
        actual_y = _signed_short(slps, record_offset + 6)
        if (
            actual_pointer != text_pointer
            or actual_x != expected_x
            or actual_y != expected_y
        ):
            raise FullStoryComponentError(
                f"scenario description source layout drift: {label}"
            )
        source_center_twice = (
            2 * expected_x + source_character_count * glyph_advance
        )
        output_center_twice = (
            2 * target_x + target_character_count * glyph_advance
        )
        if (
            source_center_twice != target_center_twice
            or output_center_twice != target_center_twice
        ):
            raise FullStoryComponentError(
                f"scenario description center contract drift: {label}"
            )
        _write_signed_short(output, record_offset + 4, target_x)
        changed_ranges.append((record_offset + 4, record_offset + 6))
        reports.append(
            {
                "label": label,
                "record_offset": record_offset,
                "text_pointer": text_pointer,
                "source_x": expected_x,
                "target_x": target_x,
                "y": expected_y,
                "source_character_count": source_character_count,
                "target_character_count": target_character_count,
                "visual_center_twice": output_center_twice,
            }
        )

    for offset, (before, after) in enumerate(zip(slps, output)):
        if before != after and not any(
            start <= offset < end for start, end in changed_ranges
        ):
            raise FullStoryComponentError(
                "scenario description patch changed bytes outside x coordinates"
            )
    for report in reports:
        reread_x = _signed_short(output, report["record_offset"] + 4)
        if reread_x != report["target_x"]:
            raise FullStoryComponentError("scenario description x reread failed")
    if {report["visual_center_twice"] for report in reports} != {
        target_center_twice
    }:
        raise FullStoryComponentError("scenario descriptions are not centered")
    return bytes(output), {
        "glyph_advance": glyph_advance,
        "target_center_twice": target_center_twice,
        "entries": reports,
        "centers_aligned": True,
        "slps_size_preserved": len(output) == len(slps),
        "changed_bytes_confined_to_x_coordinates": True,
        "reread_exact": True,
    }


def _apply_scenario_title_geometry(
    decoded: bytes,
    logical: bytes | bytearray,
    raw_config: object,
    *,
    tim2_offset: int,
    texture_y_bounds: tuple[int, int],
) -> tuple[bytes, dict]:
    if not isinstance(raw_config, dict):
        raise FullStoryComponentError("scenario title geometry is invalid")
    try:
        frame_base = int(raw_config["frame_base"], 0)
        frame_count = raw_config["frame_count"]
        frame_stride = int(raw_config["frame_stride"], 0)
        quad_size = int(raw_config["quad_size"], 0)
        target_center_twice = raw_config["target_visible_center_twice"]
        groups = raw_config["groups"]
    except (KeyError, TypeError, ValueError) as error:
        raise FullStoryComponentError(
            "scenario title geometry values are malformed"
        ) from error
    if (
        not isinstance(frame_count, int)
        or frame_count <= 0
        or frame_base < 0
        or frame_stride <= 0
        or quad_size != 0x18
        or frame_base + frame_count * frame_stride > tim2_offset
        or not isinstance(target_center_twice, int)
        or len(texture_y_bounds) != 2
        or texture_y_bounds[0] < 0
        or texture_y_bounds[1] > 256
        or texture_y_bounds[0] >= texture_y_bounds[1]
        or not isinstance(groups, list)
        or len(groups) != 2
    ):
        raise FullStoryComponentError("scenario title geometry policy drift")

    output = bytearray(decoded)
    x_coordinate_offsets = (2, 6, 10, 14)
    y_coordinate_offsets = (4, 8, 12, 16)
    group_reports = []
    changed_ranges = []
    for group in groups:
        if not isinstance(group, dict):
            raise FullStoryComponentError("scenario title group is invalid")
        label = group.get("label")
        x_shift = group.get("x_shift")
        quads = group.get("quads")
        if (
            not isinstance(label, str)
            or not label
            or not isinstance(x_shift, int)
            or not isinstance(quads, list)
            or len(quads) != 2
        ):
            raise FullStoryComponentError("scenario title group policy drift")
        quad_reports = []
        for quad in quads:
            if not isinstance(quad, dict):
                raise FullStoryComponentError("scenario title quad is invalid")
            try:
                relative_offset = int(quad["relative_offset"], 0)
                expected_x_bounds = tuple(quad["expected_x_bounds"])
                expected_y_bounds = tuple(quad["expected_y_bounds"])
                texture_x_bounds = tuple(quad["texture_x_bounds"])
            except (KeyError, TypeError, ValueError) as error:
                raise FullStoryComponentError(
                    "scenario title quad values are malformed"
                ) from error
            if (
                len(expected_x_bounds) != 2
                or len(expected_y_bounds) != 2
                or len(texture_x_bounds) != 2
                or not all(
                    isinstance(value, int)
                    for value in (
                        *expected_x_bounds,
                        *expected_y_bounds,
                        *texture_x_bounds,
                    )
                )
                or relative_offset < 0
                or relative_offset + quad_size > frame_stride
                or texture_x_bounds[0] < 0
                or texture_x_bounds[1] > 256
                or texture_x_bounds[0] >= texture_x_bounds[1]
            ):
                raise FullStoryComponentError(
                    "scenario title quad values are invalid"
                )
            for frame_index in range(frame_count):
                quad_offset = (
                    frame_base + frame_index * frame_stride + relative_offset
                )
                xs = tuple(
                    _signed_short(decoded, quad_offset + item)
                    for item in x_coordinate_offsets
                )
                ys = tuple(
                    _signed_short(decoded, quad_offset + item)
                    for item in y_coordinate_offsets
                )
                if (
                    (min(xs), max(xs)) != expected_x_bounds
                    or (min(ys), max(ys)) != expected_y_bounds
                    or max(xs) - min(xs)
                    != texture_x_bounds[1] - texture_x_bounds[0]
                ):
                    raise FullStoryComponentError(
                        "scenario title quad source geometry drift: "
                        f"{label} frame {frame_index}"
                    )
                for item in x_coordinate_offsets:
                    coordinate_offset = quad_offset + item
                    _write_signed_short(
                        output,
                        coordinate_offset,
                        _signed_short(decoded, coordinate_offset) + x_shift,
                    )
                    changed_ranges.append(
                        (coordinate_offset, coordinate_offset + 2)
                    )
            shifted_x_bounds = (
                expected_x_bounds[0] + x_shift,
                expected_x_bounds[1] + x_shift,
            )
            texture_start, texture_end = texture_x_bounds
            ink_xs = [
                x
                for y in range(texture_y_bounds[0], texture_y_bounds[1])
                for x in range(texture_start, texture_end)
                if logical[y * 256 + x]
            ]
            if not ink_xs:
                raise FullStoryComponentError(
                    f"scenario title quad texture is blank: {label}"
                )
            ink_bounds = (min(ink_xs), max(ink_xs))
            visible_bounds = (
                shifted_x_bounds[0] + ink_bounds[0] - texture_start,
                shifted_x_bounds[0] + ink_bounds[1] - texture_start,
            )
            quad_reports.append(
                {
                    "relative_offset": relative_offset,
                    "source_x_bounds": list(expected_x_bounds),
                    "target_x_bounds": list(shifted_x_bounds),
                    "y_bounds": list(expected_y_bounds),
                    "texture_x_bounds": list(texture_x_bounds),
                    "ink_x_bounds": list(ink_bounds),
                    "visible_x_bounds": list(visible_bounds),
                }
            )
        visible_min = min(item["visible_x_bounds"][0] for item in quad_reports)
        visible_max = max(item["visible_x_bounds"][1] for item in quad_reports)
        visible_center_twice = visible_min + visible_max
        if visible_center_twice != target_center_twice:
            raise FullStoryComponentError(
                f"scenario title visual center drift: {label}"
            )
        group_reports.append(
            {
                "label": label,
                "x_shift": x_shift,
                "visible_x_bounds": [visible_min, visible_max],
                "visible_center_twice": visible_center_twice,
                "quads": quad_reports,
            }
        )

    for offset, (before, after) in enumerate(zip(decoded, output)):
        if before != after and not any(
            start <= offset < end for start, end in changed_ranges
        ):
            raise FullStoryComponentError(
                "scenario title geometry changed bytes outside x coordinates"
            )
    if {
        report["visible_center_twice"] for report in group_reports
    } != {target_center_twice}:
        raise FullStoryComponentError("scenario titles are not centered")
    return bytes(output), {
        "frame_count": frame_count,
        "frame_base": frame_base,
        "frame_stride": frame_stride,
        "quad_size": quad_size,
        "target_visible_center_twice": target_center_twice,
        "groups": group_reports,
        "patched_quad_count": frame_count
        * sum(len(group["quads"]) for group in groups),
        "centers_aligned": True,
        "changed_bytes_confined_to_x_coordinates": True,
    }


def _apply_nisv_effect_names(
    slps: bytes,
    font_manifest: dict,
    raw_config: object,
) -> tuple[bytes, dict, tuple[Path, Path]]:
    """Replace the duplicated weapon-effect labels in NisVData chunk 6."""

    if not isinstance(raw_config, dict):
        raise FullStoryComponentError("NisVData effect-name config is invalid")
    translations_path, translations_data = _locked_file(
        raw_config.get("translations"),
        label="NisVData effect-name translations",
    )
    archive_path, archive = _locked_file(
        raw_config.get("original_archive"),
        label="original NisVData.bin",
    )
    archive_spec = raw_config.get("archive")
    target = raw_config.get("target")
    expected = raw_config.get("expected")
    codec = raw_config.get("codec")
    if not all(
        isinstance(value, dict)
        for value in (archive_spec, target, expected, codec)
    ):
        raise FullStoryComponentError("NisVData effect-name contract is incomplete")
    document = json.loads(translations_data.decode("utf-8"))
    terms = document.get("nisv_effect_names")
    if (
        not isinstance(terms, list)
        or len(terms) != expected.get("term_count")
        or sum(
            len(item.get("decoded_offsets", []))
            for item in terms
            if isinstance(item, dict)
        )
        != expected.get("occurrence_count")
        or codec.get("strategy") != "rust-fit"
    ):
        raise FullStoryComponentError("NisVData effect-name selection drift")
    try:
        spec = ExecutableOffsetSpec(
            name=archive_spec["name"],
            member=archive_spec["member"],
            table_start=int(archive_spec["table_start"], 0),
            table_end=int(archive_spec["table_end"], 0),
        )
        chunk_index = target["chunk_index"]
    except (KeyError, TypeError, ValueError) as error:
        raise FullStoryComponentError(
            "NisVData effect-name values are malformed"
        ) from error
    if (
        archive_spec.get("storage") != "srwz_stream"
        or archive_spec.get("alignment") != 16
        or not isinstance(chunk_index, int)
    ):
        raise FullStoryComponentError("NisVData archive policy drift")
    offsets = read_executable_archive_offsets(slps, spec, len(archive))
    if not 0 <= chunk_index < len(offsets) - 1:
        raise FullStoryComponentError("NisVData target chunk is missing")
    chunk_start, chunk_end = offsets[chunk_index : chunk_index + 2]
    stored = archive[chunk_start:chunk_end]
    if (
        chunk_start != target.get("stored_start")
        or chunk_end != target.get("stored_end")
        or len(stored) != target.get("stored_size")
        or sha256_bytes(stored) != target.get("stored_sha256")
    ):
        raise FullStoryComponentError("NisVData stored chunk lock drift")
    decoded = decode(stored)
    if (
        decoded.consumed != target.get("stored_consumed")
        or any(stored[decoded.consumed :])
        or len(decoded.output) != target.get("decoded_size")
        or sha256_bytes(decoded.output) != target.get("decoded_sha256")
    ):
        raise FullStoryComponentError("NisVData decoded chunk lock drift")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    fullwidth_space = encode_text(
        "\u3000",
        table,
        overrides=encoding_overrides,
        terminate=False,
    )
    if len(fullwidth_space) != 2:
        raise FullStoryComponentError("NisVData padding glyph drift")
    output_decoded = bytearray(decoded.output)
    changed_ranges = []
    term_reports = []
    for item in terms:
        if not isinstance(item, dict):
            raise FullStoryComponentError("NisVData effect-name entry is invalid")
        source = item.get("source")
        translation = item.get("translation")
        raw_offsets = item.get("decoded_offsets")
        if (
            not isinstance(source, str)
            or not source
            or not isinstance(translation, str)
            or not translation
            or not isinstance(raw_offsets, list)
            or not raw_offsets
        ):
            raise FullStoryComponentError("NisVData effect-name entry drift")
        translation = normalize_original_fullwidth_ascii(translation)
        source_encoded = encode_text(source, table, terminate=False)
        translated_encoded = encode_text(
            translation,
            table,
            overrides=encoding_overrides,
            terminate=False,
        )
        headroom = len(source_encoded) - len(translated_encoded)
        if headroom < 0 or headroom % len(fullwidth_space):
            raise FullStoryComponentError(
                f"NisVData effect-name overflow: {source!r}"
            )
        replacement = translated_encoded + fullwidth_space * (
            headroom // len(fullwidth_space)
        )
        expected_offsets = [int(value, 0) for value in raw_offsets]
        actual_offsets = []
        cursor = 0
        while True:
            cursor = decoded.output.find(source_encoded, cursor)
            if cursor < 0:
                break
            actual_offsets.append(cursor)
            cursor += 1
        if actual_offsets != expected_offsets:
            raise FullStoryComponentError(
                f"NisVData effect-name occurrence drift: {source!r}"
            )
        for offset in expected_offsets:
            end = offset + len(source_encoded)
            if bytes(output_decoded[offset:end]) != source_encoded:
                raise FullStoryComponentError(
                    f"NisVData effect-name preimage drift at 0x{offset:X}"
                )
            output_decoded[offset:end] = replacement
            changed_ranges.append((offset, end))
        term_reports.append(
            {
                "source": source,
                "translation": translation,
                "decoded_offsets": expected_offsets,
                "source_encoded_size": len(source_encoded),
                "translation_encoded_size": len(translated_encoded),
                "fullwidth_padding_count": headroom // len(fullwidth_space),
            }
        )
    for offset, (before, after) in enumerate(
        zip(decoded.output, output_decoded)
    ):
        if before != after and not any(
            start <= offset < end for start, end in changed_ranges
        ):
            raise FullStoryComponentError(
                "NisVData changed bytes outside effect-name spans"
            )
    try:
        rebuilt = reencode_changed_suffix(
            stored[: decoded.consumed],
            bytes(output_decoded),
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=len(stored),
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"NisVData Rust compression failed: {error}"
        ) from error
    round_trip = decode(rebuilt)
    if (
        round_trip.consumed != len(rebuilt)
        or round_trip.output != bytes(output_decoded)
        or round_trip.flags != decoded.flags
    ):
        raise FullStoryComponentError("NisVData codec round trip failed")
    padded = rebuilt + bytes(len(stored) - len(rebuilt))
    output_archive = archive[:chunk_start] + padded + archive[chunk_end:]
    if (
        len(output_archive) != len(archive)
        or output_archive[:chunk_start] != archive[:chunk_start]
        or output_archive[chunk_end:] != archive[chunk_end:]
        or read_executable_archive_offsets(slps, spec, len(output_archive))
        != offsets
    ):
        raise FullStoryComponentError("NisVData archive layout changed")
    reread = decode(output_archive[chunk_start:chunk_end])
    if (
        reread.output != bytes(output_decoded)
        or any(output_archive[chunk_start + reread.consumed : chunk_end])
    ):
        raise FullStoryComponentError("NisVData archive reread failed")
    return output_archive, {
        "member": archive_spec["member"],
        "chunk_index": chunk_index,
        "terms": term_reports,
        "term_count": len(term_reports),
        "occurrence_count": sum(
            len(item["decoded_offsets"]) for item in term_reports
        ),
        "source_stored_size": len(stored),
        "output_encoded_size": len(rebuilt),
        "output_padding_size": len(stored) - len(rebuilt),
        "codec": dict(codec),
        "archive_size_preserved": True,
        "archive_offsets_preserved": True,
        "non_target_chunks_preserved_byte_exact": True,
        "fullwidth_space_padding_only": True,
        "translated_reread_exact": True,
    }, (translations_path, archive_path)


def _apply_scenario_select_effect(
    slps: bytes,
    final_font: bytes,
    release_by_character: dict,
    raw_config: object,
    *,
    archive_payload: bytes | None = None,
) -> tuple[bytes, dict, Path]:
    if not isinstance(raw_config, dict):
        raise FullStoryComponentError("scenario-select effect config is invalid")
    archive_path, original_archive = _locked_file(
        raw_config.get("original_archive"),
        label="original VEFF2DX.BIN",
    )
    archive = original_archive if archive_payload is None else archive_payload
    if len(archive) != len(original_archive):
        raise FullStoryComponentError("VEFF2DX archive size drift")
    archive_spec = raw_config.get("archive")
    target = raw_config.get("target")
    raster = raw_config.get("raster")
    geometry = raw_config.get("geometry")
    if not all(
        isinstance(value, dict)
        for value in (archive_spec, target, raster, geometry)
    ):
        raise FullStoryComponentError("scenario-select effect contract is incomplete")
    try:
        offset_spec = ExecutableOffsetSpec(
            name=archive_spec["name"],
            member=archive_spec["member"],
            table_start=int(archive_spec["table_start"], 0),
            table_end=int(archive_spec["table_end"], 0),
        )
        chunk_index = target["chunk_index"]
        record_index = target["record_index"]
        picture_index = target["picture_index"]
        clear_x = raster["clear_x"]
        clear_y = raster["clear_y"]
        clear_width = raster["clear_width"]
        clear_height = raster["clear_height"]
        glyph_sampling = raster["glyph_sampling"]
        segments = raster["segments"]
    except (KeyError, TypeError, ValueError) as error:
        raise FullStoryComponentError(
            "scenario-select effect values are malformed"
        ) from error
    if (
        archive_spec.get("storage") != "srwz_stream"
        or archive_spec.get("alignment") != 16
        or not isinstance(chunk_index, int)
        or not isinstance(record_index, int)
        or picture_index != 0
        or not all(
            isinstance(value, int)
            for value in (
                clear_x,
                clear_y,
                clear_width,
                clear_height,
            )
        )
        or glyph_sampling != "native_24px_center_crop_preserve_4bpp"
        or not isinstance(segments, list)
        or not segments
    ):
        raise FullStoryComponentError("scenario-select effect policy drift")

    offsets = read_executable_archive_offsets(slps, offset_spec, len(archive))
    if not 0 <= chunk_index < len(offsets) - 1:
        raise FullStoryComponentError("scenario-select chunk index is outside archive")
    chunk_start = offsets[chunk_index]
    chunk_end = offsets[chunk_index + 1]
    stored = archive[chunk_start:chunk_end]
    if (
        chunk_start != target.get("stored_start")
        or chunk_end != target.get("stored_end")
        or len(stored) != target.get("stored_size")
        or sha256_bytes(stored) != target.get("stored_sha256")
    ):
        raise FullStoryComponentError("scenario-select stored chunk lock drift")
    decoded_result = decode(stored)
    decoded = decoded_result.output
    if (
        decoded_result.consumed != target.get("stored_consumed")
        or any(stored[decoded_result.consumed :])
        or len(decoded) != target.get("decoded_size")
        or sha256_bytes(decoded) != target.get("decoded_sha256")
    ):
        raise FullStoryComponentError("scenario-select decoded chunk lock drift")

    records = scan_tim2(decoded)
    if not 0 <= record_index < len(records):
        raise FullStoryComponentError("scenario-select TIM2 record is missing")
    record = records[record_index]
    record_bytes = decoded[record.offset : record.end]
    if (
        record.offset != target.get("record_offset")
        or record.size != target.get("record_size")
        or sha256_bytes(record_bytes) != target.get("record_sha256")
        or not 0 <= picture_index < len(record.pictures)
    ):
        raise FullStoryComponentError("scenario-select TIM2 record lock drift")
    picture = record.pictures[picture_index]
    if (
        picture.width != 256
        or picture.height != 256
        or picture.image_type != 4
        or picture.image_size != 32768
    ):
        raise FullStoryComponentError("scenario-select picture layout drift")
    image_start = picture.offset + picture.header_size
    image_end = image_start + picture.image_size
    logical = bytearray(unswizzle_psmt4(decoded[image_start:image_end]))
    if sha256_bytes(logical) != target.get("logical_image_sha256"):
        raise FullStoryComponentError("scenario-select logical image lock drift")
    if (
        clear_x < 0
        or clear_y < 0
        or clear_width <= 0
        or clear_height <= 0
        or clear_x + clear_width > 256
        or clear_y + clear_height > 256
    ):
        raise FullStoryComponentError("scenario-select clear rectangle is invalid")
    for y in range(clear_y, clear_y + clear_height):
        start = y * 256 + clear_x
        logical[start : start + clear_width] = bytes(clear_width)

    rendered_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise FullStoryComponentError("scenario title segment is invalid")
        text = segment.get("text")
        x = segment.get("x")
        y = segment.get("y")
        output_width = segment.get("glyph_width")
        advance = segment.get("advance")
        if (
            not isinstance(text, str)
            or not text
            or not all(isinstance(value, int) for value in (x, y, output_width, advance))
        ):
            raise FullStoryComponentError("scenario title segment values are invalid")
        origin_x = x
        glyph_reports = []
        for character in text:
            mapping = release_by_character.get(character)
            if (
                not isinstance(mapping, tuple)
                or len(mapping) != 2
                or not isinstance(mapping[1], int)
            ):
                raise FullStoryComponentError(
                    f"scenario title glyph mapping is missing: {character!r}"
                )
            glyph = decode_glyph(final_font, mapping[1])
            rendered = _render_title_glyph(
                glyph,
                output_width=output_width,
            )
            if x < 0 or y < 0 or x + output_width > 256 or y + 24 > 256:
                raise FullStoryComponentError("scenario title segment exceeds texture")
            for row in range(24):
                start = (y + row) * 256 + x
                source_start = row * output_width
                logical[start : start + output_width] = rendered[
                    source_start : source_start + output_width
                ]
            glyph_reports.append(
                {
                    "character": character,
                    "glyph_index": mapping[1],
                    "ink_pixel_count": sum(bool(pixel) for pixel in rendered),
                    "intermediate_pixel_count": sum(
                        0 < pixel < 15 for pixel in rendered
                    ),
                    "native_height_preserved": True,
                }
            )
            x += advance
        rendered_segments.append(
            {
                "text": text,
                "x": origin_x,
                "y": y,
                "glyph_width": output_width,
                "advance": advance,
                "glyphs": glyph_reports,
            }
        )

    if geometry.get("enabled") is False:
        geometry_decoded = decoded
        geometry_report = {
            "enabled": False,
            "layout_bytes_preserved": True,
            "reason": geometry.get("reason"),
        }
    else:
        geometry_decoded, geometry_report = _apply_scenario_title_geometry(
            decoded,
            logical,
            geometry,
            tim2_offset=record.offset,
            texture_y_bounds=(clear_y, clear_y + clear_height),
        )
    packed = swizzle_psmt4(logical)
    if unswizzle_psmt4(packed) != logical:
        raise FullStoryComponentError("scenario-select PSMT4 round trip failed")
    modified_decoded = (
        geometry_decoded[:image_start]
        + packed
        + geometry_decoded[image_end:]
    )
    codec_strategy = raw_config.get("codec_strategy")
    codec_max_match_chain = raw_config.get("codec_max_match_chain")
    if (
        codec_strategy != "rust-fit"
        or not isinstance(codec_max_match_chain, int)
        or codec_max_match_chain <= 0
    ):
        raise FullStoryComponentError(
            "scenario-select Rust codec policy is invalid"
        )
    encoded = encode(
        modified_decoded,
        strategy=codec_strategy,
        max_match_chain=codec_max_match_chain,
        max_output_size=len(stored),
    )
    reread = decode(encoded)
    if reread.consumed != len(encoded) or reread.output != modified_decoded:
        raise FullStoryComponentError("scenario-select codec round trip failed")
    padded = encoded + bytes(len(stored) - len(encoded))
    output_archive = archive[:chunk_start] + padded + archive[chunk_end:]
    if len(output_archive) != len(archive):
        raise FullStoryComponentError("scenario-select archive size changed")
    if (
        output_archive[:chunk_start] != archive[:chunk_start]
        or output_archive[chunk_end:] != archive[chunk_end:]
    ):
        raise FullStoryComponentError("non-target VEFF2DX bytes changed")
    reread_stored = output_archive[chunk_start:chunk_end]
    reread_decoded = decode(reread_stored)
    reread_records = scan_tim2(reread_decoded.output)
    reread_picture = reread_records[record_index].pictures[picture_index]
    reread_image_start = reread_picture.offset + reread_picture.header_size
    reread_image_end = reread_image_start + reread_picture.image_size
    reread_logical = unswizzle_psmt4(
        reread_decoded.output[reread_image_start:reread_image_end]
    )
    if reread_logical != logical or any(reread_stored[reread_decoded.consumed :]):
        raise FullStoryComponentError("scenario-select archive reread failed")
    composed_labels = raw_config.get("composed_labels")
    if (
        not isinstance(composed_labels, list)
        or not composed_labels
        or not all(isinstance(label, str) and label for label in composed_labels)
    ):
        raise FullStoryComponentError("scenario composed labels are invalid")
    report = {
        "member": archive_spec["member"],
        "effect_id": target.get("effect_id"),
        "chunk_index": chunk_index,
        "record_index": record_index,
        "picture_index": picture_index,
        "labels": [segment["text"] for segment in rendered_segments],
        "composed_labels": composed_labels,
        "glyph_sampling": glyph_sampling,
        "segments": rendered_segments,
        "source_logical_image_sha256": target["logical_image_sha256"],
        "output_logical_image_sha256": sha256_bytes(logical),
        "changed_logical_pixel_count": sum(
            before != after
            for before, after in zip(
                unswizzle_psmt4(decoded[image_start:image_end]),
                logical,
            )
        ),
        "source_stored_size": len(stored),
        "encoded_size": len(encoded),
        "codec": {
            "strategy": codec_strategy,
            "max_match_chain": codec_max_match_chain,
        },
        "padding_size": len(stored) - len(encoded),
        "archive_size_preserved": True,
        "archive_offsets_preserved": True,
        "non_target_archive_bytes_exact": True,
        "psmt4_round_trip_exact": True,
        "codec_round_trip_exact": True,
        "translated_reread_exact": True,
        "all_glyphs_native_height_and_antialiased": all(
            glyph["native_height_preserved"]
            and glyph["intermediate_pixel_count"] > 0
            for segment in rendered_segments
            for glyph in segment["glyphs"]
        ),
        "geometry": geometry_report,
    }
    return output_archive, report, archive_path


def _apply_auto_demo_overlays(
    slps: bytes,
    raw_config: object,
    font_manifest: dict,
) -> tuple[bytes, dict[str, bytes], dict, dict[str, Path]]:
    """Localize the title-idle work title and speaker-name overlays."""

    if not isinstance(raw_config, dict):
        raise FullStoryComponentError("auto-demo overlay config is invalid")
    title_corpus_path, title_corpus_data = _locked_file(
        raw_config.get("title_corpus"),
        label="auto-demo work-title corpus",
    )
    original_slps_path, original_slps = _locked_file(
        raw_config.get("original_slps"),
        label="auto-demo original SLPS",
    )
    story_speaker_path, story_speaker_data = _locked_file(
        raw_config.get("story_speakers"),
        label="auto-demo canonical story speakers",
    )
    residual_name_path, residual_name_data = _locked_file(
        raw_config.get("residual_names"),
        label="auto-demo residual display names",
    )
    unit_name_path, unit_name_data = _locked_file(
        raw_config.get("unit_names"),
        label="auto-demo canonical work titles",
    )
    expected = raw_config.get("expected")
    archives = raw_config.get("battle_archives")
    if not isinstance(expected, dict) or not isinstance(archives, list):
        raise FullStoryComponentError("auto-demo overlay contract is incomplete")
    if expected.get("name_field_capacity") != 20:
        raise FullStoryComponentError("auto-demo name-field capacity drift")

    title_corpus = json.loads(title_corpus_data.decode("utf-8"))
    title_entries = title_corpus.get("entries")
    unit_names = json.loads(unit_name_data.decode("utf-8"))
    unit_segments = unit_names.get("segments")
    if (
        title_corpus.get("language") != "zh-Hans"
        or title_corpus.get("scope", {}).get("surface")
        != "title-idle-auto-demo"
        or not isinstance(title_entries, list)
        or len(title_entries) != expected.get("title_entry_count")
        or not isinstance(unit_segments, list)
    ):
        raise FullStoryComponentError("auto-demo work-title corpus drift")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    output_table = project_runtime_text_table(table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(table)
    )

    output_slps = bytearray(slps)
    title_reports = []
    title_ranges = []
    for ordinal, entry in enumerate(title_entries):
        if not isinstance(entry, dict):
            raise FullStoryComponentError("auto-demo work-title entry is invalid")
        entry_id = f"auto-demo/title/{ordinal:02d}"
        try:
            offset = int(entry["offset"], 0)
            capacity = entry["capacity"]
        except (KeyError, TypeError, ValueError) as error:
            raise FullStoryComponentError(
                f"auto-demo work-title location is malformed: {entry_id}"
            ) from error
        source_text = entry.get("source_text")
        translation = entry.get("translation")
        translation_source = entry.get("translation_source")
        if (
            entry.get("id") != entry_id
            or entry.get("editorial_status") != "reviewed"
            or not isinstance(capacity, int)
            or capacity <= 0
            or not isinstance(source_text, str)
            or not source_text
            or not isinstance(translation, str)
            or not translation
            or entry.get("source_text_sha256")
            != sha256_bytes(source_text.encode("utf-8"))
            or offset < 0
            or offset + capacity > len(original_slps)
        ):
            raise FullStoryComponentError(
                f"auto-demo work-title entry drift: {entry_id}"
            )
        if isinstance(translation_source, str) and translation_source.startswith(
            "units-full:segment/"
        ):
            try:
                segment_index = int(translation_source.rsplit("/", 1)[1])
                canonical_title = unit_segments[segment_index]["work"]
            except (IndexError, KeyError, TypeError, ValueError) as error:
                raise FullStoryComponentError(
                    f"auto-demo work-title source is invalid: {entry_id}"
                ) from error
            if translation != canonical_title:
                raise FullStoryComponentError(
                    f"auto-demo work title differs from unit corpus: {entry_id}"
                )
        elif translation_source != "project-work-title":
            raise FullStoryComponentError(
                f"auto-demo work-title provenance drift: {entry_id}"
            )
        source_span = original_slps[offset : offset + capacity]
        terminator = source_span.find(b"\0")
        try:
            reread_source = source_span[:terminator].decode("cp932")
        except UnicodeDecodeError as error:
            raise FullStoryComponentError(
                f"auto-demo work-title source cannot decode: {entry_id}"
            ) from error
        if (
            terminator <= 0
            or any(source_span[terminator:])
            or reread_source != source_text
            or sha256_bytes(source_span) != entry.get("source_span_sha256")
            or slps[offset : offset + capacity] != source_span
        ):
            raise FullStoryComponentError(
                f"auto-demo work-title preimage drift: {entry_id}"
            )
        stored_translation = _two_byte_visible_spaces(translation)
        encoded = encode_text(
            stored_translation,
            table,
            overrides=encoding_overrides,
            terminate=True,
        )
        if len(encoded) > capacity:
            raise FullStoryComponentError(
                f"auto-demo work-title overflow: {entry_id} "
                f"({len(encoded)} > {capacity})"
            )
        output_slps[offset : offset + capacity] = encoded + bytes(
            capacity - len(encoded)
        )
        reread = decode_text(bytes(output_slps), offset, output_table).text
        if reread != stored_translation:
            raise FullStoryComponentError(
                f"auto-demo work-title reread mismatch: {entry_id}"
            )
        title_ranges.append((offset, offset + capacity))
        title_reports.append(
            {
                "id": entry_id,
                "offset": offset,
                "capacity": capacity,
                "source_text": source_text,
                "translation": translation,
                "stored_translation": stored_translation,
                "translation_source": translation_source,
                "encoded_size": len(encoded),
                "headroom": capacity - len(encoded),
            }
        )
    for offset, (before, after) in enumerate(zip(slps, output_slps)):
        if before != after and not any(
            start <= offset < end for start, end in title_ranges
        ):
            raise FullStoryComponentError(
                "auto-demo work titles changed bytes outside fixed spans"
            )

    story_speakers = json.loads(story_speaker_data.decode("utf-8"))
    speaker_entries = story_speakers.get("entries")
    residual_names = json.loads(residual_name_data.decode("utf-8")).get(
        "display_names_by_source_text"
    )
    if not isinstance(speaker_entries, list) or not isinstance(
        residual_names, dict
    ):
        raise FullStoryComponentError("auto-demo canonical name sources drift")
    translation_by_hash: dict[str, str] = {}
    for entry in speaker_entries:
        if not isinstance(entry, dict):
            raise FullStoryComponentError("story-speaker entry is invalid")
        source_hash = entry.get("source_text_sha256")
        translation = entry.get("translation")
        if not isinstance(source_hash, str) or not isinstance(translation, str):
            raise FullStoryComponentError("story-speaker entry drift")
        previous = translation_by_hash.setdefault(source_hash, translation)
        if previous != translation:
            raise FullStoryComponentError(
                f"story-speaker canonical translation conflicts: {source_hash}"
            )

    output_archives = {}
    archive_reports = []
    input_paths: dict[str, Path] = {
        "title_corpus": title_corpus_path,
        "original_slps": original_slps_path,
        "story_speakers": story_speaker_path,
        "residual_names": residual_name_path,
        "unit_names": unit_name_path,
    }
    all_name_sources = set()
    total_name_slots = 0
    for archive in archives:
        if not isinstance(archive, dict):
            raise FullStoryComponentError("auto-demo archive entry is invalid")
        member = archive.get("member")
        expected_slot_count = archive.get("expected_name_slot_count")
        if (
            not isinstance(member, str)
            or not member.startswith("BTL/OP")
            or not member.endswith(".BIN")
            or not isinstance(expected_slot_count, int)
        ):
            raise FullStoryComponentError("auto-demo archive contract drift")
        source_path, source_payload = _locked_file(
            archive.get("source"), label=f"auto-demo {member}"
        )
        seg_path, source_seg = _locked_file(
            archive.get("seg"), label=f"auto-demo {member[:-4]}.SEG"
        )

        # Resolve only the names actually present in this locked archive.  The
        # preferred source is the story-speaker corpus; generic enemy/unit
        # labels fall back to the existing residual display-name mapping.
        from_hash = {}
        from_residual = {}
        for source_text in residual_names:
            if not isinstance(source_text, str):
                raise FullStoryComponentError("residual display-name key drift")
        translations = {}
        try:
            discovered = discover_auto_demo_name_slots(source_payload, source_seg)
        except AutoDemoError as error:
            raise FullStoryComponentError(
                f"auto-demo discovery failed for {member}: {error}"
            ) from error
        for slot in discovered:
            source_hash = sha256_bytes(slot.source_text.encode("utf-8"))
            translation = translation_by_hash.get(source_hash)
            if translation is not None:
                from_hash[slot.source_text] = translation
            else:
                translation = residual_names.get(slot.source_text)
                if translation is not None:
                    from_residual[slot.source_text] = translation
            if not isinstance(translation, str) or not translation:
                raise FullStoryComponentError(
                    f"auto-demo canonical name is missing: {slot.source_text!r}"
                )
            translations[slot.source_text] = _two_byte_visible_spaces(
                normalize_original_fullwidth_ascii(translation)
            )
        try:
            output_payload, name_reports = rewrite_auto_demo_names(
                source_payload,
                source_seg,
                translations,
                table,
                encoding_overrides=encoding_overrides,
                output_table=output_table,
                expected_slot_count=expected_slot_count,
            )
        except (AutoDemoError, SrwzTextEncodeError) as error:
            raise FullStoryComponentError(
                f"auto-demo name writeback failed for {member}: {error}"
            ) from error
        output_archives[member] = output_payload
        input_paths[f"original_{Path(member).stem.lower()}_bin"] = source_path
        input_paths[f"original_{Path(member).stem.lower()}_seg"] = seg_path
        sources = {item["source_text"] for item in name_reports}
        all_name_sources.update(sources)
        total_name_slots += len(name_reports)
        archive_reports.append(
            {
                "member": member,
                "name_slot_count": len(name_reports),
                "unique_name_source_count": len(sources),
                "story_speaker_source_count": len(from_hash),
                "residual_display_name_source_count": len(from_residual),
                "names": name_reports,
                "archive_size_preserved": len(output_payload)
                == len(source_payload),
                "seg_preserved_byte_exact": True,
                "translated_reread_exact": True,
            }
        )
    if (
        total_name_slots != expected.get("name_slot_count")
        or len(all_name_sources) != expected.get("unique_name_source_count")
    ):
        raise FullStoryComponentError("auto-demo name inventory drift")
    report = {
        "title_entry_count": len(title_reports),
        "titles": title_reports,
        "name_slot_count": total_name_slots,
        "unique_name_source_count": len(all_name_sources),
        "archives": archive_reports,
        "work_titles_reused_from_existing_corpus": True,
        "names_reused_from_existing_corpora": True,
        "fixed_spans_preserved": True,
        "archive_sizes_preserved": True,
        "seg_files_preserved_byte_exact": True,
        "translated_reread_exact": True,
    }
    return bytes(output_slps), output_archives, report, input_paths


def _build_incremental_fixed_slps(
    *,
    config_path: Path,
    config: dict,
    output_root: Path,
    prior_report: dict,
    baseline_remaining_ui: dict,
    current_remaining_ui: dict,
) -> tuple[dict[str, bytes], dict]:
    """Patch reviewed fixed SLPS fields after the dependency planner selects them."""

    baseline_map = baseline_remaining_ui.get("slps_by_offset")
    current_map = current_remaining_ui.get("slps_by_offset")
    if not isinstance(baseline_map, dict) or not isinstance(current_map, dict):
        raise FullStoryComponentError("incremental SLPS maps are invalid")
    changed_offsets = {
        offset
        for offset in set(baseline_map) | set(current_map)
        if baseline_map.get(offset) != current_map.get(offset)
    }
    removed_offsets = set(baseline_map) - set(current_map)
    if removed_offsets:
        raise FullStoryComponentError(
            "incremental fixed-SLPS patch does not support removing offsets: "
            + ", ".join(sorted(removed_offsets))
        )
    if not changed_offsets:
        raise FullStoryComponentError(
            "incremental fixed-SLPS handler selected without changed fields"
        )

    remaining_reference = config.get("remaining_ui")
    if not isinstance(remaining_reference, dict):
        raise FullStoryComponentError("remaining UI configuration is invalid")
    remaining_ui_path, remaining_data = _locked_file(
        remaining_reference.get("translations"),
        label="remaining UI translations",
    )
    font_manifest_path, font_manifest = _manifest(
        config["full_story_font"]["manifest"],
        label="full-story font manifest",
    )
    if prior_report.get("inputs", {}).get("full_story_font_manifest") != _file_lock(
        font_manifest_path,
        font_manifest_path.read_bytes(),
    ):
        raise FullStoryComponentError(
            "incremental fixed-SLPS patch refused because the font changed"
        )
    original_slps_path, original_slps = _locked_file(
        remaining_reference.get("original_slps"),
        label="original SLPS",
    )
    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
        font_manifest
    )
    encoding_overrides = _stored_text_overrides(table, primary, aliases)
    output_table = project_runtime_text_table(table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table,
        original_fullwidth_ascii_overrides(table),
    )
    current_slps_path = output_root / SLPS_MEMBER
    current_slps = current_slps_path.read_bytes()
    output_slps, _incremental_slps_report = _apply_fixed_span_translations(
        current_slps,
        original_slps,
        current_map,
        table=table,
        output_table=output_table,
        encoding_overrides=encoding_overrides,
        label="remaining SLPS UI",
        accepted_current_texts=current_remaining_ui.get(
            "accepted_current_preimages_by_offset"
        ),
    )
    changed_byte_offsets = {
        index
        for index, (before, after) in enumerate(zip(current_slps, output_slps))
        if before != after
    }
    allowed_byte_offsets = set()
    for raw_offset in changed_offsets:
        offset = int(raw_offset, 16)
        source = decode_text(original_slps, offset, table)
        allowed_byte_offsets.update(range(offset, offset + source.consumed))
    if changed_byte_offsets - allowed_byte_offsets:
        raise FullStoryComponentError(
            "incremental SLPS write changed bytes outside affected fixed fields"
        )

    report = json.loads(json.dumps(prior_report))
    report["inputs"]["config"] = _file_lock(
        config_path, config_path.read_bytes()
    )
    current_remaining_lock = _file_lock(remaining_ui_path, remaining_data)
    for label, lock in report["inputs"].items():
        if isinstance(lock, dict) and lock.get("path") == current_remaining_lock["path"]:
            report["inputs"][label] = current_remaining_lock
    report["inputs"]["original_slps"] = _file_lock(
        original_slps_path,
        original_slps,
    )
    # Keep the clean-build aggregate counters. They describe the complete
    # composition chain, whereas this handler starts from the validated final
    # SLPS and would otherwise turn every unchanged entry into a misleading
    # incremental no-op. New fixed fields and existing fields with a locked
    # preimage can still update those counters exactly from their byte spans.
    aggregate = report["remaining_ui"]["slps"]
    baseline_accepted = baseline_remaining_ui.get(
        "accepted_current_preimages_by_offset", {}
    )
    current_accepted = current_remaining_ui.get(
        "accepted_current_preimages_by_offset", {}
    )

    def fixed_span_metrics(raw_offset: str, translation: str, accepted: dict) -> tuple[bool, int, int]:
        offset = int(raw_offset, 16)
        source = decode_text(original_slps, offset, table)
        preimage = original_slps[offset : offset + source.consumed]
        if raw_offset in accepted:
            encoded_preimage = encode_text(
                normalize_original_fullwidth_ascii(accepted[raw_offset]),
                table,
                overrides=encoding_overrides,
                terminate=True,
            )
            if len(encoded_preimage) > source.consumed:
                raise FullStoryComponentError(
                    f"incremental SLPS preimage overflow at {raw_offset}"
                )
            preimage = encoded_preimage + bytes(
                source.consumed - len(encoded_preimage)
            )
        encoded_translation = encode_text(
            normalize_original_fullwidth_ascii(translation),
            table,
            overrides=encoding_overrides,
            terminate=True,
        )
        replacement = encoded_translation + bytes(
            source.consumed - len(encoded_translation)
        )
        return (
            replacement != preimage,
            sum(before != after for before, after in zip(preimage, replacement)),
            source.consumed - len(encoded_translation),
        )

    for raw_offset in sorted(changed_offsets):
        current_metrics = fixed_span_metrics(
            raw_offset,
            current_map[raw_offset],
            current_accepted,
        )
        if raw_offset not in baseline_map:
            aggregate["entry_count"] += 1
            aggregate[
                "write_entry_count" if current_metrics[0] else "no_op_entry_count"
            ] += 1
            aggregate["changed_byte_count"] += current_metrics[1]
            aggregate["minimum_output_headroom"] = min(
                aggregate["minimum_output_headroom"],
                current_metrics[2],
            )
            continue
        reliable_preimage = (
            raw_offset in baseline_accepted
            or raw_offset in current_accepted
            or baseline_map[raw_offset]
            == decode_text(original_slps, int(raw_offset, 16), table).text
        )
        if reliable_preimage:
            baseline_metrics = fixed_span_metrics(
                raw_offset,
                baseline_map[raw_offset],
                baseline_accepted,
            )
            if baseline_metrics[0] != current_metrics[0]:
                aggregate[
                    "write_entry_count" if baseline_metrics[0] else "no_op_entry_count"
                ] -= 1
                aggregate[
                    "write_entry_count" if current_metrics[0] else "no_op_entry_count"
                ] += 1
            aggregate["changed_byte_count"] += (
                current_metrics[1] - baseline_metrics[1]
            )
            aggregate["minimum_output_headroom"] = min(
                aggregate["minimum_output_headroom"],
                current_metrics[2],
            )
    report["outputs"][SLPS_MEMBER] = _output_lock(
        current_slps_path,
        output_slps,
    )
    if not all(report.get("acceptance", {}).values()):
        raise FullStoryComponentError("prior component acceptance is not reusable")
    print(
        "[incremental] fixed SLPS fields:",
        f"changed_fields={len(changed_offsets)}",
        f"changed_bytes={len(changed_byte_offsets)}",
        flush=True,
    )
    return {SLPS_MEMBER: output_slps}, report


def build(
    config_path: Path,
    output_root: Path,
    *,
    affected_members: set[str] | None = None,
    prior_report: dict | None = None,
) -> tuple[dict[str, bytes], dict]:
    config = _json(config_path)
    incremental = affected_members is not None
    if incremental and (
        not isinstance(prior_report, dict)
        or not affected_members <= ALL_COMPONENT_MEMBERS
    ):
        raise FullStoryComponentError("incremental component context is invalid")

    def reuse_group(members: set[str] | frozenset[str]) -> bool:
        return incremental and affected_members.isdisjoint(members)

    base = config.get("base_ui")
    font = config.get("full_story_font")
    stage = config.get("full_story_stage")
    if not all(isinstance(value, dict) for value in (base, font, stage)):
        raise FullStoryComponentError("component input groups are invalid")

    base_manifest_path, base_manifest = _manifest(
        base["manifest"], label="base UI manifest"
    )
    if (
        base_manifest.get("status") != base.get("required_status")
        or base_manifest.get("profile_id") != base.get("required_profile_id")
    ):
        raise FullStoryComponentError("base UI manifest identity drift")
    base_payloads = {}
    base_paths = {}
    for name, reference in base.get("members", {}).items():
        path, payload = _locked_file(reference, label=f"base UI {name}")
        manifest_lock = base_manifest.get("outputs", {}).get(name)
        if not isinstance(manifest_lock, dict) or (
            manifest_lock.get("size") != len(payload)
            or manifest_lock.get("sha256") != sha256_bytes(payload)
        ):
            raise FullStoryComponentError(f"base UI {name} manifest drift")
        base_paths[name] = path
        base_payloads[name] = payload
    if set(base_payloads) != {"slps", "vt1", "compdata", "mtv_pros"}:
        raise FullStoryComponentError("base UI member set is incomplete")

    font_manifest_path, font_manifest = _manifest(
        font["manifest"], label="full-story font manifest"
    )
    if (
        font_manifest.get("status") != font.get("required_status")
        or font_manifest.get("font_profile_id") != font.get("required_profile_id")
    ):
        raise FullStoryComponentError("full-story font manifest identity drift")
    encoded_text_proposal = base_manifest.get("inputs", {}).get("codebook", {}).get(
        "proposal", {}
    )
    composition = config.get("composition", {})
    compatibility = composition.get("encoded_text_codebook_compatibility")
    if not isinstance(compatibility, dict) or compatibility.get("mode") != (
        "flattened-release-superset-of-encoded-ui"
    ):
        raise FullStoryComponentError(
            "encoded-text/release codebook compatibility is missing"
        )
    encoded_proposal_path = _project_path(encoded_text_proposal.get("path"))
    encoded_proposal = _json(encoded_proposal_path)
    release_proposal_path, release_proposal = _sha_locked_json(
        font_manifest.get("proposal"),
        label="global release font proposal",
    )
    snapshot_path, snapshot = _sha_locked_json(
        compatibility.get("release_snapshot"),
        label="global release assignment snapshot",
    )
    encoded_assignments = encoded_proposal.get("assignments")
    release_assignments = release_proposal.get("assignments")
    if not isinstance(encoded_assignments, list) or not isinstance(
        release_assignments, list
    ):
        raise FullStoryComponentError("font proposal assignments are malformed")
    release_by_character = {
        item.get("character"): (item.get("code"), item.get("glyph_index"))
        for item in release_assignments
        if isinstance(item, dict)
    }
    encoded_mapping_sha256 = sha256_bytes(
        json.dumps(
            sorted(
                (item["character"], item["code"], item["glyph_index"])
                for item in encoded_assignments
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    release_mapping_sha256 = sha256_bytes(
        json.dumps(
            sorted(
                (item["character"], item["code"], item["glyph_index"])
                for item in release_assignments
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if (
        len(encoded_assignments) != compatibility.get("encoded_assignment_count")
        or encoded_mapping_sha256
        != compatibility.get("encoded_assignment_mapping_sha256")
        or len(release_assignments)
        != compatibility.get("release_assignment_count")
        or release_mapping_sha256
        != compatibility.get("release_assignment_mapping_sha256")
        or snapshot.get("primary_mapping_sha256")
        != compatibility.get("release_snapshot_primary_mapping_sha256")
        or release_proposal.get("allocation_registry", {}).get("sha256")
        != compatibility.get("release_snapshot", {}).get("sha256")
        or any(
            release_by_character.get(item.get("character"))
            != (item.get("code"), item.get("glyph_index"))
            for item in encoded_assignments
        )
    ):
        raise FullStoryComponentError(
            "encoded UI text mapping is not an exact subset of the release font"
        )
    font_slps_path, font_slps = _locked_file(
        font["slps"], label="full-story font SLPS"
    )
    font_vt1_path, font_vt1 = _locked_file(
        font["vt1"], label="full-story font VT1"
    )
    font_outputs = font_manifest.get("font_component", {})
    font_component_report_path, font_component_report = _manifest(
        font_outputs.get("report"),
        label="full-story font component report",
    )
    font_codec_strategy = font_component_report.get("font", {}).get(
        "selected_encoder_strategy"
    )
    if not isinstance(font_codec_strategy, str) or not (
        font_codec_strategy.startswith("rust-")
    ):
        raise FullStoryComponentError(
            "full-story font must be compressed by the Rust codec"
        )
    for name, payload in (("slps", font_slps), ("vt1", font_vt1)):
        expected = font_outputs.get(name, {})
        if (
            expected.get("size") != len(payload)
            or expected.get("sha256") != sha256_bytes(payload)
        ):
            raise FullStoryComponentError(f"full-story font {name} manifest drift")

    stage_report_path, stage_report = _manifest(
        stage["report"], label="full-story STAGE report"
    )
    stage_codec_strategies = {
        item.get("codec_strategy")
        for item in stage_report.get("stages", [])
        if isinstance(item, dict)
    }
    if (
        not stage_codec_strategies
        or not all(
            isinstance(strategy, str) and "rust-" in strategy
            for strategy in stage_codec_strategies
        )
    ):
        raise FullStoryComponentError(
            "full-story STAGE must be compressed by the Rust codec"
        )
    expected_unaliased_conditional = release_proposal.get(
        "surface_safe_aliases", {}
    ).get("unaliased_conditional_assignment_count")
    if (
        stage_report.get("status") != stage.get("required_status")
        or len(stage_report.get("stage_indices", []))
        != stage.get("expected_stage_count")
        or stage_report.get("stage_layout_preserved") is not True
        or stage_report.get("hb_offset_reread_exact") is not True
        or stage_report.get("all_safe_aliases") is not True
        or stage_report.get(
            "unaliased_conditional_localized_assignment_count"
        )
        != expected_unaliased_conditional
    ):
        raise FullStoryComponentError("full-story STAGE report contract failed")
    stage_path, stage_payload = _locked_file(
        stage["stage"], label="full-story STAGE.BIN"
    )
    hb_path, hb_payload = _locked_file(stage["hb"], label="full-story HB.BIN")
    for name, payload in (("stage", stage_payload), ("hb", hb_payload)):
        expected = stage_report.get("outputs", {}).get(name, {})
        if (
            expected.get("size") != len(payload)
            or expected.get("sha256") != sha256_bytes(payload)
        ):
            raise FullStoryComponentError(f"full-story {name} report drift")
    kvm_path, kvm_payload = _locked_file(
        config["kvmdata"], label="localized KVMDATA.BIN"
    )

    chunk_index = composition.get("font_chunk_index")
    alignment = composition.get("archive_alignment")
    if chunk_index != 2 or alignment != 16:
        raise FullStoryComponentError("font composition policy drift")
    spec = CORE_ARCHIVE_SPECS["VT1.BIN"]
    font_offsets = read_executable_archive_offsets(font_slps, spec, len(font_vt1))
    font_stored = font_vt1[font_offsets[chunk_index] : font_offsets[chunk_index + 1]]
    font_decoded = decode(font_stored)
    if any(font_stored[font_decoded.consumed :]):
        raise FullStoryComponentError("full-story font archive padding is nonzero")
    expected_decoded_hash = font_manifest["font_component"][
        "decoded_font_sha256"
    ]
    if sha256_bytes(font_decoded.output) != expected_decoded_hash:
        raise FullStoryComponentError("full-story decoded font hash drift")

    base_offsets = read_executable_archive_offsets(
        base_payloads["slps"], spec, len(base_payloads["vt1"])
    )
    output_vt1, output_offsets, padding, borrowed = (
        replace_archive_chunk_with_preceding_zero_slack(
            base_payloads["vt1"],
            base_offsets,
            chunk_index=chunk_index,
            replacement=font_stored[: font_decoded.consumed],
            alignment=alignment,
        )
    )
    offset_plan = build_executable_offset_patch_plan(
        base_payloads["slps"], spec, output_offsets
    )
    output_slps = offset_plan.apply(base_payloads["slps"])
    if read_executable_archive_offsets(output_slps, spec, len(output_vt1)) != output_offsets:
        raise FullStoryComponentError("composed VT1 offsets fail SLPS reread")
    final_font = decode_vt1_font_segment(
        output_slps,
        output_vt1,
        decoder=decode,
    ).decoded
    if sha256_bytes(final_font) != expected_decoded_hash:
        raise FullStoryComponentError("composed decoded font differs from full-story font")

    geometry = config.get("intermission_list_font_geometry")
    if not isinstance(geometry, dict):
        raise FullStoryComponentError(
            "intermission pilot/unit list rendering policy is invalid"
        )
    if geometry.get("enabled") is True:
        try:
            geometry_metrics = IntermissionFontGeometryMetrics(
                render_width=geometry["render_width"],
                render_height=geometry["render_height"],
                advance_width=geometry["advance_width"],
                advance_height=geometry["advance_height"],
            )
            output_slps, geometry_report = apply_intermission_font_geometry_patch(
                output_slps,
                metrics=geometry_metrics,
            )
        except (KeyError, IntermissionFontGeometryError) as error:
            raise FullStoryComponentError(
                f"intermission list font geometry patch failed: {error}"
            ) from error
    elif geometry.get("strategy") == "surface-safe-code-aliases":
        geometry_report = {
            "enabled": False,
            "strategy": "surface-safe-code-aliases",
            "scope": geometry.get("scope"),
            "executable_geometry_patch_applied": False,
            "original_list_renderer_preserved": True,
        }
    else:
        raise FullStoryComponentError(
            "intermission list rendering policy is unsupported"
        )

    preserved_chunks = 0
    donor_index = chunk_index - 1
    for index, (base_start, base_end, out_start, out_end) in enumerate(
        zip(base_offsets, base_offsets[1:], output_offsets, output_offsets[1:])
    ):
        base_chunk = base_payloads["vt1"][base_start:base_end]
        out_chunk = output_vt1[out_start:out_end]
        if index == chunk_index:
            continue
        if index == donor_index:
            expected_chunk = base_chunk[:-borrowed] if borrowed else base_chunk
            donated = base_chunk[-borrowed:] if borrowed else b""
            if out_chunk != expected_chunk or any(donated):
                raise FullStoryComponentError("VT1 zero-slack donor changed unexpectedly")
        elif out_chunk != base_chunk:
            raise FullStoryComponentError(f"non-font VT1 chunk changed: {index}")
        preserved_chunks += 1

    compdata_workspace = CompressedStreamWorkspace.open(
        "DATA/COMPDATA.BN",
        base_payloads["compdata"],
    )
    _original_compdata_path, original_compdata_payload = _locked_file(
        config.get("remaining_ui", {}).get("original_compdata"),
        label="original COMPDATA workspace source",
    )
    original_compdata_decoded = decode(original_compdata_payload)
    if original_compdata_decoded.consumed != len(original_compdata_payload):
        raise FullStoryComponentError(
            "original COMPDATA workspace source has trailing compressed bytes"
        )

    (
        output_compdata,
        pilot_name_report,
        pilot_structure_path,
        story_speaker_path,
        residual_name_path,
        unit_name_path,
        font_proposal_path,
    ) = _apply_full_pilot_names(
        compdata_workspace.stored,
        config.get("full_pilot_names"),
        font_manifest,
        workspace=compdata_workspace,
    )
    (
        output_slps,
        output_vt1,
        output_compdata,
        stage_title_report,
        stage_title_input_paths,
    ) = _apply_full_stage_titles(
        output_slps,
        output_vt1,
        compdata_workspace.stored,
        config.get("full_stage_titles"),
        font_manifest,
        config["full_pilot_names"]["codec"],
        final_font,
        release_by_character,
        workspace=compdata_workspace,
    )
    (
        output_slps,
        output_compdata,
        remaining_ui_report,
        remaining_ui_input_paths,
    ) = _apply_remaining_ui(
        output_slps,
        compdata_workspace.stored,
        config.get("remaining_ui"),
        stage_title_input_paths[2],
        font_manifest,
        config["full_pilot_names"]["codec"],
        workspace=compdata_workspace,
        original_decoded=original_compdata_decoded,
    )
    if reuse_group({NISVDATA_MEMBER}):
        output_nisvdata = _prior_output_payload(output_root, NISVDATA_MEMBER)
        nisv_effect_names_report = json.loads(
            json.dumps(prior_report["nisv_effect_names"])
        )
        nisv_effect_names_input_paths = (
            _prior_input_path(prior_report, "remaining_ui_translations"),
            _prior_input_path(prior_report, "original_nisvdata"),
        )
    else:
        (
            output_nisvdata,
            nisv_effect_names_report,
            nisv_effect_names_input_paths,
        ) = _apply_nisv_effect_names(
            output_slps,
            font_manifest,
            config.get("nisv_effect_names"),
        )
    (
        output_compdata,
        compdata_battle_line_report,
        compdata_battle_line_corpus_path,
    ) = _apply_compdata_battle_lines(
        compdata_workspace.stored,
        config.get("compdata_battle_lines"),
        stage_title_input_paths[2],
        remaining_ui_input_paths[2],
        font_manifest,
        config["full_pilot_names"]["codec"],
        workspace=compdata_workspace,
        original_decoded=original_compdata_decoded,
    )
    (
        output_compdata,
        reviewed_weapon_report,
        reviewed_weapon_corpus_path,
    ) = _apply_reviewed_weapon_names(
        compdata_workspace.stored,
        config.get("reviewed_weapons"),
        stage_title_input_paths[2],
        remaining_ui_input_paths[2],
        font_manifest,
        config["full_pilot_names"]["codec"],
        workspace=compdata_workspace,
        original_decoded=original_compdata_decoded,
    )
    (
        output_slps,
        output_compdata,
        global_safe_alias_report,
    ) = _apply_global_safe_aliases(
        output_slps,
        compdata_workspace.stored,
        stage_title_input_paths[2],
        font_manifest,
        config["full_pilot_names"]["codec"],
        workspace=compdata_workspace,
    )
    try:
        output_compdata, compdata_workspace_report = compdata_workspace.finalize(
            **config["full_pilot_names"]["codec"]
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"final COMPDATA workspace compression failed: {error}"
        ) from error
    final_compdata_size = len(output_compdata)
    pilot_name_report.update(
        {
            "output_compressed_size": final_compdata_size,
            "codec_round_trip_exact": True,
        }
    )
    for compdata_report in (
        stage_title_report,
        remaining_ui_report,
        compdata_battle_line_report,
        reviewed_weapon_report,
        global_safe_alias_report,
    ):
        compdata_report["compdata_output_size"] = final_compdata_size
    stage_title_report["compdata_round_trip_exact"] = True
    remaining_ui_report["compdata_round_trip_exact"] = True
    compdata_battle_line_report["codec_round_trip_exact"] = True
    reviewed_weapon_report["codec_round_trip_exact"] = True
    global_safe_alias_report["compdata_round_trip_exact"] = True
    if reuse_group({SLPS_MEMBER, *AUTO_DEMO_MEMBERS}):
        output_auto_demo_archives = {
            member: _prior_output_payload(output_root, member)
            for member in AUTO_DEMO_MEMBERS
        }
        auto_demo_report = json.loads(
            json.dumps(prior_report["auto_demo_overlays"])
        )
        auto_demo_input_paths = {
            label.removeprefix("auto_demo_"): _prior_input_path(
                prior_report, label
            )
            for label in prior_report["inputs"]
            if label.startswith("auto_demo_")
        }
    else:
        (
            output_slps,
            output_auto_demo_archives,
            auto_demo_report,
            auto_demo_input_paths,
        ) = _apply_auto_demo_overlays(
            output_slps,
            config.get("auto_demo_overlays"),
            font_manifest,
        )
    (
        output_slps,
        scenario_description_layout_report,
    ) = _apply_scenario_description_layout(
        output_slps,
        config["scenario_select_effect"].get("description_layout"),
    )
    if reuse_group(SRVC_MEMBERS):
        output_srvc_bin = _prior_output_payload(output_root, "BTL/SRVC.BIN")
        output_srvc_seg = _prior_output_payload(output_root, "BTL/SRVC.SEG")
        srvc_report = json.loads(json.dumps(prior_report["srvc_battle_text"]))
        srvc_input_paths = tuple(
            _prior_input_path(prior_report, label)
            for label in (
                "srvc_battle_text_corpus",
                "original_srvc_bin",
                "original_srvc_seg",
            )
        )
    else:
        (
            output_srvc_bin,
            output_srvc_seg,
            srvc_report,
            srvc_input_paths,
        ) = _apply_srvc_battle_text(
            config.get("srvc_battle_text"),
            font_manifest,
        )

    if reuse_group({STAGE_MEMBER}):
        output_stage = _prior_output_payload(output_root, STAGE_MEMBER)
        stage_chunk0_workspace_report = json.loads(
            json.dumps(
                prior_report.get("compression", {}).get(
                    "stage_chunk_0_workspace",
                    {
                        "physical_stream": "DATA/STAGE.BIN chunk 0",
                        "workflow": "legacy_prior_manifest",
                    },
                )
            )
        )
        stage_overview_report = json.loads(json.dumps(prior_report["stage_overviews"]))
        stage_overview_corpus_path = _prior_input_path(prior_report, "stage_overviews")
        stage_fixed_formation_report = json.loads(
            json.dumps(prior_report["remaining_ui"]["stage_fixed_formation"])
        )
        stage_default_formation_report = json.loads(
            json.dumps(prior_report["remaining_ui"]["stage_default_formation"])
        )
        stage_system_dialogue_report = json.loads(
            json.dumps(prior_report["remaining_ui"]["stage_system_dialogue"])
        )
        original_stage_path = _prior_input_path(prior_report, "original_stage")
        stage_default_formation_corpus_path = _prior_input_path(
            prior_report, "stage_default_formation_corpus"
        )
        stage_default_formation_inventory_path = _prior_input_path(
            prior_report, "stage_default_formation_inventory"
        )
        stage_system_dialogue_corpus_path = _prior_input_path(
            prior_report, "stage_system_dialogue"
        )
    else:
        stage_offset_spec = ExecutableOffsetSpec(
            name="HEDBDY/HB.BIN STAGE offsets",
            member="HEDBDY/HB.BIN",
            table_start=30320,
            table_end=31144,
        )
        stage_offsets = read_executable_archive_offsets(
            hb_payload,
            stage_offset_spec,
            len(stage_payload),
        )
        stage_chunk0_end = stage_offsets[1]
        stage_chunk0_workspace = (
            CompressedStreamWorkspace.open_zero_padded_allocation(
                "DATA/STAGE.BIN chunk 0",
                stage_payload[:stage_chunk0_end],
            )
        )
        (
            output_stage,
            stage_overview_report,
            stage_overview_corpus_path,
        ) = _apply_stage_overviews(
            stage_payload,
            hb_payload,
            config.get("stage_overviews"),
            font_manifest,
            config["full_pilot_names"]["codec"],
            chunk_workspace=stage_chunk0_workspace,
        )
        (
            output_stage,
            stage_default_formation_report,
            stage_fixed_formation_report,
            original_stage_path,
            stage_default_formation_corpus_path,
            stage_default_formation_inventory_path,
        ) = _apply_stage_default_formation_names(
            output_stage,
            hb_payload,
            config.get("remaining_ui"),
            font_manifest,
            config["full_pilot_names"]["codec"],
        )
        (
            output_stage,
            stage_system_dialogue_report,
            stage_system_dialogue_corpus_path,
        ) = _apply_stage_system_dialogues(
            output_stage,
            hb_payload,
            config.get("remaining_ui"),
            font_manifest,
            config["full_pilot_names"]["codec"],
            chunk_workspace=stage_chunk0_workspace,
        )
        try:
            stage_chunk0_encoded, stage_chunk0_workspace_report = (
                stage_chunk0_workspace.finalize(
                    strategy=config["full_pilot_names"]["codec"]["strategy"],
                    min_match_length=config["full_pilot_names"]["codec"][
                        "min_match_length"
                    ],
                    max_match_chain=config["full_pilot_names"]["codec"][
                        "max_match_chain"
                    ],
                    lazy_matching=config["full_pilot_names"]["codec"][
                        "lazy_matching"
                    ],
                    max_output_size=stage_chunk0_end,
                )
            )
        except (RuntimeError, ValueError) as error:
            raise FullStoryComponentError(
                f"final STAGE chunk 0 workspace compression failed: {error}"
            ) from error
        stage_chunk0_stored = stage_chunk0_encoded + bytes(
            stage_chunk0_end - len(stage_chunk0_encoded)
        )
        output_stage = stage_chunk0_stored + output_stage[stage_chunk0_end:]
        if (
            len(output_stage) != len(stage_payload)
            or read_executable_archive_offsets(
                hb_payload,
                stage_offset_spec,
                len(output_stage),
            )
            != stage_offsets
        ):
            raise FullStoryComponentError(
                "final STAGE chunk 0 workspace layout changed"
            )
        for chunk0_report in (
            stage_overview_report,
            stage_system_dialogue_report,
        ):
            chunk0_report.update(
                {
                    "output_encoded_size": len(stage_chunk0_encoded),
                    "codec_round_trip_exact": True,
                }
            )
        stage_overview_report.update(
            {
                "output_encoded_sha256": sha256_bytes(stage_chunk0_encoded),
                "output_padding_size": (
                    stage_chunk0_end - len(stage_chunk0_encoded)
                ),
            }
        )
    remaining_ui_report["stage_fixed_formation"] = stage_fixed_formation_report
    remaining_ui_report["stage_default_formation"] = stage_default_formation_report
    remaining_ui_report["stage_system_dialogue"] = stage_system_dialogue_report

    if reuse_group({HSFC_MEMBER}):
        output_hsfc = _prior_output_payload(output_root, HSFC_MEMBER)
        hsfc_overview_report = json.loads(json.dumps(prior_report["hsfc_overviews"]))
        hsfc_overview_input_paths = (
            _prior_input_path(prior_report, "hsfc_overviews"),
            _prior_input_path(prior_report, "original_hsfc"),
        )
    else:
        (
            output_hsfc,
            hsfc_overview_report,
            hsfc_overview_input_paths,
        ) = _apply_hsfc_overviews(
            output_slps,
            config.get("hsfc_overviews"),
            font_manifest,
            config["full_pilot_names"]["codec"],
        )

    if reuse_group({VEFF_MEMBER}):
        output_veff = _prior_output_payload(output_root, VEFF_MEMBER)
        scenario_select_report = json.loads(
            json.dumps(prior_report["scenario_select_effect"])
        )
        mode_select_report = json.loads(json.dumps(prior_report["mode_select_effect"]))
        scenario_select_source_path = _prior_input_path(prior_report, "original_veff2dx")
        mode_select_source_path = scenario_select_source_path
    else:
        (
            output_veff,
            scenario_select_report,
            scenario_select_source_path,
        ) = _apply_scenario_select_effect(
            output_slps,
            final_font,
            release_by_character,
            config.get("scenario_select_effect"),
        )
        scenario_select_report["description_layout"] = (
            scenario_description_layout_report
        )
        (
            output_veff,
            mode_select_report,
            mode_select_source_path,
        ) = _apply_scenario_select_effect(
            output_slps,
            final_font,
            release_by_character,
            config.get("mode_select_effect"),
            archive_payload=output_veff,
        )
        if mode_select_source_path != scenario_select_source_path:
            raise FullStoryComponentError("VEFF2DX source path drift between targets")

    if reuse_group({MAPMODEL_MEMBER}):
        output_mapmodel = _prior_output_payload(output_root, MAPMODEL_MEMBER)
        world_map_title_report = json.loads(json.dumps(prior_report["world_map_titles"]))
        terrain_name_report = world_map_title_report["terrain_names"]
        world_map_title_input_paths = {
            "corpus": _prior_input_path(prior_report, "world_map_title_corpus"),
            "render_snapshot": _prior_input_path(
                prior_report, "world_map_title_render_snapshot"
            ),
            "original_slps": _prior_input_path(prior_report, "world_map_original_slps"),
            "original_archive": _prior_input_path(
                prior_report, "world_map_original_archive"
            ),
        }
        terrain_name_input_paths = (
            _prior_input_path(prior_report, "terrain_name_corpus"),
            _prior_input_path(prior_report, "terrain_name_inventory"),
        )
    else:
        mapmodel_decoded_cache = {}
        (
            output_mapmodel,
            world_map_title_report,
            world_map_title_input_paths,
        ) = build_world_map_titles(
            PROJECT_ROOT,
            WORK_ROOT,
            config.get("world_map_titles"),
            preview_root=output_root / "previews/world-map-titles",
            decoded_cache=mapmodel_decoded_cache,
        )
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        _proposal_path, primary, aliases, _alias_report = _full_story_overrides(
            font_manifest
        )
        encoding_overrides = _stored_text_overrides(table, primary, aliases)
        try:
            (
                output_mapmodel,
                terrain_name_report,
                terrain_name_input_paths,
            ) = build_terrain_names(
                PROJECT_ROOT,
                config.get("world_map_titles", {}).get("terrain_names"),
                archive_payload=output_mapmodel,
                table=table,
                encoding_overrides=encoding_overrides,
                decoded_cache=mapmodel_decoded_cache,
            )
        except TerrainNameError as error:
            raise FullStoryComponentError(
                f"MAPMODEL terrain-name write failed: {error}"
            ) from error
        world_map_title_report["terrain_names"] = terrain_name_report

    payloads = {
        "SLPS_258.87": output_slps,
        "DATA/VT1.BIN": output_vt1,
        "DATA/COMPDATA.BN": output_compdata,
        "DATA/NISVDATA.BIN": output_nisvdata,
        "DATA/MTV_PROS.BIN": base_payloads["mtv_pros"],
        "DATA/STAGE.BIN": output_stage,
        "DATA/HSFC.BIN": output_hsfc,
        "HEDBDY/HB.BIN": hb_payload,
        "KURODATA/KVMDATA.BIN": kvm_payload,
        "BTL/SRVC.BIN": output_srvc_bin,
        "BTL/SRVC.SEG": output_srvc_seg,
        "EFF/VEFF2DX.BIN": output_veff,
        "MAP/MAPMODEL.BIN": output_mapmodel,
        **output_auto_demo_archives,
    }
    if incremental:
        for member in ALL_COMPONENT_MEMBERS - affected_members:
            payloads[member] = _prior_output_payload(output_root, member)
    output_paths = {name: output_root / name for name in payloads}
    stage_headrooms = [
        item["source_chunk_size"] - item["output_encoded_size"]
        for item in stage_report["stages"]
    ]
    report = {
        "schema_version": 1,
        "status": "integrated_global_zh_release_components_validated_runtime_pending",
        "profile_id": config["profile_id"],
        "scope": config["scope"],
        "inputs": {
            "config": _file_lock(config_path, config_path.read_bytes()),
            "base_ui_manifest": _file_lock(
                base_manifest_path, base_manifest_path.read_bytes()
            ),
            "full_story_font_manifest": _file_lock(
                font_manifest_path, font_manifest_path.read_bytes()
            ),
            "full_story_stage_report": _file_lock(
                stage_report_path, stage_report_path.read_bytes()
            ),
            "pilot_name_structure": _file_lock(
                pilot_structure_path, pilot_structure_path.read_bytes()
            ),
            "story_speakers": _file_lock(
                story_speaker_path, story_speaker_path.read_bytes()
            ),
            "remaining_display_names": _file_lock(
                residual_name_path, residual_name_path.read_bytes()
            ),
            "full_unit_names": _file_lock(
                unit_name_path, unit_name_path.read_bytes()
            ),
            "full_story_font_proposal": _file_lock(
                font_proposal_path, font_proposal_path.read_bytes()
            ),
            "stage_names": _file_lock(
                stage_title_input_paths[0], stage_title_input_paths[0].read_bytes()
            ),
            "stage_title_format": _file_lock(
                stage_title_input_paths[1], stage_title_input_paths[1].read_bytes()
            ),
            "stage_overviews": _file_lock(
                stage_overview_corpus_path,
                stage_overview_corpus_path.read_bytes(),
            ),
            "stage_system_dialogue": _file_lock(
                stage_system_dialogue_corpus_path,
                stage_system_dialogue_corpus_path.read_bytes(),
            ),
            "hsfc_overviews": _file_lock(
                hsfc_overview_input_paths[0],
                hsfc_overview_input_paths[0].read_bytes(),
            ),
            "original_hsfc": _file_lock(
                hsfc_overview_input_paths[1],
                hsfc_overview_input_paths[1].read_bytes(),
            ),
            "menu_descriptor": _file_lock(
                stage_title_input_paths[2], stage_title_input_paths[2].read_bytes()
            ),
            "remaining_ui_translations": _file_lock(
                remaining_ui_input_paths[0],
                remaining_ui_input_paths[0].read_bytes(),
            ),
            "stage_default_formation_corpus": _file_lock(
                stage_default_formation_corpus_path,
                stage_default_formation_corpus_path.read_bytes(),
            ),
            "stage_default_formation_inventory": _file_lock(
                stage_default_formation_inventory_path,
                stage_default_formation_inventory_path.read_bytes(),
            ),
            "remaining_ui_parts": _file_lock(
                remaining_ui_input_paths[1],
                remaining_ui_input_paths[1].read_bytes(),
            ),
            "reviewed_weapons": _file_lock(
                reviewed_weapon_corpus_path,
                reviewed_weapon_corpus_path.read_bytes(),
            ),
            "compdata_battle_lines": _file_lock(
                compdata_battle_line_corpus_path,
                compdata_battle_line_corpus_path.read_bytes(),
            ),
            "original_compdata": _file_lock(
                remaining_ui_input_paths[2],
                remaining_ui_input_paths[2].read_bytes(),
            ),
            "original_nisvdata": _file_lock(
                nisv_effect_names_input_paths[1],
                nisv_effect_names_input_paths[1].read_bytes(),
            ),
            "original_slps": _file_lock(
                remaining_ui_input_paths[3],
                remaining_ui_input_paths[3].read_bytes(),
            ),
            "original_stage": _file_lock(
                original_stage_path,
                original_stage_path.read_bytes(),
            ),
            "srvc_battle_text_corpus": _file_lock(
                srvc_input_paths[0], srvc_input_paths[0].read_bytes()
            ),
            "original_srvc_bin": _file_lock(
                srvc_input_paths[1], srvc_input_paths[1].read_bytes()
            ),
            "original_srvc_seg": _file_lock(
                srvc_input_paths[2], srvc_input_paths[2].read_bytes()
            ),
            "font_slps": _file_lock(font_slps_path, font_slps),
            "font_vt1": _file_lock(font_vt1_path, font_vt1),
            "font_component_report": _file_lock(
                font_component_report_path,
                font_component_report_path.read_bytes(),
            ),
            "stage": _file_lock(stage_path, stage_payload),
            "hb": _file_lock(hb_path, hb_payload),
            "kvmdata": _file_lock(kvm_path, kvm_payload),
            "original_veff2dx": _file_lock(
                scenario_select_source_path,
                scenario_select_source_path.read_bytes(),
            ),
            "world_map_title_corpus": _file_lock(
                world_map_title_input_paths["corpus"],
                world_map_title_input_paths["corpus"].read_bytes(),
            ),
            "world_map_title_render_snapshot": _file_lock(
                world_map_title_input_paths["render_snapshot"],
                world_map_title_input_paths["render_snapshot"].read_bytes(),
            ),
            "world_map_original_slps": _file_lock(
                world_map_title_input_paths["original_slps"],
                world_map_title_input_paths["original_slps"].read_bytes(),
            ),
            "world_map_original_archive": _file_lock(
                world_map_title_input_paths["original_archive"],
                world_map_title_input_paths["original_archive"].read_bytes(),
            ),
            "terrain_name_corpus": _file_lock(
                terrain_name_input_paths[0],
                terrain_name_input_paths[0].read_bytes(),
            ),
            "terrain_name_inventory": _file_lock(
                terrain_name_input_paths[1],
                terrain_name_input_paths[1].read_bytes(),
            ),
            **{
                f"auto_demo_{label}": _file_lock(path, path.read_bytes())
                for label, path in auto_demo_input_paths.items()
            },
        },
        "compression": {
            "backend_policy": "rust-only",
            "python_encoder_used": False,
            "python_decoder_used": False,
            "compdata_workspace": compdata_workspace_report,
            "stage_chunk_0_workspace": stage_chunk0_workspace_report,
            "font_strategy": font_codec_strategy,
            "stage_strategies": sorted(stage_codec_strategies),
            "component_strategy": config["full_pilot_names"]["codec"][
                "strategy"
            ],
            "scenario_select_strategy": scenario_select_report["codec"][
                "strategy"
            ],
            "mode_select_strategy": mode_select_report["codec"]["strategy"],
            "nisv_effect_names_strategy": nisv_effect_names_report["codec"][
                "strategy"
            ],
            "world_map_title_strategy": world_map_title_report["codec"][
                "strategy"
            ],
        },
        "composition": {
            "font_chunk_index": chunk_index,
            "font_encoded_size": font_decoded.consumed,
            "font_decoded_sha256": expected_decoded_hash,
            "font_padding_size": padding,
            "additional_borrowed_preceding_zero_slack": borrowed,
            "preserved_non_font_vt1_chunk_count": preserved_chunks,
            "archive_size_preserved": len(output_vt1) == len(base_payloads["vt1"]),
            "slps_offset_reread_exact": True,
            "intermission_list_font_geometry": geometry_report,
            "encoded_text_codebook_compatibility": {
                "encoded_ui_mapping_is_release_subset": True,
                "encoded_proposal": _file_lock(
                    encoded_proposal_path,
                    encoded_proposal_path.read_bytes(),
                ),
                "release_proposal": _file_lock(
                    release_proposal_path,
                    release_proposal_path.read_bytes(),
                ),
                "release_snapshot": _file_lock(
                    snapshot_path,
                    snapshot_path.read_bytes(),
                ),
                "encoded_assignment_count": len(encoded_assignments),
                "encoded_assignment_mapping_sha256": encoded_mapping_sha256,
                "release_assignment_count": len(release_assignments),
                "release_assignment_mapping_sha256": release_mapping_sha256,
            },
        },
        "story": {
            "stage_count": len(stage_report["stage_indices"]),
            "stage_indices": stage_report["stage_indices"],
            "translated_allocation_count": sum(
                item["allocation_count"] for item in stage_report["stages"]
            ),
            "speaker_count": sum(
                item["speaker_count"] for item in stage_report["stages"]
            ),
            "minimum_compressed_chunk_headroom": min(stage_headrooms),
            "stage_layout_preserved": True,
            "translated_reread_exact": all(
                item["translated_reread_exact"] for item in stage_report["stages"]
            ),
            "codec_round_trip_exact": all(
                item["codec_round_trip_exact"] for item in stage_report["stages"]
            ),
        },
        "pilot_names": pilot_name_report,
        "stage_titles": stage_title_report,
        "stage_overviews": stage_overview_report,
        "hsfc_overviews": hsfc_overview_report,
        "remaining_ui": remaining_ui_report,
        "nisv_effect_names": nisv_effect_names_report,
        "compdata_battle_lines": compdata_battle_line_report,
        "reviewed_weapons": reviewed_weapon_report,
        "srvc_battle_text": srvc_report,
        "auto_demo_overlays": auto_demo_report,
        "scenario_select_effect": scenario_select_report,
        "mode_select_effect": mode_select_report,
        "world_map_titles": world_map_title_report,
        "global_safe_aliases": global_safe_alias_report,
        "outputs": {
            name: _output_lock(output_paths[name], payload)
            for name, payload in payloads.items()
        },
        "acceptance": {
            "production_compression_backend_rust_only": (
                font_codec_strategy.startswith("rust-")
                and all(
                    "rust-" in strategy
                    for strategy in stage_codec_strategies
                )
                and config["full_pilot_names"]["codec"]["strategy"]
                == "rust-fit"
                and scenario_select_report["codec"]["strategy"]
                == "rust-fit"
                and mode_select_report["codec"]["strategy"] == "rust-fit"
                and nisv_effect_names_report["codec"]["strategy"]
                == "rust-fit"
                and stage_fixed_formation_report["codec_strategy"]
                == "rust-fit"
                and world_map_title_report["codec"]["strategy"]
                == "rust-fit"
                and terrain_name_report["codec_round_trip_exact"]
            ),
            "world_map_titles_reread_exact": (
                world_map_title_report["unique_title_count"] == 78
                and world_map_title_report["translated_unique_title_count"]
                == 70
                and world_map_title_report["member_count"] == 115
                and world_map_title_report["translated_member_count"] == 101
                and world_map_title_report["archive_size_preserved"]
                and world_map_title_report["top_level_offsets_preserved"]
                and world_map_title_report[
                    "non_title_members_preserved_byte_exact"
                ]
                and world_map_title_report[
                    "non_title_decoded_bytes_preserved"
                ]
                and world_map_title_report[
                    "english_subtitle_preserved_byte_exact"
                ]
                and world_map_title_report[
                    "same_text_members_preserved_byte_exact"
                ]
                and world_map_title_report[
                    "compressed_chunks_fit_allocations"
                ]
                and world_map_title_report["codec_round_trip_exact"]
                and terrain_name_report["unique_source_count"] == 15
                and terrain_name_report["occurrence_count"] == 66
                and terrain_name_report["changed_member_count"] == 10
                and terrain_name_report["fixed_decoded_spans_preserved"]
                and terrain_name_report["archive_size_preserved"]
                and terrain_name_report["offset_table_preserved"]
                and terrain_name_report["codec_round_trip_exact"]
                and terrain_name_report["reread_exact"]
            ),
            "p10_ui_members_inherited_exact": True,
            "encoded_ui_codebook_is_release_subset": True,
            "global_release_font_missing_character_count_zero": (
                font_manifest["coverage"]["missing_character_count"]
                == 0
            ),
            "global_release_font_original_han_count_zero": (
                font_manifest["coverage"]["original_font_han_count"]
                == 0
            ),
            "global_release_font_original_visible_character_count_zero": (
                font_manifest["coverage"][
                    "original_font_visible_character_count"
                ]
                == 0
            ),
            "font_codec_round_trip_exact": font_manifest["acceptance"][
                "codec_round_trip_exact"
            ],
            "font_archive_size_preserved": len(output_vt1)
            == len(base_payloads["vt1"]),
            "stage_layout_preserved": stage_report["stage_layout_preserved"],
            "stage_hb_offset_reread_exact": stage_report["hb_offset_reread_exact"],
            "all_story_text_reread_exact": all(
                item["translated_reread_exact"] for item in stage_report["stages"]
            ),
            "full_story_pilot_names_reread_exact": pilot_name_report[
                "reread_exact"
            ],
            "full_story_unit_names_reread_exact": pilot_name_report[
                "unit_names"
            ]["reread_exact"],
            "full_story_unit_name_pointer_relocations_exact": pilot_name_report[
                "unit_names"
            ]["pointer_relocations_exact"],
            "full_story_unit_name_spaces_two_byte": pilot_name_report[
                "unit_names"
            ]["two_byte_spaces_exact"],
            "full_story_pilot_name_codec_round_trip_exact": pilot_name_report[
                "codec_round_trip_exact"
            ],
            "full_story_pilot_name_changes_confined": pilot_name_report[
                "changed_bytes_confined_to_selected_fields"
            ],
            "full_story_stage_titles_reread_exact": (
                stage_title_report["stage_title_entry_count"] == 122
                and stage_title_report["stage_38_title"] == "被安排的决战"
                and stage_title_report["compdata_round_trip_exact"]
                and stage_title_report["fixed_spans_preserved"]
                and stage_title_report["pointer_bytes_unchanged"]
                and stage_title_report["slps_size_preserved"]
                and stage_title_report["graphics"]["texture_entry_count"] == 107
                and stage_title_report["graphics"]["stage_name_entry_count"]
                == 122
                and stage_title_report["graphics"]["text_only_entry_count"]
                == 15
                and stage_title_report["graphics"][
                    "all_stage_name_entries_accounted_for"
                ]
                and stage_title_report["graphics"][
                    "archive_size_preserved"
                ]
                and stage_title_report["graphics"][
                    "top_level_offsets_preserved"
                ]
                and stage_title_report["graphics"][
                    "internal_offsets_preserved"
                ]
                and stage_title_report["graphics"][
                    "tim2_metadata_and_clut_preserved"
                ]
                and stage_title_report["graphics"][
                    "translated_reread_exact"
                ]
                and stage_title_report["graphics"]["stage_38"]["text"]
                == "被安排的决战"
            ),
            "stage_overviews_reread_exact": (
                stage_overview_report["translated_readback_exact"]
                and stage_overview_report["fixed_allocations_preserved"]
                and stage_overview_report["untranslated_allocations_preserved"]
                and stage_overview_report["newline_counts_preserved"]
                and stage_overview_report["codec_round_trip_exact"]
                and stage_overview_report["archive_size_preserved"]
                and stage_overview_report["hb_offsets_preserved"]
                and stage_overview_report[
                    "non_target_chunks_preserved_byte_exact"
                ]
            ),
            "hsfc_overviews_reread_exact": (
                hsfc_overview_report["translated_readback_exact"]
                and hsfc_overview_report["fixed_cells_preserved"]
                and hsfc_overview_report["non_target_bytes_preserved"]
                and hsfc_overview_report["codec_round_trip_exact"]
                and hsfc_overview_report["archive_size_preserved"]
                and hsfc_overview_report["slps_offsets_preserved"]
                and hsfc_overview_report[
                    "non_target_chunks_preserved_byte_exact"
                ]
                and hsfc_overview_report["translated_occurrence_count"] == 180
                and hsfc_overview_report["translation_method"]
                == "direct_manual"
                and hsfc_overview_report["external_model_used"] is False
            ),
            "remaining_ui_binary_text_reread_exact": (
                remaining_ui_report["compdata_direct"]["reread_exact"]
                and remaining_ui_report["compdata_context_help"][
                    "reread_exact"
                ]
                and remaining_ui_report["compdata_inline"]["reread_exact"]
                and remaining_ui_report["compdata_inline"][
                    "internal_entry_offsets_preserved"
                ]
                and remaining_ui_report["leadership_effects"]["reread_exact"]
                and remaining_ui_report["slps_context_ui"]["reread_exact"]
                and remaining_ui_report["slps"]["reread_exact"]
                and remaining_ui_report["parts"]["reread_exact"]
                and remaining_ui_report["stage_fixed_formation"][
                    "reread_exact"
                ]
                and remaining_ui_report["stage_fixed_formation"][
                    "codec_round_trip_exact"
                ]
                and remaining_ui_report["stage_fixed_formation"][
                    "archive_size_preserved"
                ]
                and remaining_ui_report["stage_fixed_formation"][
                    "hb_offsets_preserved"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "reread_exact"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "codec_round_trip_exact"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "archive_size_preserved"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "hb_offsets_preserved"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "group_count"
                ]
                == config["remaining_ui"]["expected"][
                    "stage_default_formation_group_count"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "stage_count"
                ]
                == config["remaining_ui"]["expected"][
                    "stage_default_formation_stage_count"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "entry_count"
                ]
                == config["remaining_ui"]["expected"][
                    "stage_default_formation_entry_count"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "unique_source_count"
                ]
                == config["remaining_ui"]["expected"][
                    "stage_default_formation_unique_source_count"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "record_metadata_count"
                ]
                == config["remaining_ui"]["expected"][
                    "stage_default_formation_record_metadata_count"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "inventory_sha256"
                ]
                == config["remaining_ui"]["expected"][
                    "stage_default_formation_inventory_sha256"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "record_metadata_preserved_byte_exact"
                ]
                and remaining_ui_report["stage_system_dialogue"][
                    "reread_exact"
                ]
                and remaining_ui_report["stage_system_dialogue"][
                    "pointer_bytes_unchanged"
                ]
                and remaining_ui_report["stage_system_dialogue"][
                    "codec_round_trip_exact"
                ]
                and remaining_ui_report["stage_system_dialogue"][
                    "archive_size_preserved"
                ]
                and remaining_ui_report["stage_system_dialogue"][
                    "hb_offsets_preserved"
                ]
                and remaining_ui_report["compdata_round_trip_exact"]
                and remaining_ui_report["slps_size_preserved"]
            ),
            "remaining_ui_placeholders_preserved": (
                remaining_ui_report["compdata_direct"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["compdata_context_help"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["compdata_inline"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["leadership_effects"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["slps_context_ui"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["slps"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["parts"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["stage_fixed_formation"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["stage_default_formation"][
                    "placeholder_control_tokens_preserved"
                ]
                and remaining_ui_report["stage_system_dialogue"][
                    "source_preimages_sha256_exact"
                ]
            ),
            "reviewed_weapon_names_reread_exact": (
                reviewed_weapon_report["corpus_entry_count"] == 711
                and reviewed_weapon_report["all_editorial_statuses_reviewed"]
                and reviewed_weapon_report["source_preimages_sha256_exact"]
                and reviewed_weapon_report["fixed_spans_preserved"]
                and reviewed_weapon_report["pointer_bytes_unchanged"]
                and reviewed_weapon_report["target_offset_reread_exact"]
                and reviewed_weapon_report["codec_round_trip_exact"]
            ),
            "compdata_battle_lines_reread_exact": (
                compdata_battle_line_report["corpus_entry_count"] == 297
                and compdata_battle_line_report["target_occurrence_count"]
                == 511
                and compdata_battle_line_report["unique_target_count"] == 297
                and compdata_battle_line_report[
                    "shared_non_battle_owner_count"
                ]
                == 0
                and compdata_battle_line_report[
                    "source_preimages_sha256_exact"
                ]
                and compdata_battle_line_report["fixed_spans_preserved"]
                and compdata_battle_line_report["pointer_bytes_unchanged"]
                and compdata_battle_line_report[
                    "target_offset_reread_exact"
                ]
                and compdata_battle_line_report["codec_round_trip_exact"]
            ),
            "single_character_atlas_regions_untouched": (
                remaining_ui_report["atlas"][
                    "single_character_regions_untouched"
                ]
                and remaining_ui_report["atlas"][
                    "protected_single_character_sources"
                ]
                == ["攻", "反"]
            ),
            "srvc_battle_text_reread_exact": (
                srvc_report["translated_reread_exact"]
                and srvc_report["control_tokens_preserved"]
                and srvc_report["record_budgets_preserved"]
                and srvc_report["chunk_boundaries_preserved"]
                and srvc_report["index_structure_preserved"]
                and srvc_report["metadata_preserved_byte_exact"]
                and srvc_report["unindexed_tails_preserved_byte_exact"]
                and srvc_report["zero_record_chunks_preserved_byte_exact"]
                and srvc_report["seg_preserved_byte_exact"]
            ),
            "auto_demo_overlays_reread_exact": (
                auto_demo_report["title_entry_count"] == 22
                and auto_demo_report["name_slot_count"] == 63
                and auto_demo_report["unique_name_source_count"] == 59
                and auto_demo_report[
                    "work_titles_reused_from_existing_corpus"
                ]
                and auto_demo_report["names_reused_from_existing_corpora"]
                and auto_demo_report["fixed_spans_preserved"]
                and auto_demo_report["archive_sizes_preserved"]
                and auto_demo_report["seg_files_preserved_byte_exact"]
                and auto_demo_report["translated_reread_exact"]
            ),
            "all_localized_text_uses_safe_double_byte_aliases": (
                global_safe_alias_report[
                    "unaliased_conditional_assignment_count"
                ]
                == 0
                and global_safe_alias_report[
                    "conditional_primary_assignment_count"
                ]
                == global_safe_alias_report["safe_alias_assignment_count"]
                and global_safe_alias_report[
                    "alias_codes_default_width_only"
                ]
                and global_safe_alias_report["slps"]["reread_exact"]
                and global_safe_alias_report["compdata"]["reread_exact"]
                and global_safe_alias_report[
                    "compdata_round_trip_exact"
                ]
            ),
            "scenario_select_labels_aligned": (
                scenario_select_report["geometry"]["centers_aligned"]
                and scenario_select_report["geometry"][
                    "changed_bytes_confined_to_x_coordinates"
                ]
                and scenario_description_layout_report["centers_aligned"]
                and scenario_description_layout_report["reread_exact"]
                and scenario_description_layout_report[
                    "slps_size_preserved"
                ]
                and scenario_description_layout_report[
                    "changed_bytes_confined_to_x_coordinates"
                ]
            ),
            "intermission_list_safe_aliases_scoped": (
                geometry_report["executable_geometry_patch_applied"] is False
                and geometry_report["original_list_renderer_preserved"] is True
                and pilot_name_report["surface_safe_aliases"][
                    "assignment_count"
                ]
                == font_manifest["mapping"][
                    "surface_alias_assignment_count"
                ]
                and pilot_name_report["surface_safe_aliases"][
                    "alias_codes_outside_conditional_range"
                ]
                and pilot_name_report["surface_safe_aliases"][
                    "fixed_field_capacities_preserved"
                ]
                and pilot_name_report["surface_safe_aliases"][
                    "pointer_bytes_unchanged"
                ]
            ),
        },
        "runtime": {
            "status": "not_tested",
            "reason": "The exact ISO and fresh PCSX2 target-flow evidence are still pending.",
        },
    }
    if not all(report["acceptance"].values()):
        raise FullStoryComponentError(
            f"full-story component acceptance failed: {report['acceptance']}"
        )
    if incremental:
        payloads = {
            member: payload
            for member, payload in payloads.items()
            if member in affected_members
        }
    return payloads, report


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = _json(config_path)
    output_root = require_work_output(
        args.output_root or _project_path(config["outputs"]["component_root"]),
        WORK_ROOT,
    )
    report_path = output_root / "component-validation.json"
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        if args.incremental:
            manifest_path = _project_path(config["outputs"]["manifest"])
            if not manifest_path.is_file():
                raise FullStoryComponentError(
                    "incremental build requires a prior full component manifest"
                )
            prior_report = _json(manifest_path)
            _validate_prior_component_outputs(output_root, prior_report)
            remaining_reference = config.get("remaining_ui", {}).get(
                "translations"
            )
            remaining_ui_path, remaining_ui_data = _locked_file(
                remaining_reference,
                label="remaining UI translations",
            )
            remaining_ui = json.loads(remaining_ui_data.decode("utf-8"))
            state = _load_or_seed_incremental_state(
                config_path=config_path,
                config=config,
                output_root=output_root,
                manifest_path=manifest_path,
                manifest=prior_report,
                remaining_ui_path=remaining_ui_path,
                remaining_ui=remaining_ui,
            )
            affected_members, reasons = _plan_incremental_members(
                baseline_config=state["config"],
                current_config=config,
                baseline_remaining_ui=state["remaining_ui"],
                current_remaining_ui=remaining_ui,
                prior_report=prior_report,
            )
            print(
                "[incremental] affected members:",
                ", ".join(sorted(affected_members)) or "none",
                flush=True,
            )
            if reasons:
                print(
                    "[incremental] reasons:",
                    ", ".join(reasons),
                    flush=True,
                )
            if affected_members:
                fixed_slps_reasons = {
                    "remaining-ui:slps_by_offset",
                    "remaining-ui:accepted_current_preimages_by_offset",
                }
                if affected_members == {SLPS_MEMBER} and set(reasons) <= (
                    fixed_slps_reasons
                ):
                    payloads, report = _build_incremental_fixed_slps(
                        config_path=config_path,
                        config=config,
                        output_root=output_root,
                        prior_report=prior_report,
                        baseline_remaining_ui=state["remaining_ui"],
                        current_remaining_ui=remaining_ui,
                    )
                else:
                    payloads, report = build(
                        config_path,
                        output_root,
                        affected_members=affected_members,
                        prior_report=prior_report,
                    )
            else:
                payloads, report = {}, prior_report
        else:
            payloads, report = build(config_path, output_root)
    except (
        KeyError,
        OSError,
        FullStoryComponentError,
        WorldMapTitleError,
    ) as error:
        raise SystemExit(f"full-story component build failed: {error}") from error
    for name, payload in payloads.items():
        path = output_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest_path = _project_path(config["outputs"]["manifest"])
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file() or _json(manifest_path) != report:
            raise SystemExit(
                "full-story component manifest drift; review the work report, "
                "then rerun with --refresh-manifest"
            )
        manifest_status = "verified"
    _write_incremental_state(
        config_path=config_path,
        config=config,
        output_root=output_root,
        manifest_path=manifest_path,
    )
    print(
        "full-story components:",
        f"stages={report['story']['stage_count']}",
        f"updated_members={len(payloads)}",
        f"font={report['composition']['font_encoded_size']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
