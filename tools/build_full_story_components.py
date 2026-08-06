#!/usr/bin/env python3
"""Compose the P10 UI, complete story font, and complete STAGE components."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from srwz.codec import decode, reencode_changed_suffix
    from srwz.diagnostics import require_work_output
    from srwz.display_names import (
        DisplayNameError,
        load_display_name_source,
        parse_display_names,
    )
    from srwz.font import decode_vt1_font_segment, sha256_bytes
    from srwz.menu import parse_menu_file
    from srwz.intermission_font_geometry import (
        IntermissionFontGeometryError,
        IntermissionFontGeometryMetrics,
        apply_intermission_font_geometry_patch,
    )
    from srwz.iso_layout import (
        CORE_ARCHIVE_SPECS,
        read_executable_archive_offsets,
    )
    from srwz.text import (
        SrwzTextEncodeError,
        decode_text,
        encode_text,
        load_text_table,
        normalize_original_fullwidth_ascii,
        original_fullwidth_ascii_overrides,
    )
    from srwz.ui_menu import (
        project_ui_runtime_text_table,
    )
    from srwz.writeback import replace_archive_chunk_with_preceding_zero_slack
    from srwz.writers import (
        WritebackError,
        build_executable_offset_patch_plan,
        replace_menu_texts_in_place,
    )
except ModuleNotFoundError:
    from tools.srwz.codec import decode, reencode_changed_suffix
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.display_names import (
        DisplayNameError,
        load_display_name_source,
        parse_display_names,
    )
    from tools.srwz.font import decode_vt1_font_segment, sha256_bytes
    from tools.srwz.menu import parse_menu_file
    from tools.srwz.intermission_font_geometry import (
        IntermissionFontGeometryError,
        IntermissionFontGeometryMetrics,
        apply_intermission_font_geometry_patch,
    )
    from tools.srwz.iso_layout import (
        CORE_ARCHIVE_SPECS,
        read_executable_archive_offsets,
    )
    from tools.srwz.text import (
        SrwzTextEncodeError,
        decode_text,
        encode_text,
        load_text_table,
        normalize_original_fullwidth_ascii,
        original_fullwidth_ascii_overrides,
    )
    from tools.srwz.ui_menu import (
        project_ui_runtime_text_table,
    )
    from tools.srwz.writeback import (
        replace_archive_chunk_with_preceding_zero_slack,
    )
    from tools.srwz.writers import (
        WritebackError,
        build_executable_offset_patch_plan,
        replace_menu_texts_in_place,
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


def _apply_full_pilot_names(
    stored_compdata: bytes,
    reference: dict,
    font_manifest: dict,
) -> tuple[bytes, dict, Path, Path, Path]:
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
    except DisplayNameError as error:
        raise FullStoryComponentError(str(error)) from error
    speaker_document = json.loads(speaker_data.decode("utf-8"))
    speaker_entries = speaker_document.get("entries")
    if not isinstance(speaker_entries, list) or not speaker_entries:
        raise FullStoryComponentError("story speaker corpus has no entries")
    by_source: dict[str, str] = {}
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
        previous = by_source.setdefault(source_hash, translation)
        if previous != translation:
            raise FullStoryComponentError(
                f"conflicting story speaker translation: {source_hash}"
            )

    include_fields = reference.get("include_fields")
    if (
        not isinstance(include_fields, list)
        or not include_fields
        or any(field not in {"display", "family", "given"} for field in include_fields)
        or len(set(include_fields)) != len(include_fields)
    ):
        raise FullStoryComponentError("full pilot-name field selection is invalid")
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
        len(by_source) != expected.get("unique_source_count")
        or len(selected) != expected.get("selected_entry_count")
        or field_counts != expected.get("field_entry_counts")
    ):
        raise FullStoryComponentError("full pilot-name selection drift")

    decoded = decode(stored_compdata)
    if decoded.consumed != len(stored_compdata):
        raise FullStoryComponentError("base COMPDATA has trailing compressed bytes")
    table_path = _project_path(structure["text_table"]["path"])
    table = load_text_table(table_path)
    source_table = project_ui_runtime_text_table(table, overrides)
    encoding_overrides = _stored_text_overrides(table, overrides)
    output_table = project_ui_runtime_text_table(
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
    current_by_id = {entry.entry_id: entry for entry in current_names.pilot_entries}
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
    alias_output_table = project_ui_runtime_text_table(
        project_ui_runtime_text_table(source_table, menu_surface_aliases),
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
    reread_by_id = {entry.entry_id: entry for entry in reread.pilot_entries}
    for original in selected:
        if (
            reread_by_id[original.entry_id].text
            != by_source[original.source_text_sha256]
        ):
            raise FullStoryComponentError(
                f"pilot-name readback mismatch: {original.entry_id}"
            )

    codec = reference.get("codec")
    if not isinstance(codec, dict) or codec.get("strategy") != "maximum":
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
    if any(offset not in allowed_offsets for offset in changed_offsets):
        raise FullStoryComponentError("pilot-name write escaped selected fields")
    return rebuilt, {
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
    }, structure_path, speaker_path, proposal_path


def _apply_full_stage_titles(
    slps: bytes,
    stored_compdata: bytes,
    reference: dict,
    font_manifest: dict,
    codec: dict,
) -> tuple[bytes, bytes, dict, tuple[Path, Path, Path]]:
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
    current_table = project_ui_runtime_text_table(table, primary_overrides)
    current_table = project_ui_runtime_text_table(
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
            replacements=stage_replacements,
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

    if not isinstance(codec, dict) or codec.get("strategy") != "maximum":
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
    return slps_write.data, rebuilt_compdata, {
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
    }, (stage_path, format_path, descriptor_path)


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
    if (
        alias_report.get("all_selected_assignments") is not True
        or alias_report.get("unaliased_conditional_assignment_count") != 0
        or set(aliases) != conditional_characters
        or any(0x8140 <= code < 0x889F for code in aliases.values())
    ):
        raise FullStoryComponentError("global safe-alias contract failed")

    table = load_text_table(
        PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    source_table = project_ui_runtime_text_table(table, primary)
    source_table = project_ui_runtime_text_table(source_table, aliases)
    ascii_overrides = original_fullwidth_ascii_overrides(table)
    output_table = project_ui_runtime_text_table(
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
        "conditional_primary_assignment_count": len(conditional_characters),
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
    base_proposal = font_manifest.get("inputs", {}).get("base_proposal", {})
    expected_base_proposal = base_manifest.get("inputs", {}).get("codebook", {}).get(
        "proposal", {}
    )
    if (
        base_proposal.get("path") != expected_base_proposal.get("path")
        or base_proposal.get("sha256") != expected_base_proposal.get("sha256")
    ):
        raise FullStoryComponentError("full-story font does not inherit P10 exactly")
    font_slps_path, font_slps = _locked_file(
        font["slps"], label="full-story font SLPS"
    )
    font_vt1_path, font_vt1 = _locked_file(
        font["vt1"], label="full-story font VT1"
    )
    font_outputs = font_manifest.get("font_component", {}).get("outputs", {})
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
        != 0
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

    composition = config.get("composition", {})
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
    expected_decoded_hash = font_manifest["font_component"]["decoded_sha256"]
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
        font_proposal_path,
    ) = _apply_full_pilot_names(
        base_payloads["compdata"],
        config.get("full_pilot_names"),
        font_manifest,
    )
    (
        output_slps,
        output_compdata,
        stage_title_report,
        stage_title_input_paths,
    ) = _apply_full_stage_titles(
        output_slps,
        output_compdata,
        config.get("full_stage_titles"),
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

    payloads = {
        "SLPS_258.87": output_slps,
        "DATA/VT1.BIN": output_vt1,
        "DATA/COMPDATA.BN": output_compdata,
        "DATA/MTV_PROS.BIN": base_payloads["mtv_pros"],
        "DATA/STAGE.BIN": stage_payload,
        "HEDBDY/HB.BIN": hb_payload,
        "KURODATA/KVMDATA.BIN": kvm_payload,
    }
    output_paths = {name: output_root / name for name in payloads}
    stage_headrooms = [
        item["source_chunk_size"] - item["output_encoded_size"]
        for item in stage_report["stages"]
    ]
    report = {
        "schema_version": 1,
        "status": "integrated_p10_ui_full_story_components_validated_runtime_pending",
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
            "full_story_font_proposal": _file_lock(
                font_proposal_path, font_proposal_path.read_bytes()
            ),
            "stage_names": _file_lock(
                stage_title_input_paths[0], stage_title_input_paths[0].read_bytes()
            ),
            "stage_title_format": _file_lock(
                stage_title_input_paths[1], stage_title_input_paths[1].read_bytes()
            ),
            "menu_descriptor": _file_lock(
                stage_title_input_paths[2], stage_title_input_paths[2].read_bytes()
            ),
            "font_slps": _file_lock(font_slps_path, font_slps),
            "font_vt1": _file_lock(font_vt1_path, font_vt1),
            "stage": _file_lock(stage_path, stage_payload),
            "hb": _file_lock(hb_path, hb_payload),
            "kvmdata": _file_lock(kvm_path, kvm_payload),
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
        "global_safe_aliases": global_safe_alias_report,
        "outputs": {
            name: _output_lock(output_paths[name], payload)
            for name, payload in payloads.items()
        },
        "acceptance": {
            "p10_ui_members_inherited_exact": True,
            "p10_codebook_assignments_inherited_exact": True,
            "full_story_font_missing_character_count_zero": (
                font_manifest["full_story_renderer_coverage"][
                    "missing_renderer_character_count"
                ]
                == 0
            ),
            "full_story_font_original_han_count_zero": (
                font_manifest["full_story_renderer_coverage"][
                    "original_font_han_count"
                ]
                == 0
            ),
            "full_story_font_original_visible_character_count_zero": (
                font_manifest["full_story_renderer_coverage"][
                    "original_font_visible_character_count"
                ]
                == 0
            ),
            "font_codec_round_trip_exact": font_manifest["font_component"][
                "archive"
            ]["offset_reread_exact"],
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
            "intermission_list_safe_aliases_scoped": (
                geometry_report["executable_geometry_patch_applied"] is False
                and geometry_report["original_list_renderer_preserved"] is True
                and pilot_name_report["surface_safe_aliases"][
                    "assignment_count"
                ]
                == font_manifest["surface_safe_aliases"]["assignment_count"]
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
    except (KeyError, OSError, FullStoryComponentError) as error:
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
