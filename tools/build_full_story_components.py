#!/usr/bin/env python3
"""Compose the release UI, global font, story, overview, and battle components."""

from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

try:
    from srwz.codec import decode, encode, reencode_changed_suffix
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
    from tools.srwz.codec import decode, encode, reencode_changed_suffix
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
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
            load_display_name_source(PROJECT_ROOT, structure_path)
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

    decoded = decode(stored_compdata)
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
    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError("full pilot-name codec policy is invalid")
    try:
        rebuilt = reencode_changed_suffix(
            stored_compdata,
            bytes(output),
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=codec["max_output_size"],
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"full pilot-name COMPDATA compression failed: {error}"
        ) from error
    round_trip = decode(rebuilt)
    if (
        round_trip.consumed != len(rebuilt)
        or round_trip.output != bytes(output)
        or round_trip.flags != decoded.flags
    ):
        raise FullStoryComponentError("full pilot-name COMPDATA round-trip failed")
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
        "output_compressed_size": len(rebuilt),
        "compressed_sector_budget": codec["max_output_size"],
        "codec": {
            "strategy": codec["strategy"],
            "min_match_length": codec["min_match_length"],
            "max_match_chain": codec["max_match_chain"],
            "lazy_matching": codec["lazy_matching"],
        },
        "codec_round_trip_exact": True,
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
    decoded = decode(stored_compdata)
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

    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError("stage-title codec policy is invalid")
    try:
        rebuilt_compdata = reencode_changed_suffix(
            stored_compdata,
            compdata_write.data,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=codec["max_output_size"],
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"stage-title COMPDATA compression failed: {error}"
        ) from error
    round_trip = decode(rebuilt_compdata)
    if (
        round_trip.consumed != len(rebuilt_compdata)
        or round_trip.output != compdata_write.data
        or round_trip.flags != decoded.flags
    ):
        raise FullStoryComponentError("stage-title COMPDATA round-trip failed")
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
        "compdata_output_size": len(rebuilt_compdata),
        "compdata_round_trip_exact": True,
        "slps_size_preserved": len(slps_write.data) == len(slps),
        "graphics": graphic_report,
    }, (stage_path, format_path, descriptor_path)


def _apply_stage_overviews(
    stage: bytes,
    hb: bytes,
    reference: dict,
    font_manifest: dict,
    codec: dict,
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
    decoded = decode(stored)
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
            "output_encoded_size": len(rebuilt),
            "output_encoded_sha256": sha256_bytes(rebuilt),
            "output_padding_size": len(rebuilt_stored) - len(rebuilt),
            "codec_round_trip_exact": True,
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


def _apply_stage_system_dialogues(
    stage: bytes,
    hb: bytes,
    reference: dict,
    font_manifest: dict,
    codec: dict,
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
    current_decoded = decode(stored)
    original_decoded = decode(original_stored)
    if (
        any(stored[current_decoded.consumed :])
        or any(original_stored[original_decoded.consumed :])
        or len(current_decoded.output) != len(original_decoded.output)
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
    try:
        encoded = reencode_changed_suffix(
            stored[: current_decoded.consumed],
            write.data,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=len(stored),
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
            "output_encoded_size": len(encoded),
            "codec_round_trip_exact": True,
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

    original_decoded = decode(original_compdata)
    current_decoded = decode(stored_compdata)
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

    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError("remaining UI codec policy is invalid")
    try:
        rebuilt_compdata = reencode_changed_suffix(
            stored_compdata,
            parts_write.data,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=codec["max_output_size"],
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"remaining UI COMPDATA compression failed: {error}"
        ) from error
    round_trip = decode(rebuilt_compdata)
    if (
        round_trip.consumed != len(rebuilt_compdata)
        or round_trip.output != parts_write.data
        or round_trip.flags != current_decoded.flags
    ):
        raise FullStoryComponentError("remaining UI COMPDATA round-trip failed")

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
        "compdata_output_size": len(rebuilt_compdata),
        "compdata_sector_budget": codec["max_output_size"],
        "compdata_round_trip_exact": True,
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

    decoded = decode(stored_compdata)
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
        ranges = []
        for offset in sorted(target_offsets):
            decoded_target = decode_text(data, offset, source_table)
            ranges.append((offset, offset + decoded_target.consumed))
        merged_ranges = []
        for start, end in ranges:
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
                (
                    offset,
                    offset + decode_text(data, offset, source_table).consumed,
                )
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
        selected_entries = sum(
            any(
                start <= changed < end
                for changed in changed_offsets
                for start, end in (
                    (
                        offset,
                        offset
                        + decode_text(data, offset, source_table).consumed,
                    )
                    for offset in entry.target_offsets
                )
            )
            for entry in parsed.entries
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
    try:
        rebuilt_compdata = reencode_changed_suffix(
            stored_compdata,
            rewritten_compdata,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=codec["max_output_size"],
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"global safe-alias COMPDATA compression failed: {error}"
        ) from error
    round_trip = decode(rebuilt_compdata)
    if (
        round_trip.consumed != len(rebuilt_compdata)
        or round_trip.output != rewritten_compdata
        or round_trip.flags != decoded.flags
    ):
        raise FullStoryComponentError(
            "global safe-alias COMPDATA round-trip failed"
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
        "compdata_output_size": len(rebuilt_compdata),
        "compdata_round_trip_exact": True,
    }


def _apply_reviewed_weapon_names(
    stored_compdata: bytes,
    reference: dict,
    descriptor_path: Path,
    original_compdata_path: Path,
    font_manifest: dict,
    codec: dict,
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
    original_decoded = decode(original_compdata)
    current_decoded = decode(stored_compdata)
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
    if not isinstance(codec, dict) or codec.get("strategy") != "rust-fit":
        raise FullStoryComponentError("reviewed weapon codec policy is invalid")
    try:
        rebuilt = reencode_changed_suffix(
            stored_compdata,
            rewritten,
            strategy=codec["strategy"],
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=codec["lazy_matching"],
            max_output_size=codec["max_output_size"],
        )
    except (RuntimeError, ValueError) as error:
        raise FullStoryComponentError(
            f"reviewed weapon COMPDATA compression failed: {error}"
        ) from error
    round_trip = decode(rebuilt)
    if (
        round_trip.consumed != len(rebuilt)
        or round_trip.output != rewritten
        or round_trip.flags != current_decoded.flags
    ):
        raise FullStoryComponentError(
            "reviewed weapon COMPDATA round-trip failed"
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
            "compdata_output_size": len(rebuilt),
            "compdata_sector_budget": codec["max_output_size"],
            "codec_round_trip_exact": True,
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


def build(config_path: Path, output_root: Path) -> tuple[dict[str, bytes], dict]:
    config = _json(config_path)
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
    final_font = decode_vt1_font_segment(output_slps, output_vt1).decoded
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

    (
        output_compdata,
        pilot_name_report,
        pilot_structure_path,
        story_speaker_path,
        residual_name_path,
        unit_name_path,
        font_proposal_path,
    ) = _apply_full_pilot_names(
        base_payloads["compdata"],
        config.get("full_pilot_names"),
        font_manifest,
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
        output_compdata,
        config.get("full_stage_titles"),
        font_manifest,
        config["full_pilot_names"]["codec"],
        final_font,
        release_by_character,
    )
    (
        output_slps,
        output_compdata,
        remaining_ui_report,
        remaining_ui_input_paths,
    ) = _apply_remaining_ui(
        output_slps,
        output_compdata,
        config.get("remaining_ui"),
        stage_title_input_paths[2],
        font_manifest,
        config["full_pilot_names"]["codec"],
    )
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
        reviewed_weapon_report,
        reviewed_weapon_corpus_path,
    ) = _apply_reviewed_weapon_names(
        output_compdata,
        config.get("reviewed_weapons"),
        stage_title_input_paths[2],
        remaining_ui_input_paths[2],
        font_manifest,
        config["full_pilot_names"]["codec"],
    )
    (
        output_slps,
        output_compdata,
        global_safe_alias_report,
    ) = _apply_global_safe_aliases(
        output_slps,
        output_compdata,
        stage_title_input_paths[2],
        font_manifest,
        config["full_pilot_names"]["codec"],
    )
    (
        output_slps,
        scenario_description_layout_report,
    ) = _apply_scenario_description_layout(
        output_slps,
        config["scenario_select_effect"].get("description_layout"),
    )
    (
        output_srvc_bin,
        output_srvc_seg,
        srvc_report,
        srvc_input_paths,
    ) = _apply_srvc_battle_text(
        config.get("srvc_battle_text"),
        font_manifest,
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
    )
    (
        output_stage,
        stage_fixed_formation_report,
        original_stage_path,
    ) = _apply_stage_fixed_formation_names(
        output_stage,
        hb_payload,
        config.get("remaining_ui"),
        remaining_ui_input_paths[0],
        font_manifest,
        config["full_pilot_names"]["codec"],
    )
    remaining_ui_report["stage_fixed_formation"] = (
        stage_fixed_formation_report
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
    )
    remaining_ui_report["stage_system_dialogue"] = (
        stage_system_dialogue_report
    )
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
    (
        output_mapmodel,
        world_map_title_report,
        world_map_title_input_paths,
    ) = build_world_map_titles(
        PROJECT_ROOT,
        WORK_ROOT,
        config.get("world_map_titles"),
        preview_root=output_root / "previews/world-map-titles",
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
    }
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
            "remaining_ui_parts": _file_lock(
                remaining_ui_input_paths[1],
                remaining_ui_input_paths[1].read_bytes(),
            ),
            "reviewed_weapons": _file_lock(
                reviewed_weapon_corpus_path,
                reviewed_weapon_corpus_path.read_bytes(),
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
        },
        "compression": {
            "backend_policy": "rust-only",
            "python_encoder_used": False,
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
        "reviewed_weapons": reviewed_weapon_report,
        "srvc_battle_text": srvc_report,
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
    print(
        "full-story components:",
        f"stages={report['story']['stage_count']}",
        f"members={len(payloads)}",
        f"font={report['composition']['font_encoded_size']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
