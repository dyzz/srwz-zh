#!/usr/bin/env python3
"""Independently reread every selected Chinese story entry from the final ISO."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from srwz.archive import sha256_file
from srwz.chinese_layout import dialogue_line_widths
from srwz.codec import decode
from srwz.display_names import load_display_name_source, parse_display_names
from srwz.font import (
    GLYPH_COUNT,
    GLYPH_SIZE,
    ascii_glyph_index,
    decode_vt1_font_segment,
    glyph_index_for_code,
    read_extended_glyph_table,
    sha256_bytes,
    standard_glyph_index,
)
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.hsfc_overview import (
    group_hsfc_overviews,
    parse_hsfc_overviews,
)
from srwz.menu import parse_menu_file
from srwz.psmt4 import unswizzle_psmt4
from srwz.stage import parse_stage, read_stage_function_addresses
from srwz.stage_overview import parse_stage_overviews
from srwz.tim2 import scan_tim2
from srwz.text import (
    ORIGINAL_FULLWIDTH_ASCII,
    RUNTIME_SUBSTITUTION_TOKEN,
    TextTable,
    control_notation_tokens,
    decode_text,
    encode_text,
    load_text_table,
    normalize_original_fullwidth_ascii,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = (
    PROJECT_ROOT
    / "build/iso/zh-release-full-story/srwz-zh-release-full-story-r8.iso"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "work/verification/zh-release-full-story-content.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "manifests/zh-release-full-story-iso-content-validation.json"
)
BUILD_CONFIG = PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
COMPONENT_REPORT = (
    PROJECT_ROOT
    / "manifests/full-story-components-validation.json"
)
FONT_MANIFEST = PROJECT_ROOT / "manifests/zh-release-font-validation.json"
SOURCE_CONTENT_CONFIG = PROJECT_ROOT / "config/story-component.json"
SOURCE_FONT_CONFIG = (
    PROJECT_ROOT / "config/fonts/original-font-baseline.json"
)
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
BASE_CODEBOOK = PROJECT_ROOT / "config/encoding/codebook.json"
CODEBOOK_PROPOSAL = (
    PROJECT_ROOT / "work/writeback/zh-release-codebook-proposal.json"
)
FULL_COMPONENT_CONFIG = PROJECT_ROOT / "config/full-story-components.json"
MENU_DESCRIPTOR = PROJECT_ROOT / "vendor/upstream-python/project/menu_files.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--build-config", type=Path, default=BUILD_CONFIG)
    parser.add_argument(
        "--component-report",
        type=Path,
        default=COMPONENT_REPORT,
    )
    parser.add_argument("--font-manifest", type=Path, default=FONT_MANIFEST)
    parser.add_argument(
        "--codebook-proposal",
        type=Path,
        default=CODEBOOK_PROPOSAL,
    )
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_translations(path: Path) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["id"]: normalize_original_fullwidth_ascii(
            entry["translation"]
        )
        for entry in document["entries"]
    }


def load_overrides(
    proposal_path: Path,
) -> tuple[dict[str, int], dict[str, int], dict]:
    base = json.loads(BASE_CODEBOOK.read_text(encoding="utf-8"))
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assignments = [*base["assignments"], *proposal["assignments"]]
    overrides = {
        assignment["character"]: int(assignment["code"], 16)
        for assignment in assignments
    }
    aliases = {}
    seen_codes = set(overrides.values())
    for assignment in proposal.get("surface_alias_assignments", []):
        character = assignment.get("character")
        primary_code = assignment.get("primary_code")
        try:
            code = int(assignment.get("code"), 16)
        except (TypeError, ValueError) as error:
            raise SystemExit("surface alias code is malformed") from error
        if (
            not isinstance(character, str)
            or len(character) != 1
            or character in aliases
            or character not in overrides
            or primary_code != f"{overrides[character]:04X}"
            or code in seen_codes
        ):
            raise SystemExit("surface alias mapping is not one-to-one")
        aliases[character] = code
        seen_codes.add(code)
    conditional_characters = {
        assignment["character"]
        for assignment in proposal["assignments"]
        if 0x8140 <= int(assignment["code"], 16) < 0x889F
    }
    alias_report = proposal.get("surface_safe_aliases", {})
    unaliased_characters = conditional_characters - set(aliases)
    if (
        not set(aliases) <= conditional_characters
        or alias_report.get("assignment_count") != len(aliases)
        or alias_report.get("conditional_primary_assignment_count")
        != len(conditional_characters)
        or alias_report.get("unaliased_conditional_assignment_count")
        != len(unaliased_characters)
        or alias_report.get("all_selected_assignments")
        is not (not unaliased_characters)
        or any(0x8140 <= code < 0x889F for code in aliases.values())
    ):
        raise SystemExit("global safe-alias proposal contract failed")
    return overrides, aliases, proposal


def expected_font_component(
    config: dict,
    component_manifest: dict | None,
    font_manifest: dict,
) -> dict:
    if not config.get("require_component_output_binding"):
        return font_manifest["font_component"]
    if component_manifest is None:
        raise SystemExit("bound component manifest is missing")
    composition = component_manifest["composition"]
    return {
        "encoded_size": composition["font_encoded_size"],
        "decoded_size": GLYPH_COUNT * GLYPH_SIZE,
        "decoded_sha256": composition["font_decoded_sha256"],
    }


def expected_story_entry_count(
    config: dict,
    component_manifest: dict | None,
    font_manifest: dict,
) -> int:
    if config.get("require_component_output_binding"):
        if component_manifest is None:
            raise SystemExit("bound component manifest is missing")
        story = component_manifest["story"]
        return (
            story["translated_allocation_count"] + story["speaker_count"]
        )
    return font_manifest["full_story_renderer_coverage"][
        "unique_entry_count"
    ]


def renderer_coverage(font_manifest: dict) -> dict:
    if "full_story_renderer_coverage" in font_manifest:
        coverage = font_manifest["full_story_renderer_coverage"]
        return {
            "missing_character_count": coverage[
                "missing_renderer_character_count"
            ],
            "original_font_han_count": coverage[
                "original_font_han_count"
            ],
            "original_font_visible_character_count": coverage[
                "original_font_visible_character_count"
            ],
        }
    coverage = font_manifest["coverage"]
    return {
        "missing_character_count": coverage["missing_character_count"],
        "original_font_han_count": coverage["original_font_han_count"],
        "original_font_visible_character_count": coverage[
            "original_font_visible_character_count"
        ],
    }


def read_members(iso_path: Path, paths: tuple[str, ...]) -> dict[str, bytes]:
    image = scan_iso9660(iso_path)
    members = member_map(image)
    missing = sorted(set(paths) - set(members))
    if missing:
        raise SystemExit(f"final ISO is missing members: {missing!r}")
    result = {}
    with iso_path.open("rb") as source:
        for path in paths:
            member = members[path]
            source.seek(member.extent_lba * SECTOR_SIZE)
            data = source.read(member.size)
            if len(data) != member.size:
                raise SystemExit(f"short final ISO member read: {path}")
            result[path] = data
    return result


def stage_index(entry_id: str) -> int:
    return int(entry_id.split("/")[1])


def verify_stock_ascii_glyphs(
    source_table: TextTable,
    ascii_overrides: dict[str, int],
    final_font: bytes,
) -> dict:
    """Prove both ASCII encodings still resolve to stock glyph bytes."""

    source_config = json.loads(
        SOURCE_FONT_CONFIG.read_text(encoding="utf-8")
    )
    source_members = {}
    for name in ("slps", "vt1"):
        spec = source_config["members"][name]
        path = project_path(Path(spec["path"]))
        data = path.read_bytes()
        if len(data) != spec["size"] or sha256_bytes(data) != spec["sha256"]:
            raise SystemExit(f"source font member drift: {name}")
        source_members[name] = data
    source_font = decode_vt1_font_segment(
        source_members["slps"],
        source_members["vt1"],
    ).decoded
    if len(source_font) != len(final_font):
        raise SystemExit("source/final decoded font sizes differ")

    glyph_indices = {}
    for character in sorted(ORIGINAL_FULLWIDTH_ASCII):
        raw_index = ascii_glyph_index(ord(character))
        fullwidth_code = ascii_overrides[character]
        fullwidth_index = standard_glyph_index(fullwidth_code)
        if raw_index != fullwidth_index:
            raise SystemExit(
                "raw/fullwidth stock ASCII glyph mapping differs: "
                f"{character!r}"
            )
        start = raw_index * GLYPH_SIZE
        end = start + GLYPH_SIZE
        if source_font[start:end] != final_font[start:end]:
            raise SystemExit(
                f"stock ASCII glyph was modified: {character!r}"
            )
        glyph_indices[character] = raw_index

    return {
        "mode": "surface-aware-original-game-glyphs",
        "stock_alphanumeric_glyph_count": len(glyph_indices),
        "stock_alphanumeric_glyphs_byte_exact": True,
        "raw_and_fullwidth_codes_share_glyph_slots": True,
        "story_and_display_name_storage": "original_fullwidth_two_byte",
        "stage_title_storage": (
            "stock_raw_ascii_except_tag_bytes_31_35"
        ),
        "runtime_tokens_raw_ascii": True,
        "source_decoded_font_sha256": sha256_bytes(source_font),
    }


def verify_targeted_ui_glyphs(
    slps: bytes,
    output_table: TextTable,
    final_font: bytes,
) -> dict:
    """Require visible glyph rasters for the reported new-game regressions."""

    target_texts = {
        "male_default_name": "兰德·特拉维斯",
        "male_profile": (
            "与搭档在荒野经营修理店的男人"
            "自称烈焰豪爽而热血但有时会热情过头"
        ),
    }
    extended = read_extended_glyph_table(slps)
    by_character = {}
    for character in sorted(set("".join(target_texts.values()))):
        code = output_table.inverse_characters.get(character)
        if code is None:
            raise SystemExit(
                f"targeted new-game glyph has no output code: {character!r}"
            )
        glyph_index = glyph_index_for_code(code, extended)
        start = glyph_index * GLYPH_SIZE
        packed = final_font[start : start + GLYPH_SIZE]
        ink_pixel_count = sum(
            (value & 0x0F) != 0 for value in packed
        ) + sum((value >> 4) != 0 for value in packed)
        if len(packed) != GLYPH_SIZE or ink_pixel_count == 0:
            raise SystemExit(
                f"targeted new-game glyph is blank: {character!r}"
            )
        by_character[character] = {
            "code": f"{code:04X}",
            "glyph_index": glyph_index,
            "ink_pixel_count": ink_pixel_count,
            "packed_sha256": sha256_bytes(packed),
        }
    return {
        "texts": target_texts,
        "unique_character_count": len(by_character),
        "characters": by_character,
        "all_target_glyphs_present_and_nonblank": True,
    }


def verify_scenario_select_effect(
    slps: bytes,
    archive: bytes,
    component_manifest: dict | None,
) -> dict:
    """Reread the localized scenario labels from VEFF effect 295."""

    config = json.loads(FULL_COMPONENT_CONFIG.read_text(encoding="utf-8"))
    effect = config.get("scenario_select_effect")
    if not isinstance(effect, dict):
        raise SystemExit("scenario-select effect config is missing")
    archive_spec = effect["archive"]
    target = effect["target"]
    raster = effect["raster"]
    spec = ExecutableOffsetSpec(
        name=archive_spec["name"],
        member=archive_spec["member"],
        table_start=int(archive_spec["table_start"], 0),
        table_end=int(archive_spec["table_end"], 0),
    )
    offsets = read_executable_archive_offsets(slps, spec, len(archive))
    chunk_index = target["chunk_index"]
    if (
        offsets[chunk_index] != target["stored_start"]
        or offsets[chunk_index + 1] != target["stored_end"]
    ):
        raise SystemExit("final ISO scenario-select offsets drifted")
    stored = archive[offsets[chunk_index] : offsets[chunk_index + 1]]
    decoded = decode(stored)
    if any(stored[decoded.consumed :]):
        raise SystemExit("final ISO scenario-select padding is nonzero")
    records = scan_tim2(decoded.output)
    record = records[target["record_index"]]
    picture = record.pictures[target["picture_index"]]
    image_start = picture.offset + picture.header_size
    image_end = image_start + picture.image_size
    logical = unswizzle_psmt4(decoded.output[image_start:image_end])
    logical_sha256 = sha256_bytes(logical)
    expected = (
        component_manifest.get("scenario_select_effect", {})
        if component_manifest is not None
        else {}
    )
    expected_hash = expected.get("output_logical_image_sha256")
    labels = [segment["text"] for segment in raster["segments"]]
    composed_labels = effect.get("composed_labels")
    glyph_sampling = raster.get("glyph_sampling")
    if (
        expected_hash is None
        or logical_sha256 != expected_hash
        or labels != expected.get("labels")
        or composed_labels != expected.get("composed_labels")
        or glyph_sampling
        != "native_24px_center_crop_preserve_4bpp"
        or glyph_sampling != expected.get("glyph_sampling")
        or logical_sha256 == target["logical_image_sha256"]
    ):
        raise SystemExit("final ISO scenario-select title texture mismatch")
    segment_reports = []
    for segment in raster["segments"]:
        x = segment["x"]
        y = segment["y"]
        width = (
            (len(segment["text"]) - 1) * segment["advance"]
            + segment["glyph_width"]
        )
        ink_pixel_count = sum(
            logical[row * 256 + column] != 0
            for row in range(y, y + 24)
            for column in range(x, x + width)
        )
        intermediate_pixel_count = sum(
            0 < logical[row * 256 + column] < 15
            for row in range(y, y + 24)
            for column in range(x, x + width)
        )
        if ink_pixel_count == 0 or intermediate_pixel_count == 0:
            raise SystemExit(
                "final ISO scenario title segment is blank or binary-only: "
                f"{segment['text']}"
            )
        segment_reports.append(
            {
                "text": segment["text"],
                "x": x,
                "y": y,
                "width": width,
                "ink_pixel_count": ink_pixel_count,
                "intermediate_pixel_count": intermediate_pixel_count,
            }
        )
    return {
        "effect_id": target["effect_id"],
        "chunk_index": chunk_index,
        "record_index": target["record_index"],
        "picture_index": target["picture_index"],
        "labels": labels,
        "composed_labels": composed_labels,
        "glyph_sampling": glyph_sampling,
        "segments": segment_reports,
        "logical_image_sha256": logical_sha256,
        "source_title_texture_replaced": True,
        "all_label_segments_nonblank": True,
        "all_label_segments_native_4bpp_antialiased": True,
        "codec_padding_zero": True,
        "archive_offsets_preserved": True,
    }


def verify_final_compdata(
    stored_compdata: bytes,
    slps: bytes,
    source_table: TextTable,
    output_table: TextTable,
    surface_aliases: dict[str, int],
) -> dict:
    """Reread every selected COMPDATA/SLPS text family from the final ISO."""

    component_config = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )
    pilot_config = component_config["full_pilot_names"]
    structure_path = PROJECT_ROOT / pilot_config["structure"]["path"]
    structure, _source_data, source_names, _context = (
        load_display_name_source(PROJECT_ROOT, structure_path)
    )
    speaker_document = json.loads(
        (PROJECT_ROOT / pilot_config["story_speakers"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    story_by_source: dict[str, str] = {}
    for entry in speaker_document["entries"]:
        translation = normalize_original_fullwidth_ascii(
            entry["translation"]
        )
        if not translation:
            continue
        source_hash = entry["source_text_sha256"]
        previous = story_by_source.setdefault(source_hash, translation)
        if previous != translation:
            raise SystemExit(
                f"conflicting pilot-name translation: {source_hash}"
            )

    remaining_document = json.loads(
        (PROJECT_ROOT / pilot_config["residual_names"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    residual_by_text = remaining_document["display_names_by_source_text"]
    residual_by_source = {}
    matched_residual_texts = set()
    for entry in source_names.pilot_entries:
        if entry.text not in residual_by_text:
            continue
        matched_residual_texts.add(entry.text)
        translation = normalize_original_fullwidth_ascii(
            residual_by_text[entry.text]
        )
        previous = residual_by_source.setdefault(
            entry.source_text_sha256, translation
        )
        if previous != translation:
            raise SystemExit(
                f"conflicting residual pilot-name translation: {entry.text!r}"
            )
    if matched_residual_texts != set(residual_by_text):
        raise SystemExit("residual pilot-name source selection drift")
    if set(story_by_source) & set(residual_by_source):
        raise SystemExit("story and residual pilot-name selections overlap")
    by_source = {**story_by_source, **residual_by_source}

    include_fields = set(pilot_config["include_fields"])
    selected = tuple(
        entry
        for entry in source_names.pilot_entries
        if (
            entry.field in include_fields
            and entry.text
            and entry.source_text_sha256 in by_source
        )
    )
    expected = pilot_config["expected"]
    field_counts: dict[str, int] = {}
    for entry in selected:
        field_counts[entry.field] = field_counts.get(entry.field, 0) + 1
    if (
        len(story_by_source) != expected["story_unique_source_count"]
        or len(residual_by_text) != expected["residual_unique_source_count"]
        or len(by_source) != expected["unique_source_count"]
        or len(selected) != expected["selected_entry_count"]
        or field_counts != expected["field_entry_counts"]
    ):
        raise SystemExit("pilot-name source selection drift")

    decoded_compdata = decode(stored_compdata)
    if decoded_compdata.consumed != len(stored_compdata):
        raise SystemExit("final ISO COMPDATA has trailing compressed bytes")
    reread = parse_display_names(
        decoded_compdata.output,
        output_table,
        structure,
        verify_text_preimages=False,
    )
    actual_by_id = {entry.entry_id: entry for entry in reread.pilot_entries}
    examples = {}
    example_sources = {
        "マーイ",
        "マリン",
        "オリバー",
        "コトセット",
        "ファットマン",
        "ブルメ",
    }
    for source_entry in selected:
        actual_entry = actual_by_id.get(source_entry.entry_id)
        if actual_entry is None:
            raise SystemExit(
                f"final ISO pilot entry missing: {source_entry.entry_id}"
            )
        actual = actual_entry.text
        target = by_source[source_entry.source_text_sha256]
        if actual != target:
            raise SystemExit(
                f"final ISO pilot-name mismatch: {source_entry.entry_id}: "
                f"expected {target!r}, got {actual!r}"
            )
        if source_entry.text in example_sources:
            examples[source_entry.text] = actual

    descriptors = json.loads(MENU_DESCRIPTOR.read_text(encoding="utf-8"))
    descriptor = next(
        item for item in descriptors if item.get("friendly_name") == "Compdata"
    )
    parsed_menu = parse_menu_file(
        decoded_compdata.output,
        descriptor,
        output_table,
    )
    menu_by_id = {entry.entry_id: entry.text for entry in parsed_menu.entries}
    button_prompts = {
        "menu/Compdata/07/0000": "：确定",
        "menu/Compdata/07/0004": "：返回",
    }
    for entry_id, expected_text in button_prompts.items():
        if menu_by_id.get(entry_id) != expected_text:
            raise SystemExit(
                f"final ISO button prompt mismatch: {entry_id}: "
                f"expected {expected_text!r}, got {menu_by_id.get(entry_id)!r}"
            )

    remaining_config = component_config["remaining_ui"]
    original_compdata = decode(
        (PROJECT_ROOT / remaining_config["original_compdata"]["path"]).read_bytes()
    )
    original_slps = (
        PROJECT_ROOT / remaining_config["original_slps"]["path"]
    ).read_bytes()
    if original_compdata.consumed != remaining_config["original_compdata"]["size"]:
        raise SystemExit("original COMPDATA baseline has trailing bytes")

    def verify_offset_map(
        data: bytes,
        original: bytes,
        translations: dict[str, str],
        label: str,
    ) -> dict:
        minimum_headroom = None
        for raw_offset, raw_translation in translations.items():
            offset = int(raw_offset, 16)
            source = decode_text(original, offset, source_table)
            actual = decode_text(data, offset, output_table)
            translation = normalize_original_fullwidth_ascii(raw_translation)
            source_tokens = tuple(
                (token.kind, token.text)
                for token in control_notation_tokens(source.text)
            )
            target_tokens = tuple(
                (token.kind, token.text)
                for token in control_notation_tokens(translation)
            )
            if source_tokens != target_tokens:
                raise SystemExit(
                    f"{label} control-token drift at {raw_offset}"
                )
            if actual.text != translation or actual.consumed > source.consumed:
                raise SystemExit(
                    f"{label} mismatch at {raw_offset}: "
                    f"expected={translation!r} actual={actual.text!r}"
                )
            headroom = source.consumed - actual.consumed
            minimum_headroom = (
                headroom
                if minimum_headroom is None
                else min(minimum_headroom, headroom)
            )
        return {
            "entry_count": len(translations),
            "minimum_output_headroom": minimum_headroom,
            "placeholder_control_tokens_preserved": True,
            "readback_exact": True,
        }

    direct_report = verify_offset_map(
        decoded_compdata.output,
        original_compdata.output,
        remaining_document["compdata_direct_by_offset"],
        "remaining COMPDATA UI",
    )
    leadership_report = verify_offset_map(
        decoded_compdata.output,
        original_compdata.output,
        remaining_document["leadership_effect_by_offset"],
        "leadership effects",
    )
    slps_report = verify_offset_map(
        slps,
        original_slps,
        remaining_document["slps_by_offset"],
        "remaining SLPS UI",
    )

    new_game_name_expectations = {
        "0x33B440": "兰德",
        "0x33B448": "特拉维斯",
        "0x33E300": "兰德·特拉维斯",
        "0x3479C8": "兰德",
        "0x3479D0": "特拉维斯",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in new_game_name_expectations
    } != new_game_name_expectations:
        raise SystemExit("male new-game default-name offset contract drift")
    scenario_button_expectations = {
        "0x33BD4A": "：确定",
        "0x33BD58": "：取消",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in scenario_button_expectations
    } != scenario_button_expectations:
        raise SystemExit("scenario-select button-label offset contract drift")
    male_profile = remaining_document["compdata_direct_by_offset"].get(
        "0x7FD20"
    )
    expected_profile = (
        "与搭档在荒野经营修理店的男人。\n"
        "自称“烈焰”，豪爽而热血。\n"
        "但有时会热情过头。"
    )
    if male_profile != expected_profile:
        raise SystemExit("male new-game profile contract drift")
    profile_line_lengths = [len(line) for line in male_profile.splitlines()]
    if len(profile_line_lengths) != 3 or max(profile_line_lengths) > 24:
        raise SystemExit("male new-game profile exceeds its 24x3 layout")
    stored_profile = decode_text(
        decoded_compdata.output, 0x7FD20, output_table
    )
    profile_bytes = decoded_compdata.output[
        0x7FD20 : 0x7FD20 + stored_profile.consumed
    ]
    conditional_codes = []
    cursor = 0
    while cursor < len(profile_bytes):
        lead = profile_bytes[cursor]
        if lead in (0, 0x0A):
            cursor += 1
            continue
        if 0x31 <= lead <= 0x35:
            cursor += 2
            continue
        if 0x80 <= lead <= 0x9F or 0xE0 <= lead <= 0xEA:
            if cursor + 1 >= len(profile_bytes):
                raise SystemExit("male new-game profile has a truncated code")
            code = (lead << 8) | profile_bytes[cursor + 1]
            if 0x8140 <= code < 0x889F:
                conditional_codes.append(code)
            cursor += 2
            continue
        cursor += 1
    if conditional_codes:
        raise SystemExit(
            "male new-game profile still uses conditional-width codes: "
            + ", ".join(f"0x{code:04X}" for code in conditional_codes)
        )

    parts_document = json.loads(
        (PROJECT_ROOT / remaining_config["parts"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    original_parsed_menu = parse_menu_file(
        original_compdata.output, descriptor, source_table
    )
    original_menu_by_id = {
        entry.entry_id: entry for entry in original_parsed_menu.entries
    }
    final_menu_by_id = {entry.entry_id: entry for entry in parsed_menu.entries}
    written_part_count = 0
    preserved_part_count = 0
    for item in parts_document["entries"]:
        entry_id = item["id"]
        source_entry = original_menu_by_id.get(entry_id)
        actual_entry = final_menu_by_id.get(entry_id)
        if (
            source_entry is None
            or actual_entry is None
            or sha256_bytes(source_entry.text.encode("utf-8"))
            != item["source_text_sha256"]
        ):
            raise SystemExit(f"strengthening-part source drift: {entry_id}")
        if item.get("translation_action") == "preserve":
            expected_part = source_entry.text
            preserved_part_count += 1
        else:
            expected_part = normalize_original_fullwidth_ascii(
                item["translation"]
            )
            written_part_count += 1
        if actual_entry.text != expected_part:
            raise SystemExit(
                f"strengthening-part mismatch: {entry_id}: "
                f"expected={expected_part!r} actual={actual_entry.text!r}"
            )
    parts_report = {
        "corpus_entry_count": len(parts_document["entries"]),
        "written_entry_count": written_part_count,
        "preserved_empty_entry_count": preserved_part_count,
        "readback_exact": True,
    }

    unit_by_id = {
        entry.entry_id: entry for entry in reread.unit_entries
    }
    unit_ascii_expectations = {
        "display-name/unit/0089/name": {
            "text": "钢铁基亚（LS）",
            "token": "LS",
            "stored_hex": "826b8272",
        },
        "display-name/unit/0090/name": {
            "text": "钢铁基亚（WM）",
            "token": "WM",
            "stored_hex": "8276826c",
        },
    }
    unit_ascii_storage_examples = {}
    for entry_id, expectation in unit_ascii_expectations.items():
        entry = unit_by_id.get(entry_id)
        if entry is None or entry.text != expectation["text"]:
            raise SystemExit(
                f"final ISO unit ASCII example mismatch: {entry_id}"
            )
        token = expectation["token"]
        token_payload = bytes.fromhex(expectation["stored_hex"])
        field_payload = decoded_compdata.output[
            entry.target_offset:
            entry.target_offset + entry.encoded_size
        ]
        byte_start = field_payload.find(token_payload)
        raw = field_payload[byte_start : byte_start + len(token_payload)]
        if (
            byte_start < 0
            or raw != token_payload
            or token.encode("ascii") in field_payload
        ):
            raise SystemExit(
                f"final ISO unit ASCII storage mismatch: {entry_id}"
            )
        unit_ascii_storage_examples[token] = {
            "entry_id": entry_id,
            "text": entry.text,
            "stored_hex": raw.hex(),
            "raw_single_byte_ascii": False,
        }

    return {
        "decoded_size": len(decoded_compdata.output),
        "selected_entry_count": len(selected),
        "field_entry_counts": field_counts,
        "unique_source_count": len(by_source),
        "story_unique_source_count": len(story_by_source),
        "residual_unique_source_count": len(residual_by_text),
        "readback_exact": True,
        "examples": examples,
        "button_prompts": button_prompts,
        "button_prompts_exact": True,
        "unit_ascii_storage_examples": unit_ascii_storage_examples,
        "unit_ascii_storage_examples_exact": True,
        "surface_safe_alias_count": len(surface_aliases),
        "surface_safe_aliases_readback_exact": True,
        "remaining_ui": {
            "compdata_direct": direct_report,
            "leadership_effects": leadership_report,
            "slps": slps_report,
            "parts": parts_report,
            "readback_exact": True,
        },
        "new_game_regressions": {
            "male_default_name_offsets": new_game_name_expectations,
            "male_default_name_readback_exact": True,
            "scenario_button_offsets": scenario_button_expectations,
            "scenario_button_readback_exact": True,
            "male_profile_offset": "0x7FD20",
            "male_profile_text": expected_profile,
            "male_profile_line_lengths": profile_line_lengths,
            "male_profile_within_24x3": True,
            "male_profile_readback_exact": True,
            "male_profile_default_width_codes_only": True,
            "male_profile_conditional_width_code_count": 0,
        },
    }


def main() -> int:
    args = parse_args()
    iso_path = project_path(args.iso)
    report_path = project_path(args.report)
    manifest_path = project_path(args.manifest)
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")

    config = json.loads(
        project_path(args.build_config).read_text(encoding="utf-8")
    )
    component_manifest = None
    component_manifest_path = config.get("component_validation_manifest")
    if config.get("require_component_output_binding"):
        if not component_manifest_path:
            raise SystemExit("bound component manifest path is missing")
        component_manifest = json.loads(
            project_path(Path(component_manifest_path)).read_text(
                encoding="utf-8"
            )
        )
        if component_manifest.get("status") != config.get(
            "component_required_status"
        ):
            raise SystemExit("bound component manifest status mismatch")
    component = json.loads(
        project_path(args.component_report).read_text(encoding="utf-8")
    )
    font_manifest = json.loads(
        project_path(args.font_manifest).read_text(encoding="utf-8")
    )
    source_config = json.loads(
        SOURCE_CONTENT_CONFIG.read_text(encoding="utf-8")
    )
    stages = tuple(component["story"]["stage_indices"])
    if len(stages) != len(set(stages)) or tuple(sorted(stages)) != stages:
        raise SystemExit("full-story stage selection is not unique and sorted")

    expected_replacements = {
        item["member"]: item for item in config["replacements"]
    }
    if component_manifest is not None:
        manifest_outputs = component_manifest.get("outputs", {})
        if set(expected_replacements) != set(manifest_outputs):
            raise SystemExit("bound component output member set mismatch")
        for member, replacement in expected_replacements.items():
            output = manifest_outputs[member]
            if (
                replacement["source"] != output["path"]
                or replacement["size"] != output["size"]
                or replacement["sha256"] != output["sha256"]
            ):
                raise SystemExit(
                    f"bound component output mismatch: {member}"
                )
    required_members = tuple(expected_replacements)
    members = read_members(iso_path, required_members)
    for member_path, data in members.items():
        expected = expected_replacements[member_path]
        if (
            len(data) != expected["size"]
            or sha256_bytes(data) != expected["sha256"]
        ):
            raise SystemExit(
                f"final ISO replacement mismatch: {member_path}"
            )

    slps = members["SLPS_258.87"]
    hb = members["HEDBDY/HB.BIN"]
    vt1 = members["DATA/VT1.BIN"]
    stage_archive = members["DATA/STAGE.BIN"]
    stage_offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member="HEDBDY/HB.BIN",
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(
        hb,
        stage_offset_spec,
        len(stage_archive),
    )
    if len(offsets) != 206 or offsets[-1] != len(stage_archive):
        raise SystemExit("final ISO HB/STAGE layout mismatch")

    font_offsets = read_executable_archive_offsets(
        slps,
        CORE_ARCHIVE_SPECS["VT1.BIN"],
        len(vt1),
    )
    font_index = 2
    font_chunk = vt1[font_offsets[font_index]:font_offsets[font_index + 1]]
    decoded_font = decode(font_chunk)
    font_padding = font_chunk[decoded_font.consumed:]
    expected_font = expected_font_component(
        config,
        component_manifest,
        font_manifest,
    )
    if (
        decoded_font.consumed != expected_font["encoded_size"]
        or len(decoded_font.output) != expected_font["decoded_size"]
        or sha256_bytes(decoded_font.output) != expected_font["decoded_sha256"]
        or any(font_padding)
    ):
        raise SystemExit("final ISO font chunk mismatch")

    source_table = load_text_table(TEXT_TABLE)
    overrides, surface_aliases, proposal = load_overrides(
        project_path(args.codebook_proposal)
    )
    table = project_runtime_text_table(source_table, overrides)
    compdata_table = project_runtime_text_table(table, surface_aliases)
    ascii_overrides = original_fullwidth_ascii_overrides(source_table)
    visible_ascii_policy = verify_stock_ascii_glyphs(
        source_table,
        ascii_overrides,
        decoded_font.output,
    )
    compdata_table = project_runtime_text_table(
        compdata_table, ascii_overrides
    )
    targeted_ui_glyphs = verify_targeted_ui_glyphs(
        slps,
        compdata_table,
        decoded_font.output,
    )
    scenario_select_effect = verify_scenario_select_effect(
        slps,
        members["EFF/VEFF2DX.BIN"],
        component_manifest,
    )
    stage_overrides = {
        character: code
        for character, code in overrides.items()
        if not 0x20 <= ord(character) <= 0x7E
        or character in "12345"
    }
    stage_overrides.update(surface_aliases)
    stage_overrides.update(ascii_overrides)
    stage_table = project_runtime_text_table(
        source_table,
        stage_overrides,
    )
    overview_overrides = dict(overrides)
    overview_overrides.update(surface_aliases)
    overview_overrides.update(ascii_overrides)
    overview_overrides[" "] = ord(" ")
    overview_table = project_runtime_text_table(
        source_table,
        overview_overrides,
    )
    full_component_config = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )
    overview_reference = full_component_config.get("stage_overviews", {})
    overview_corpus_reference = overview_reference.get("corpus", {})
    overview_corpus_path = PROJECT_ROOT / overview_corpus_reference.get(
        "path", ""
    )
    overview_corpus_bytes = overview_corpus_path.read_bytes()
    if (
        len(overview_corpus_bytes) != overview_corpus_reference.get("size")
        or sha256_bytes(overview_corpus_bytes)
        != overview_corpus_reference.get("sha256")
    ):
        raise SystemExit("stage-overview corpus lock drift")
    overview_corpus = json.loads(overview_corpus_bytes.decode("utf-8"))
    overview_chunk = stage_archive[offsets[0] : offsets[1]]
    decoded_overview = decode(overview_chunk)
    if any(overview_chunk[decoded_overview.consumed :]):
        raise SystemExit("final ISO stage-overview chunk has nonzero padding")
    overview_entries = parse_stage_overviews(
        decoded_overview.output, overview_table
    )
    overview_by_id = {
        entry.entry_id: entry for entry in overview_entries
    }
    overview_examples = {}
    for row in overview_corpus.get("entries", []):
        entry = overview_by_id.get(row.get("id"))
        expected_text = normalize_original_fullwidth_ascii(
            row.get("translation", "")
        )
        if (
            entry is None
            or entry.ordinal != row.get("ordinal")
            or f"0x{entry.pointer_offset:X}" != row.get("pointer_offset")
            or f"0x{entry.text_offset:X}" != row.get("text_offset")
            or entry.source_text != expected_text
        ):
            raise SystemExit(
                f"final ISO stage-overview mismatch: {row.get('id')}"
            )
        overview_examples[entry.entry_id] = entry.source_text
    overview_expected = overview_reference.get("expected", {})
    if (
        len(overview_entries)
        != overview_expected.get("inventory_entry_count")
        or len(overview_examples)
        != overview_expected.get("translated_entry_count")
        or list(overview_examples)
        != overview_expected.get("translated_entry_ids")
    ):
        raise SystemExit("final ISO stage-overview selection drift")
    overview_report = {
        "inventory_entry_count": len(overview_entries),
        "translated_entry_count": len(overview_examples),
        "translated_entry_ids": list(overview_examples),
        "chunk_index": 0,
        "stored_chunk_size": len(overview_chunk),
        "encoded_size": decoded_overview.consumed,
        "padding_size": len(overview_chunk) - decoded_overview.consumed,
        "fixed_pointer_entries_exact": True,
        "translated_readback_exact": True,
    }
    hsfc_reference = full_component_config.get("hsfc_overviews", {})
    hsfc_corpus_reference = hsfc_reference.get("corpus", {})
    hsfc_corpus_path = PROJECT_ROOT / hsfc_corpus_reference.get("path", "")
    hsfc_corpus_bytes = hsfc_corpus_path.read_bytes()
    if (
        len(hsfc_corpus_bytes) != hsfc_corpus_reference.get("size")
        or sha256_bytes(hsfc_corpus_bytes)
        != hsfc_corpus_reference.get("sha256")
    ):
        raise SystemExit("HSFC overview corpus lock drift")
    hsfc_corpus = json.loads(hsfc_corpus_bytes.decode("utf-8"))
    original_hsfc_reference = hsfc_reference.get("original", {})
    original_hsfc_path = PROJECT_ROOT / original_hsfc_reference.get(
        "path", ""
    )
    original_hsfc = original_hsfc_path.read_bytes()
    if (
        len(original_hsfc) != original_hsfc_reference.get("size")
        or sha256_bytes(original_hsfc)
        != original_hsfc_reference.get("sha256")
    ):
        raise SystemExit("original HSFC baseline drift")
    hsfc_expected = hsfc_reference.get("expected", {})
    hsfc_offsets = struct.unpack_from("<5I", slps, 0x3476A0)
    expected_hsfc_offsets = tuple(hsfc_expected.get("offsets", []))
    if hsfc_offsets != expected_hsfc_offsets:
        raise SystemExit("final ISO HSFC offset table drift")
    final_hsfc = members["DATA/HSFC.BIN"]
    original_hsfc_chunk = original_hsfc[hsfc_offsets[0] : hsfc_offsets[1]]
    final_hsfc_chunk = final_hsfc[hsfc_offsets[0] : hsfc_offsets[1]]
    original_hsfc_decoded = decode(original_hsfc_chunk)
    final_hsfc_decoded = decode(final_hsfc_chunk)
    if (
        any(original_hsfc_chunk[original_hsfc_decoded.consumed :])
        or any(final_hsfc_chunk[final_hsfc_decoded.consumed :])
    ):
        raise SystemExit("HSFC chunk 0 has nonzero padding")
    original_hsfc_records = parse_hsfc_overviews(
        original_hsfc_decoded.output, source_table
    )
    original_hsfc_groups = group_hsfc_overviews(original_hsfc_records)
    final_hsfc_records = parse_hsfc_overviews(
        final_hsfc_decoded.output, overview_table
    )
    hsfc_rows = {
        row.get("id"): row for row in hsfc_corpus.get("entries", [])
    }
    hsfc_examples = {}
    translated_occurrence_count = 0
    for group in original_hsfc_groups:
        row = hsfc_rows.get(group.entry_id)
        expected_text = normalize_original_fullwidth_ascii(
            row.get("translation", "") if isinstance(row, dict) else ""
        )
        if (
            not isinstance(row, dict)
            or row.get("editorial_status") != "reviewed"
            or expected_text.count("\n") != 2
        ):
            raise SystemExit(
                f"HSFC overview corpus drift: {group.entry_id}"
            )
        for ordinal in group.ordinals:
            actual = final_hsfc_records[ordinal].source_text
            if actual != expected_text:
                raise SystemExit(
                    "final ISO HSFC overview mismatch: "
                    f"{group.entry_id} record={ordinal}: "
                    f"expected={expected_text!r} actual={actual!r}"
                )
            translated_occurrence_count += 1
        if 66 in group.ordinals:
            hsfc_examples["record_066"] = expected_text
    if (
        len(original_hsfc_records)
        != hsfc_expected.get("record_count")
        or len(original_hsfc_groups)
        != hsfc_expected.get("unique_source_text_count")
        or len(hsfc_rows) != hsfc_expected.get("translated_unique_entry_count")
        or translated_occurrence_count
        != hsfc_expected.get("translated_occurrence_count")
        or set(hsfc_rows) != {group.entry_id for group in original_hsfc_groups}
        or set(hsfc_examples) != {"record_066"}
    ):
        raise SystemExit("final ISO HSFC overview selection drift")
    hsfc_report = {
        "inventory_record_count": len(original_hsfc_records),
        "unique_source_text_count": len(original_hsfc_groups),
        "translated_unique_entry_count": len(hsfc_rows),
        "translated_occurrence_count": translated_occurrence_count,
        "archive_offsets": list(hsfc_offsets),
        "chunk_index": 0,
        "stored_chunk_size": len(final_hsfc_chunk),
        "encoded_size": final_hsfc_decoded.consumed,
        "padding_size": len(final_hsfc_chunk) - final_hsfc_decoded.consumed,
        "examples": hsfc_examples,
        "translation_method": hsfc_corpus.get("policy", {}).get(
            "translation_method"
        ),
        "external_model_used": hsfc_corpus.get("policy", {}).get(
            "external_model_used"
        ),
        "fixed_record_cells_exact": True,
        "translated_readback_exact": True,
    }
    functions = read_stage_function_addresses(slps)
    source_stage_spec = source_config["source"]["stage"]
    source_stage_archive = (
        PROJECT_ROOT / source_stage_spec["path"]
    ).read_bytes()
    if (
        len(source_stage_archive) != source_stage_spec["size"]
        or sha256_bytes(source_stage_archive) != source_stage_spec["sha256"]
        or len(source_stage_archive) != len(stage_archive)
    ):
        raise SystemExit("source STAGE baseline mismatch")
    source_slps_spec = source_config["source"]["slps"]
    source_slps = (PROJECT_ROOT / source_slps_spec["path"]).read_bytes()
    if (
        len(source_slps) != source_slps_spec["size"]
        or sha256_bytes(source_slps) != source_slps_spec["sha256"]
    ):
        raise SystemExit("source SLPS baseline mismatch")
    source_functions = read_stage_function_addresses(source_slps)
    conditions = load_translations(
        PROJECT_ROOT / "corpus/zh/story-conditions.json"
    )
    speakers = load_translations(
        PROJECT_ROOT / "corpus/zh/story-speakers.json"
    )
    stage_component_spec = component.get("inputs", {}).get(
        "full_story_stage_report"
    )
    if not isinstance(stage_component_spec, dict):
        raise SystemExit("component STAGE detail report binding is missing")
    stage_component_path = project_path(Path(stage_component_spec["path"]))
    stage_component_payload = stage_component_path.read_bytes()
    if (
        len(stage_component_payload) != stage_component_spec["size"]
        or sha256_bytes(stage_component_payload)
        != stage_component_spec["sha256"]
    ):
        raise SystemExit("component STAGE detail report binding mismatch")
    stage_component = json.loads(stage_component_payload)
    component_stages = {
        item["stage_index"]: item for item in stage_component["stages"]
    }
    if set(component_stages) != set(stages):
        raise SystemExit("component stage details do not match stage selection")

    stage_reports = []
    total_entries = 0
    total_dialogue = 0
    total_conditions = 0
    total_speakers = 0
    maximum_dialogue_line_width = 0
    maximum_dialogue_line_count = 0
    runtime_token_entry_count = 0
    runtime_token_occurrence_count = 0
    story_ascii_storage_examples = {}
    for stage in stages:
        dialogue = load_translations(
            PROJECT_ROOT
            / f"corpus/zh/story-dialogue/stage-{stage:03d}.json"
        )
        stage_conditions = {
            entry_id: translation
            for entry_id, translation in conditions.items()
            if stage_index(entry_id) == stage
        }
        stage_speakers = {
            int(entry_id.split("/")[-1]): translation
            for entry_id, translation in speakers.items()
            if stage_index(entry_id) == stage
        }
        expected_texts = {
            **dialogue,
            **stage_conditions,
        }
        if len(expected_texts) != len(dialogue) + len(stage_conditions):
            raise SystemExit(f"stage {stage:03d} has duplicate entry IDs")

        chunk = stage_archive[offsets[stage]:offsets[stage + 1]]
        decoded = decode(chunk)
        expected_stage = component_stages[stage]
        encoded = chunk[:decoded.consumed]
        padding = chunk[decoded.consumed:]
        if any(padding):
            raise SystemExit(f"stage {stage:03d} has non-zero archive padding")
        if (
            decoded.consumed != expected_stage["output_encoded_size"]
            or sha256_bytes(encoded)
            != expected_stage["output_encoded_sha256"]
            or len(decoded.output) != expected_stage["output_size"]
        ):
            raise SystemExit(f"stage {stage:03d} codec metadata mismatch")

        parsed = parse_stage(
            decoded.output,
            stage_table,
            stage_index=stage,
            function_address=functions[stage],
        )
        actual_texts = {
            entry.entry_id: entry.text
            for entry in parsed.entries
            if entry.kind in {"dialogue", "condition"}
        }
        if actual_texts != expected_texts:
            missing = sorted(set(expected_texts) - set(actual_texts))
            extra = sorted(set(actual_texts) - set(expected_texts))
            wrong = sorted(
                entry_id
                for entry_id in set(expected_texts) & set(actual_texts)
                if expected_texts[entry_id] != actual_texts[entry_id]
            )
            wrong_examples = {
                entry_id: {
                    "expected": expected_texts[entry_id],
                    "actual": actual_texts[entry_id],
                }
                for entry_id in wrong[:3]
            }
            raise SystemExit(
                f"stage {stage:03d} translated text mismatch: "
                f"missing={missing[:3]!r}, extra={extra[:3]!r}, "
                f"wrong={wrong_examples!r}"
            )
        if parsed.unknown_code_count:
            raise SystemExit(
                f"stage {stage:03d} has "
                f"{parsed.unknown_code_count} unknown codes"
            )

        source_chunk = source_stage_archive[
            offsets[stage]:offsets[stage + 1]
        ]
        source_decoded = decode(source_chunk)
        source_parsed = parse_stage(
            source_decoded.output,
            source_table,
            stage_index=stage,
            function_address=source_functions[stage],
        )
        source_speaker_ids = {
            entry.speaker_id
            for entry in source_parsed.entries
            if entry.kind == "speaker"
        }
        if source_speaker_ids != set(stage_speakers):
            raise SystemExit(
                f"stage {stage:03d} speaker selection mismatch: "
                f"source={sorted(source_speaker_ids)!r}, "
                f"selected={sorted(stage_speakers)!r}"
            )
        output_entries = {
            entry.entry_id: entry for entry in parsed.entries
            if entry.kind == "dialogue"
        }
        source_entries = {
            entry.entry_id: entry for entry in source_parsed.entries
            if entry.kind == "dialogue"
        }
        if set(output_entries) != set(source_entries):
            raise SystemExit(
                f"stage {stage:03d} dialogue structure changed"
            )
        speaker_occurrence_count = 0
        stage_maximum_line_width = 0
        stage_maximum_line_count = 0
        stage_runtime_token_entry_count = 0
        stage_runtime_token_occurrence_count = 0
        for entry_id, source_entry in source_entries.items():
            output_entry = output_entries[entry_id]
            assert source_entry.text_offset is not None
            assert output_entry.text_offset is not None
            source_prefix = decode_text(
                source_decoded.output,
                source_entry.text_offset,
                source_table,
                stop_at_newline=True,
            )
            output_prefix = decode_text(
                decoded.output,
                output_entry.text_offset,
                stage_table,
                stop_at_newline=True,
            )
            expected_speaker = stage_speakers[source_entry.speaker_id]
            if source_prefix.terminator == "newline":
                if (
                    output_prefix.terminator != "newline"
                    or output_prefix.text != expected_speaker
                ):
                    raise SystemExit(
                        f"{entry_id} speaker mismatch: expected "
                        f"{expected_speaker!r}, got {output_prefix.text!r}"
                    )
            elif output_prefix.terminator == "newline":
                raise SystemExit(
                    f"{entry_id} unexpectedly gained a speaker prefix"
                )

            translation_start = (
                output_prefix.end
                if source_prefix.terminator == "newline"
                else output_entry.text_offset
            )
            expected_translation = dialogue[entry_id]
            expected_payload = encode_text(
                expected_translation,
                source_table,
                overrides=stage_overrides,
                terminate=True,
            )
            actual_payload = decoded.output[
                translation_start : translation_start + len(expected_payload)
            ]
            if actual_payload != expected_payload:
                raise SystemExit(
                    f"{entry_id} encoded dialogue payload mismatch"
                )

            for token, stored_hex in {
                "ZAFT": "8279826082658273",
                "PLANT": "826f826b8260826d8273",
            }.items():
                if token in story_ascii_storage_examples:
                    continue
                token_start = expected_translation.find(token)
                if token_start < 0:
                    continue
                byte_start = len(
                    encode_text(
                        expected_translation[:token_start],
                        source_table,
                        overrides=stage_overrides,
                    )
                )
                token_payload = encode_text(
                    token,
                    source_table,
                    overrides=stage_overrides,
                )
                raw = actual_payload[
                    byte_start : byte_start + len(token_payload)
                ]
                if (
                    raw != token_payload
                    or raw.hex() != stored_hex
                    or raw == token.encode("ascii")
                ):
                    raise SystemExit(
                        f"{entry_id} stock ASCII storage mismatch: {token}"
                    )
                story_ascii_storage_examples[token] = {
                    "entry_id": entry_id,
                    "stored_hex": raw.hex(),
                    "raw_single_byte_ascii": False,
                }

            widths = dialogue_line_widths(expected_translation)
            if len(widths) > 3 or max(widths, default=0) > 24:
                raise SystemExit(
                    f"{entry_id} exceeds 24x3 dialogue layout: {widths!r}"
                )
            stage_maximum_line_count = max(
                stage_maximum_line_count,
                len(widths),
            )
            stage_maximum_line_width = max(
                stage_maximum_line_width,
                max(widths, default=0),
            )

            token_matches = tuple(
                RUNTIME_SUBSTITUTION_TOKEN.finditer(expected_translation)
            )
            if token_matches:
                stage_runtime_token_entry_count += 1
            for match in token_matches:
                prefix_size = len(
                    encode_text(
                        expected_translation[: match.start()],
                        source_table,
                        overrides=stage_overrides,
                    )
                )
                token = match.group(0).encode("ascii")
                if actual_payload[prefix_size : prefix_size + len(token)] != token:
                    raise SystemExit(
                        f"{entry_id} runtime token is not raw ASCII: "
                        f"{match.group(0)!r}"
                    )
                stage_runtime_token_occurrence_count += 1
            speaker_occurrence_count += 1

        total_entries += len(expected_texts) + len(stage_speakers)
        total_dialogue += len(dialogue)
        total_conditions += len(stage_conditions)
        total_speakers += len(stage_speakers)
        maximum_dialogue_line_width = max(
            maximum_dialogue_line_width,
            stage_maximum_line_width,
        )
        maximum_dialogue_line_count = max(
            maximum_dialogue_line_count,
            stage_maximum_line_count,
        )
        runtime_token_entry_count += stage_runtime_token_entry_count
        runtime_token_occurrence_count += stage_runtime_token_occurrence_count
        stage_reports.append(
            {
                "stage_index": stage,
                "archive_offset": offsets[stage],
                "archive_next_offset": offsets[stage + 1],
                "encoded_size": decoded.consumed,
                "encoded_sha256": sha256_bytes(encoded),
                "padding_size": len(padding),
                "padding_all_zero": True,
                "decoded_size": len(decoded.output),
                "decoded_sha256": sha256_bytes(decoded.output),
                "dialogue_count": len(dialogue),
                "condition_count": len(stage_conditions),
                "speaker_count": len(stage_speakers),
                "speaker_occurrence_count": speaker_occurrence_count,
                "translation_entry_count": (
                    len(expected_texts) + len(stage_speakers)
                ),
                "entry_id_set_exact": True,
                "translated_text_exact": True,
                "speaker_translation_by_source_id_exact": True,
                "unknown_code_count": 0,
                "maximum_dialogue_line_width": stage_maximum_line_width,
                "maximum_dialogue_line_count": stage_maximum_line_count,
                "runtime_substitution_token_entry_count": (
                    stage_runtime_token_entry_count
                ),
                "runtime_substitution_token_occurrence_count": (
                    stage_runtime_token_occurrence_count
                ),
                "runtime_substitution_tokens_raw_ascii": True,
            }
        )

    expected_entry_count = expected_story_entry_count(
        config,
        component_manifest,
        font_manifest,
    )
    if total_entries != expected_entry_count:
        raise SystemExit(
            f"full-story entry count {total_entries}, expected "
            f"{expected_entry_count}"
        )
    if set(story_ascii_storage_examples) != {"ZAFT", "PLANT"}:
        raise SystemExit(
            "final ISO story ASCII examples are incomplete: "
            f"{sorted(story_ascii_storage_examples)!r}"
        )

    compdata_report = verify_final_compdata(
        members["DATA/COMPDATA.BN"],
        members["SLPS_258.87"],
        source_table,
        compdata_table,
        surface_aliases,
    )

    output = config["output"]
    coverage = renderer_coverage(font_manifest)
    cjk_optical_policy = font_manifest.get(
        "cjk_optical_policy",
        proposal.get("rasterizer"),
    )
    if not isinstance(cjk_optical_policy, dict):
        raise SystemExit("font rasterization policy is missing")
    iso_size = iso_path.stat().st_size
    iso_sha256 = sha256_file(iso_path)
    report = {
        "schema_version": 1,
        "status": "full_story_final_iso_static_content_readback_passed",
        "scope": (
            "Independent final-ISO readback of all 154 selected story "
            "chunks and 91,746 dialogue, condition, and speaker entries, "
            "plus reviewed save/load overviews, pilot-name, button-prompt, "
            "24x3 layout, runtime-token, "
            "and font checks; this is not a full gameplay playthrough."
        ),
        "iso": {
            "path": str(iso_path.relative_to(PROJECT_ROOT)),
            "size": iso_size,
            "sha256": iso_sha256,
        },
        "stage_indices": list(stages),
        "stage_count": len(stages),
        "translation_entry_count": total_entries,
        "dialogue_count": total_dialogue,
        "condition_count": total_conditions,
        "speaker_count": total_speakers,
        "dialogue_layout": {
            "line_width_limit": 24,
            "line_count_limit": 3,
            "maximum_line_width": maximum_dialogue_line_width,
            "maximum_line_count": maximum_dialogue_line_count,
            "all_dialogue_within_limit": True,
        },
        "runtime_substitution_tokens": {
            "entry_count": runtime_token_entry_count,
            "occurrence_count": runtime_token_occurrence_count,
            "raw_ascii_exact": True,
        },
        "visible_ascii_policy": {
            **visible_ascii_policy,
            "story_storage_examples": story_ascii_storage_examples,
            "story_storage_examples_exact": True,
        },
        "compdata": compdata_report,
        "scenario_select_effect": scenario_select_effect,
        "stage_overviews": overview_report,
        "hsfc_overviews": hsfc_report,
        "members": {
            path: {
                "size": len(data),
                "sha256": sha256_bytes(data),
                "replacement_exact": True,
            }
            for path, data in members.items()
        },
        "font": {
            "chunk_index": font_index,
            "archive_offset": font_offsets[font_index],
            "archive_next_offset": font_offsets[font_index + 1],
            "encoded_size": decoded_font.consumed,
            "decoded_size": len(decoded_font.output),
            "decoded_sha256": sha256_bytes(decoded_font.output),
            "padding_size": len(font_padding),
            "padding_all_zero": True,
            "renderer_missing_character_count": 0,
            "renderer_original_font_han_count": 0,
            "renderer_original_font_visible_character_count": 0,
            "cjk_optical_policy": cjk_optical_policy,
            "targeted_new_game_glyphs": targeted_ui_glyphs,
        },
        "hb_offset_count": len(offsets),
        "hb_offset_reread_exact": True,
        "stages": stage_reports,
        "checks": {
            "iso_size_exact": iso_size == output["expected_size"],
            "iso_sha256_exact": iso_sha256 == output["expected_sha256"],
            "replacement_members_exact": True,
            "font_chunk_exact": True,
            "font_renderer_coverage_complete": (
                coverage["missing_character_count"] == 0
                and coverage["original_font_han_count"] == 0
                and coverage["original_font_visible_character_count"] == 0
            ),
            "targeted_new_game_glyphs_nonblank": targeted_ui_glyphs[
                "all_target_glyphs_present_and_nonblank"
            ],
            "scenario_select_title_texture_exact": (
                scenario_select_effect["source_title_texture_replaced"]
                and scenario_select_effect["all_label_segments_nonblank"]
                and scenario_select_effect[
                    "all_label_segments_native_4bpp_antialiased"
                ]
                and scenario_select_effect["archive_offsets_preserved"]
            ),
            "hb_stage_offsets_valid": True,
            "encoded_streams_exact": True,
            "decoded_sizes_exact": True,
            "archive_padding_zero": True,
            "entry_id_sets_exact": True,
            "dialogue_conditions_speakers_exact": True,
            "unknown_code_count_zero": True,
            "translation_entry_count_exact": total_entries
            == expected_entry_count,
            "dialogue_layout_24x3_exact": (
                maximum_dialogue_line_width <= 24
                and maximum_dialogue_line_count <= 3
            ),
            "runtime_substitution_tokens_raw_ascii": True,
            "stock_alphanumeric_glyphs_byte_exact": (
                visible_ascii_policy[
                    "stock_alphanumeric_glyphs_byte_exact"
                ]
            ),
            "raw_and_fullwidth_ascii_share_glyph_slots": (
                visible_ascii_policy[
                    "raw_and_fullwidth_codes_share_glyph_slots"
                ]
            ),
            "story_ascii_storage_examples_exact": True,
            "pilot_names_exact": compdata_report["readback_exact"],
            "unit_ascii_storage_examples_exact": compdata_report[
                "unit_ascii_storage_examples_exact"
            ],
            "surface_safe_aliases_exact": compdata_report[
                "surface_safe_aliases_readback_exact"
            ],
            "button_prompts_exact": compdata_report["button_prompts_exact"],
            "remaining_ui_binary_text_exact": compdata_report[
                "remaining_ui"
            ]["readback_exact"],
            "stage_overviews_exact": overview_report[
                "translated_readback_exact"
            ]
            and overview_report["fixed_pointer_entries_exact"],
            "hsfc_overviews_exact": hsfc_report[
                "translated_readback_exact"
            ]
            and hsfc_report["fixed_record_cells_exact"],
        },
        "runtime_acceptance": (
            "static final-ISO content readback; fresh PCSX2 runtime evidence "
            "is separate"
        ),
    }
    iso_report_path = PROJECT_ROOT / output["report"]
    if iso_report_path.is_file():
        iso_report = json.loads(iso_report_path.read_text(encoding="utf-8"))
        if (
            report["iso"]["size"] != iso_report["output_iso"]["size"]
            or report["iso"]["sha256"]
            != iso_report["output_iso"]["sha256"]
        ):
            raise SystemExit("final ISO image hash mismatch")
    if not all(report["checks"].values()):
        failed = [
            name for name, passed in report["checks"].items() if not passed
        ]
        raise SystemExit(f"final ISO content checks failed: {failed!r}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file():
            raise SystemExit(
                f"manifest not found; review and use --refresh-manifest: "
                f"{manifest_path}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest != report:
            raise SystemExit("full-story ISO content manifest drift")
        manifest_status = "verified"

    print(
        "full-story final ISO readback:",
        f"stages={len(stages)}",
        f"translations={total_entries}",
        f"dialogue={total_dialogue}",
        f"conditions={total_conditions}",
        f"speakers={total_speakers}",
        f"runtime_tokens={runtime_token_occurrence_count}",
        f"pilot_names={compdata_report['selected_entry_count']}",
        "status=passed",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
