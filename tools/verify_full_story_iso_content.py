#!/usr/bin/env python3
"""Independently reread every selected Chinese story entry from the final ISO."""

from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path

from srwz.archive import sha256_file
from srwz.chinese_layout import (
    DEFAULT_LINE_WIDTH,
    DEFAULT_MAX_LINES,
    dialogue_line_widths,
    fit_chinese_dialogue_layout,
)
from srwz.codec import decode_production as decode
from srwz.display_names import (
    load_display_name_source,
    load_full_unit_name_corpus,
    parse_display_names,
)
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
from srwz.release_font_policy import DEFAULT_WIDTH_CLASS, allocation_width_class
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.hsfc_overview import (
    HSFC_OVERVIEW_CELL_SIZE,
    group_hsfc_overviews,
    parse_hsfc_overviews,
)
from srwz.image_export import parse_seg_offsets
from srwz.library import (
    SoundTitleSpanLock,
    verify_sound_title_source,
    verify_sound_titles_preserved,
)
from srwz.menu import parse_menu_file
from srwz.nisv_strategy_qa import (
    QA_METADATA_STRING_COUNT,
    QA_PAGE_COUNT,
    QA_TEXT_RECORD_COUNT,
    layout_nisv_strategy_qa_page,
    parse_nisv_strategy_qa,
)
from srwz.nisv_tutorial import parse_nisv_tutorial_pages
from srwz.psmt4 import unswizzle_psmt4
from srwz.runtime_keywords import (
    RuntimeKeywordError,
    apply_compdata_keyword_names,
    apply_stage_keyword_popups,
    load_keyword_authority,
)
from srwz.sound_select import (
    apply_sound_select_default_unlock,
    audit_sound_select_track_metadata,
)
from srwz.library_unlock import apply_library_default_unlock
from srwz.full_name_order import apply_route_specific_full_name_order
from srwz.game_mode_unlock import apply_postgame_mode_unlock
from srwz.movement_type_labels import apply_runtime_movement_type_labels
from srwz.weapon_category_labels import apply_runtime_weapon_category_labels
from srwz.search_tab_alignment import apply_search_tab_alignment
from srwz.intermission_library_alignment import (
    apply_intermission_library_alignment,
)
from srwz.remaining_squad_count_alignment import (
    apply_remaining_squad_count_alignment,
)
from srwz.weapon_special_effects import (
    WeaponSpecialEffectError,
    apply_weapon_special_effect_2,
)
from srwz.srvc import parse_srvc_archive
from srwz.stage import (
    parse_stage,
    parse_stage_system_dialogues,
    read_stage_function_addresses,
)
from srwz.story_quotes import evaluate_story_quote
from srwz.stage_overview import parse_stage_overviews
from srwz.stage_formations import (
    STAGE_OFFSET_SPEC,
    compact_formation_ascii_replacement,
    formation_inventory_sha256,
    has_stage_formation_pointer_owner,
    load_locked_stage_default_formations,
)
from srwz.summary import parse_summary
from srwz.tim2 import scan_tim2
from srwz.tim2_writeback import unswizzle_psmt8
from srwz.veff_tutorial_titles import audit_tutorial_effect_binding
from srwz.text import (
    ORIGINAL_FULLWIDTH_ASCII,
    RUNTIME_SUBSTITUTION_TOKEN,
    TextTable,
    control_notation_tokens,
    decode_text,
    encode_text,
    load_text_table,
    normalize_original_fullwidth_ascii,
    normalize_two_byte_visible_spaces,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)
from srwz.writers import encode_stage_message


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = (
    PROJECT_ROOT
    / "build/iso/zh-release-full-story/srwz-zh-current.iso"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "work/verification/zh-release-full-story-content.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "manifests/zh-release-full-story-iso-content-validation.json"
)


def stored_csm1_palette_index(index: int) -> int:
    """Map one logical PSMT8 index to its stored CSM1 CLUT entry."""

    return (
        (index & 0xE7)
        | ((index & 0x08) << 1)
        | ((index & 0x10) >> 1)
    )


def indexed_alpha_plane(indexes: bytes, palette: bytes) -> bytes:
    """Return the stored PS2 CLUT alpha value for each indexed pixel."""

    return bytes(
        palette[stored_csm1_palette_index(index) * 4 + 3]
        for index in indexes
    )
BUILD_CONFIG = PROJECT_ROOT / "config/iso/zh-release-current-build.json"
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
    special_characters = {
        assignment["character"]
        for assignment in proposal["assignments"]
        if allocation_width_class(int(assignment["code"], 16))
        != DEFAULT_WIDTH_CLASS
    }
    alias_report = proposal.get("surface_safe_aliases", {})
    unaliased_characters = conditional_characters - set(aliases)
    unaliased_special_characters = special_characters - set(aliases)
    if (
        not set(aliases) <= special_characters
        or alias_report.get("assignment_count") != len(aliases)
        or alias_report.get("conditional_primary_assignment_count")
        != len(conditional_characters)
        or alias_report.get("unaliased_conditional_assignment_count")
        != len(unaliased_characters)
        or alias_report.get("all_selected_assignments")
        is not (not unaliased_characters)
        or alias_report.get("special_primary_assignment_count")
        != len(special_characters)
        or alias_report.get("unaliased_special_assignment_count")
        != len(unaliased_special_characters)
        or any(
            allocation_width_class(code) != DEFAULT_WIDTH_CLASS
            for code in aliases.values()
        )
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


def raw_visible_ascii_glyphs(payload: bytes) -> tuple[tuple[int, str], ...]:
    """Locate unsafe raw visible ASCII while preserving runtime tokens."""

    found = []
    cursor = 0
    while cursor < len(payload):
        value = payload[cursor]
        if value == 0:
            break
        if value == 0x0A:
            cursor += 1
            continue
        if (
            value == ord("$")
            and cursor + 1 < len(payload)
            and payload[cursor + 1] in b"cflnF"
        ):
            cursor += 2
            continue
        if payload.startswith((b"\\n", b"%s"), cursor):
            cursor += 2
            continue
        if value >= 0x80:
            cursor += 2
            continue
        if 0x21 <= value <= 0x7E:
            found.append((cursor, chr(value)))
        cursor += 1
    return tuple(found)


def verify_world_history(
    slps: bytes,
    archive: bytes,
    table: TextTable,
    reference: dict,
) -> dict:
    """Reread every localized MTV_PROS entry from the final ISO."""

    corpus_reference = reference.get("corpus", {})
    corpus_path = project_path(Path(corpus_reference.get("path", "")))
    corpus_bytes = corpus_path.read_bytes()
    if (
        len(corpus_bytes) != corpus_reference.get("size")
        or sha256_bytes(corpus_bytes) != corpus_reference.get("sha256")
    ):
        raise SystemExit("world-history corpus lock drift")
    corpus = json.loads(corpus_bytes.decode("utf-8"))
    expected_by_id = {
        row["id"]: normalize_original_fullwidth_ascii(row["translation"])
        for row in corpus.get("entries", [])
    }
    expected = reference.get("expected", {})
    if len(expected_by_id) != expected.get("entry_count"):
        raise SystemExit("world-history corpus inventory drift")

    offsets = read_executable_archive_offsets(
        slps,
        CORE_ARCHIVE_SPECS["MTV_PROS.BIN"],
        len(archive),
    )
    if (
        len(archive) != expected.get("archive_size")
        or len(offsets) != expected.get("offset_count")
        or len(offsets) - 1 != expected.get("chunk_count")
        or offsets[-1] != len(archive)
    ):
        raise SystemExit("world-history archive layout drift")

    seen_ids = []
    raw_space_entry_count = 0
    raw_visible_ascii_glyph_count = 0
    raw_visible_ascii_entry_count = 0
    side_3_readback = None
    for chunk_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        stored = archive[start:end]
        decoded = decode(stored)
        if any(stored[decoded.consumed :]):
            raise SystemExit(
                f"final ISO world-history chunk {chunk_index} has nonzero padding"
            )
        parsed = parse_summary(
            decoded.output,
            table,
            chunk_index=chunk_index,
        )
        for entry in parsed.entries:
            expected_text = expected_by_id.get(entry.entry_id)
            if expected_text is None:
                raise SystemExit(
                    f"unexpected final ISO world-history entry: {entry.entry_id}"
                )
            stored_expected_text = expected_text.replace(" ", "\u3000")
            if entry.text != stored_expected_text:
                raise SystemExit(
                    f"final ISO world-history mismatch: {entry.entry_id}"
                )
            expected_ascii_alnum = "".join(
                character
                for character in expected_text
                if character.isascii() and character.isalnum()
            )
            stored_ascii_alnum = "".join(
                character
                for character in entry.text
                if character.isascii() and character.isalnum()
            )
            if stored_ascii_alnum != expected_ascii_alnum:
                raise SystemExit(
                    "final ISO world-history Latin/digit identity drift: "
                    f"{entry.entry_id}"
                )
            payload = decoded.output[
                entry.text_offset : entry.text_offset + entry.allocated_length
            ]
            raw_space_entry_count += b"\x20" in payload
            raw_ascii = raw_visible_ascii_glyphs(payload)
            raw_visible_ascii_glyph_count += len(raw_ascii)
            raw_visible_ascii_entry_count += bool(raw_ascii)
            if "Side\u30003" in entry.text:
                side_3_readback = "Side\u30003"
            seen_ids.append(entry.entry_id)

    if set(seen_ids) != set(expected_by_id) or len(seen_ids) != len(expected_by_id):
        raise SystemExit("final ISO world-history selection drift")
    if raw_space_entry_count or raw_visible_ascii_glyph_count:
        raise SystemExit(
            "final ISO world-history contains unsafe raw visible ASCII or spaces"
        )
    if side_3_readback is None:
        raise SystemExit("final ISO world-history Side 3 readback missing")
    return {
        "entry_count": len(seen_ids),
        "chunk_count": len(offsets) - 1,
        "translated_readback_exact": True,
        "logical_ascii_and_digits_preserved": True,
        "raw_space_entry_count": raw_space_entry_count,
        "raw_visible_ascii_glyph_count": raw_visible_ascii_glyph_count,
        "raw_visible_ascii_entry_count": raw_visible_ascii_entry_count,
        "two_byte_visible_spaces_exact": True,
        "archive_offsets_exact": True,
        "side_3_logical_text": "Side 3",
        "side_3_storage_readback": side_3_readback,
    }


def verify_auto_demo_overlays(
    slps: bytes,
    members: dict[str, bytes],
    table: TextTable,
    component_manifest: dict | None,
) -> dict:
    """Reread every title-idle work title and speaker name from the ISO."""

    if component_manifest is None:
        raise SystemExit("auto-demo readback requires a bound component manifest")
    metadata = component_manifest.get("auto_demo_overlays")
    if not isinstance(metadata, dict):
        raise SystemExit("component auto-demo metadata is missing")
    title_entries = metadata.get("titles")
    archive_entries = metadata.get("archives")
    if (
        not isinstance(title_entries, list)
        or len(title_entries) != 22
        or not isinstance(archive_entries, list)
        or len(archive_entries) != 3
    ):
        raise SystemExit("component auto-demo inventory drift")

    title_reports = []
    for entry in title_entries:
        offset = entry["offset"]
        capacity = entry["capacity"]
        end = offset + capacity
        decoded = decode_text(slps, offset, table, end=end)
        if (
            decoded.text != entry["stored_translation"]
            or decoded.unknown_code_count
            or any(slps[decoded.end:end])
        ):
            raise SystemExit(
                f"final ISO auto-demo work-title mismatch: {entry['id']}"
            )
        title_reports.append(
            {
                "id": entry["id"],
                "offset": offset,
                "capacity": capacity,
                "translation": entry["translation"],
                "stored_translation": decoded.text,
                "padding_all_zero": True,
                "unknown_code_count": 0,
            }
        )

    name_reports = []
    archive_reports = []
    for archive in archive_entries:
        member = archive["member"]
        payload = members.get(member)
        if payload is None:
            raise SystemExit(f"final ISO auto-demo member is missing: {member}")
        names = archive.get("names")
        if not isinstance(names, list):
            raise SystemExit(f"component auto-demo name list is missing: {member}")
        for entry in names:
            offset = entry["offset"]
            capacity = entry["capacity"]
            end = offset + capacity
            decoded = decode_text(payload, offset, table, end=end)
            if (
                decoded.text != entry["translation"]
                or decoded.unknown_code_count
                or any(payload[decoded.end:end])
            ):
                raise SystemExit(
                    "final ISO auto-demo speaker-name mismatch: "
                    f"{member}@0x{offset:X}"
                )
            name_reports.append(
                {
                    "member": member,
                    "offset": offset,
                    "capacity": capacity,
                    "source_text": entry["source_text"],
                    "translation": decoded.text,
                    "padding_all_zero": True,
                    "unknown_code_count": 0,
                }
            )
        archive_reports.append(
            {
                "member": member,
                "name_slot_count": len(names),
                "archive_size_preserved": archive["archive_size_preserved"],
                "translated_reread_exact": True,
            }
        )
    if (
        len(name_reports) != 63
        or len({item["source_text"] for item in name_reports}) != 59
    ):
        raise SystemExit("final ISO auto-demo name inventory mismatch")
    kamille = [
        item
        for item in name_reports
        if item["member"] == "BTL/OP0.BIN"
        and item["offset"] == 0x40B0C
    ]
    if len(kamille) != 1 or kamille[0]["translation"] != "卡缪":
        raise SystemExit("final ISO auto-demo Kamille name mismatch")
    return {
        "title_entry_count": len(title_reports),
        "name_slot_count": len(name_reports),
        "unique_name_source_count": len(
            {item["source_text"] for item in name_reports}
        ),
        "titles": title_reports,
        "archives": archive_reports,
        "kamille_name": kamille[0],
        "fixed_field_padding_all_zero": True,
        "unknown_code_count": 0,
        "translated_reread_exact": True,
    }


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
        "stage_title_storage": "original_fullwidth_two_byte",
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
        "female_default_name": "小原节子",
        "male_profile": (
            "与同伴在荒野当修理店老板的男人"
            "自称烈焰豪爽而有血性但有时会冲得太猛"
        ),
        "male_default_unit_name": "钢狮子",
        "female_default_unit_name": "巴尔戈拉",
        "formation_action_labels": "攻击反击参与攻击",
        "formation_names": "TRI中央广域",
        "spirit_acronyms": "热魂闪不铁集必加迅觉手狙直幸努乱分",
        "reported_land_dialogue": "哦把自己机器弄坏的那家伙罚你帮忙修理",
        "reported_kejinan_retreat": "今今天只是身体不舒服你们给我记住",
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


def verify_stage_system_dialogues(
    stage_archive: bytes,
    offsets: tuple,
    source_table: TextTable,
    output_table: TextTable,
    component_config: dict,
) -> dict:
    """Reject original chunk-zero dialogue rendered through the release font."""

    remaining = component_config["remaining_ui"]
    original_stage = (
        PROJECT_ROOT / remaining["original_stage"]["path"]
    ).read_bytes()
    corpus = json.loads(
        (
            PROJECT_ROOT / remaining["stage_system_dialogue"]["path"]
        ).read_text(encoding="utf-8")
    )
    entries = corpus.get("entries")
    expected = remaining.get("expected")
    if (
        corpus.get("editorial_status") != "reviewed"
        or not isinstance(entries, list)
        or not isinstance(expected, dict)
        or len(entries)
        != expected.get("stage_system_dialogue_entry_count")
    ):
        raise SystemExit("stage system-dialogue corpus contract drift")
    start, end = offsets[0:2]
    original_decoded = decode(original_stage[start:end])
    final_decoded = decode(stage_archive[start:end])
    if (
        any(original_stage[start + original_decoded.consumed : end])
        or any(stage_archive[start + final_decoded.consumed : end])
        or len(original_decoded.output) != len(final_decoded.output)
    ):
        raise SystemExit("stage system-dialogue archive decode drift")
    source_by_id = {
        entry.entry_id: entry
        for entry in parse_stage_system_dialogues(
            original_decoded.output,
            source_table,
        )
    }
    stale_by_id = {
        entry.entry_id: entry
        for entry in parse_stage_system_dialogues(
            original_decoded.output,
            output_table,
        )
    }
    final_by_id = {
        entry.entry_id: entry
        for entry in parse_stage_system_dialogues(
            final_decoded.output,
            output_table,
        )
    }
    corpus_ids = {item.get("id") for item in entries}
    if (
        len(source_by_id)
        != expected.get("stage_system_dialogue_inventory_count")
        or set(source_by_id) != corpus_ids
        or set(stale_by_id) != corpus_ids
        or set(final_by_id) != corpus_ids
    ):
        raise SystemExit("stage system-dialogue inventory drift")
    stale_fingerprint_field_count = 0
    stale_fingerprint_match_count = 0
    for item in entries:
        entry_id = item["id"]
        source = source_by_id[entry_id]
        stale = stale_by_id[entry_id]
        actual = final_by_id[entry_id]
        expected_speaker = normalize_original_fullwidth_ascii(item["speaker"])
        expected_text = normalize_original_fullwidth_ascii(item["translation"])
        if (
            sha256_bytes(source.text.encode("utf-8"))
            != item.get("source_text_sha256")
            or actual.pointer_offset != source.pointer_offset
            or actual.text_offset != source.text_offset
            or actual.speaker != expected_speaker
            or actual.text != expected_text
        ):
            raise SystemExit(
                f"stage system-dialogue final readback mismatch: {entry_id}"
            )
        for stale_value, actual_value, expected_value in (
            (stale.speaker, actual.speaker, expected_speaker),
            (stale.text, actual.text, expected_text),
        ):
            if stale_value == expected_value:
                continue
            stale_fingerprint_field_count += 1
            stale_fingerprint_match_count += actual_value == stale_value
    if stale_fingerprint_match_count:
        raise SystemExit(
            "final ISO contains stale STAGE system-dialogue renderings: "
            f"{stale_fingerprint_match_count}"
        )
    return {
        "stage_index": 0,
        "record_count": len(entries),
        "checked_text_field_count": len(entries) * 2,
        "distinct_stale_fingerprint_field_count": (
            stale_fingerprint_field_count
        ),
        "stale_fingerprint_match_count": stale_fingerprint_match_count,
        "pointer_offsets_preserved": True,
        "text_offsets_preserved": True,
        "source_preimages_sha256_exact": True,
        "translated_readback_exact": True,
    }


def verify_stage_scenario_chart_prompts(
    stage_archive: bytes,
    offsets: tuple,
    source_table: TextTable,
    output_table: TextTable,
    component_config: dict,
) -> dict:
    """Read back the fixed Scenario Chart prompt from STAGE chunk zero."""

    remaining = component_config["remaining_ui"]
    original_stage = (
        PROJECT_ROOT / remaining["original_stage"]["path"]
    ).read_bytes()
    translations = json.loads(
        (
            PROJECT_ROOT / remaining["translations"]["path"]
        ).read_text(encoding="utf-8")
    )
    replacements = translations.get("stage_scenario_chart_prompts_by_offset")
    expected = remaining.get("expected")
    if (
        not isinstance(replacements, dict)
        or not isinstance(expected, dict)
        or len(replacements)
        != expected.get("stage_scenario_chart_prompt_entry_count")
    ):
        raise SystemExit("Scenario Chart prompt corpus contract drift")
    start, end = offsets[0:2]
    original_stored = original_stage[start:end]
    final_stored = stage_archive[start:end]
    original_decoded = decode(original_stored)
    final_decoded = decode(final_stored)
    if (
        any(original_stored[original_decoded.consumed :])
        or any(final_stored[final_decoded.consumed :])
        or len(original_decoded.output) != len(final_decoded.output)
    ):
        raise SystemExit("Scenario Chart prompt STAGE decode drift")
    source_texts = {
        "0x1F790": "：決定",
        "0x1F798": "：戻る",
        "0x1F7A0": "：スピードＵＰ",
    }
    if set(replacements) != set(source_texts):
        raise SystemExit("Scenario Chart prompt source selection drift")
    readbacks = {}
    for raw_offset, expected_text in replacements.items():
        offset = int(raw_offset, 16)
        source = decode_text(original_decoded.output, offset, source_table)
        actual = decode_text(final_decoded.output, offset, output_table)
        if (
            raw_offset != f"0x{offset:X}"
            or source.text != source_texts[raw_offset]
            or actual.text != expected_text
            or actual.consumed > source.consumed
            or any(
                final_decoded.output[
                    offset + actual.consumed : offset + source.consumed
                ]
            )
        ):
            raise SystemExit(
                f"final ISO Scenario Chart prompt mismatch: {raw_offset}"
            )
        readbacks[raw_offset] = {
            "source_text": source.text,
            "translation": actual.text,
            "source_capacity": source.consumed,
            "output_size": actual.consumed,
            "headroom": source.consumed - actual.consumed,
            "readback_exact": True,
        }
    return {
        "member": "DATA/STAGE.BIN",
        "chunk_index": 0,
        "entry_count": len(readbacks),
        "entries": readbacks,
        "fixed_spans_preserved": True,
        "zero_padding_preserved": True,
        "translated_readback_exact": True,
    }


def verify_scenario_select_effect(
    slps: bytes,
    archive: bytes,
    component_manifest: dict | None,
    *,
    config_key: str = "scenario_select_effect",
) -> dict:
    """Reread one localized VEFF2DX label texture."""

    config = json.loads(FULL_COMPONENT_CONFIG.read_text(encoding="utf-8"))
    effect = config.get(config_key)
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
        component_manifest.get(config_key, {})
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


def verify_nisv_effect_names(
    slps: bytes,
    archive: bytes,
    source_table: TextTable,
    output_table: TextTable,
    component_manifest: dict | None,
) -> dict:
    """Reread the duplicated weapon-effect labels from NisVData chunk 6."""

    config = json.loads(FULL_COMPONENT_CONFIG.read_text(encoding="utf-8"))
    reference = config.get("nisv_effect_names")
    if not isinstance(reference, dict):
        raise SystemExit("NisVData effect-name config is missing")
    archive_spec = reference["archive"]
    target = reference["target"]
    expected = reference["expected"]
    translations_reference = reference["translations"]
    translations_path = PROJECT_ROOT / translations_reference["path"]
    translations_data = translations_path.read_bytes()
    if (
        len(translations_data) != translations_reference["size"]
        or sha256_bytes(translations_data) != translations_reference["sha256"]
    ):
        raise SystemExit("NisVData effect-name corpus lock drift")
    document = json.loads(translations_data.decode("utf-8"))
    terms = document.get("nisv_effect_names")
    if (
        not isinstance(terms, list)
        or len(terms) != expected["term_count"]
        or sum(len(item["decoded_offsets"]) for item in terms)
        != expected["occurrence_count"]
    ):
        raise SystemExit("NisVData effect-name corpus selection drift")
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
        or len(archive) != reference["original_archive"]["size"]
    ):
        raise SystemExit("final ISO NisVData layout drifted")
    stored = archive[offsets[chunk_index] : offsets[chunk_index + 1]]
    decoded = decode(stored)
    if (
        len(decoded.output) != target["decoded_size"]
        or any(stored[decoded.consumed :])
    ):
        raise SystemExit("final ISO NisVData chunk decode drift")
    term_reports = []
    raw_visible_ascii_glyph_count = 0
    raw_visible_ascii_target_count = 0
    raw_space_target_count = 0
    for item in terms:
        source_encoded = encode_text(
            item["source"], source_table, terminate=False
        )
        translation = normalize_original_fullwidth_ascii(item["translation"])
        decoded_offsets = [int(value, 0) for value in item["decoded_offsets"]]
        for offset in decoded_offsets:
            actual = decode_text(decoded.output, offset, output_table)
            translation_size = len(
                encode_text(translation, output_table, terminate=False)
            )
            translation_payload = decoded.output[
                offset : offset + translation_size
            ]
            raw_ascii = raw_visible_ascii_glyphs(translation_payload)
            raw_visible_ascii_glyph_count += len(raw_ascii)
            raw_visible_ascii_target_count += bool(raw_ascii)
            raw_space_target_count += b"\x20" in translation_payload
            if not actual.text.startswith(translation + "\u3000") or (
                decoded.output[offset : offset + len(source_encoded)]
                == source_encoded
            ):
                raise SystemExit(
                    "final ISO NisVData effect-name mismatch at "
                    f"0x{offset:X}"
                )
        residual_source_offsets = []
        cursor = 0
        while True:
            cursor = decoded.output.find(source_encoded, cursor)
            if cursor < 0:
                break
            residual_source_offsets.append(cursor)
            cursor += 1
        if residual_source_offsets:
            raise SystemExit(
                "final ISO NisVData retains source effect name "
                f"{item['source']!r} at "
                + ", ".join(
                    f"0x{offset:X}" for offset in residual_source_offsets
                )
            )
        term_reports.append(
            {
                "source": item["source"],
                "translation": translation,
                "decoded_offsets": decoded_offsets,
                "residual_source_occurrence_count": 0,
                "reread_exact": True,
            }
        )
    manifest_report = (
        component_manifest.get("nisv_effect_names", {})
        if component_manifest is not None
        else {}
    )
    if (
        manifest_report.get("term_count") != len(term_reports)
        or manifest_report.get("occurrence_count")
        != sum(len(item["decoded_offsets"]) for item in term_reports)
        or raw_visible_ascii_glyph_count
        or raw_visible_ascii_target_count
        or raw_space_target_count
    ):
        raise SystemExit("final ISO NisVData component report drift")
    return {
        "member": archive_spec["member"],
        "chunk_index": chunk_index,
        "term_count": len(term_reports),
        "occurrence_count": sum(
            len(item["decoded_offsets"]) for item in term_reports
        ),
        "terms": term_reports,
        "codec_padding_zero": True,
        "archive_offsets_preserved": True,
        "all_source_occurrences_absent": True,
        "raw_visible_ascii_glyph_count": 0,
        "raw_visible_ascii_target_count": 0,
        "raw_space_target_count": 0,
        "runtime_control_tokens_excluded": True,
        "translated_reread_exact": True,
    }


def verify_nisv_strategy_qa(
    slps: bytes,
    archive: bytes,
    output_table: TextTable,
    component_manifest: dict | None,
) -> dict:
    """Independently reread the complete translated Strategy Q&A surface."""

    config = json.loads(FULL_COMPONENT_CONFIG.read_text(encoding="utf-8"))
    reference = config.get("nisv_strategy_qa")
    if not isinstance(reference, dict):
        raise SystemExit("NisVData Strategy Q&A config is missing")
    corpus_reference = reference.get("corpus")
    source_reference = reference.get("original_archive")
    if not isinstance(corpus_reference, dict) or not isinstance(
        source_reference, dict
    ):
        raise SystemExit("NisVData Strategy Q&A input locks are missing")
    corpus_path = project_path(Path(corpus_reference["path"]))
    corpus_data = corpus_path.read_bytes()
    if (
        len(corpus_data) != corpus_reference.get("size")
        or sha256_bytes(corpus_data) != corpus_reference.get("sha256")
    ):
        raise SystemExit("NisVData Strategy Q&A corpus lock drift")
    corpus = json.loads(corpus_data.decode("utf-8"))
    if (
        corpus.get("expected_metadata_string_count")
        != QA_METADATA_STRING_COUNT
        or corpus.get("expected_page_count") != QA_PAGE_COUNT
        or corpus.get("expected_text_record_count") != QA_TEXT_RECORD_COUNT
    ):
        raise SystemExit("NisVData Strategy Q&A corpus identity drift")

    source_path = project_path(Path(source_reference["path"]))
    source_archive = source_path.read_bytes()
    if (
        len(source_archive) != source_reference.get("size")
        or sha256_bytes(source_archive) != source_reference.get("sha256")
    ):
        raise SystemExit("NisVData Strategy Q&A source archive lock drift")
    archive_spec = reference["archive"]
    target = reference["target"]
    spec = ExecutableOffsetSpec(
        name=archive_spec["name"],
        member=archive_spec["member"],
        table_start=int(archive_spec["table_start"], 0),
        table_end=int(archive_spec["table_end"], 0),
    )
    final_offsets = read_executable_archive_offsets(slps, spec, len(archive))
    source_offsets = read_executable_archive_offsets(
        slps, spec, len(source_archive)
    )
    chunk_index = target["chunk_index"]
    if (
        final_offsets != source_offsets
        or final_offsets[chunk_index] != target["stored_start"]
        or final_offsets[chunk_index + 1] != target["stored_end"]
    ):
        raise SystemExit("final ISO Strategy Q&A archive layout drift")
    final_stored = archive[
        final_offsets[chunk_index] : final_offsets[chunk_index + 1]
    ]
    source_stored = source_archive[
        source_offsets[chunk_index] : source_offsets[chunk_index + 1]
    ]
    final_decoded = decode(final_stored)
    source_decoded = decode(source_stored)
    if (
        len(final_decoded.output) != target["decoded_size"]
        or len(source_decoded.output) != target["decoded_size"]
        or any(final_stored[final_decoded.consumed :])
    ):
        raise SystemExit("final ISO Strategy Q&A chunk decode drift")
    final_qa = parse_nisv_strategy_qa(final_decoded.output)
    source_qa = parse_nisv_strategy_qa(source_decoded.output)
    if (
        final_qa["entries"] != source_qa["entries"]
        or final_qa["metadata_prefix"] != source_qa["metadata_prefix"]
    ):
        raise SystemExit("final ISO Strategy Q&A allocation metadata drift")

    metadata_groups = (
        ("categories", 4),
        ("topics", 26),
        ("questions", 102),
        ("category_summaries", 4),
        ("topic_summaries", 26),
        ("keyword_summaries", 102),
    )
    semantic_records = []
    raw_visible_ascii_glyph_count = 0
    raw_visible_ascii_target_count = 0
    raw_space_target_count = 0
    metadata_count = 0
    for group_name, expected_count in metadata_groups:
        corpus_records = corpus["metadata"].get(group_name)
        source_records = source_qa["metadata"].get(group_name)
        final_records = final_qa["metadata"].get(group_name)
        if not all(
            len(records) == expected_count
            for records in (corpus_records, source_records, final_records)
        ):
            raise SystemExit(
                f"final ISO Strategy Q&A metadata group drift: {group_name}"
            )
        for corpus_record, source_raw, final_raw in zip(
            corpus_records, source_records, final_records
        ):
            if source_raw != corpus_record["source"].encode("cp932"):
                raise SystemExit(
                    "final ISO Strategy Q&A metadata source preimage drift: "
                    f"{corpus_record['id']}"
                )
            actual = normalize_two_byte_visible_spaces(
                decode_text(final_raw + b"\x00", 0, output_table).text
            )
            if actual != corpus_record["translation"]:
                raise SystemExit(
                    "final ISO Strategy Q&A metadata mismatch: "
                    f"{corpus_record['id']}"
                )
            raw_ascii = raw_visible_ascii_glyphs(final_raw)
            raw_visible_ascii_glyph_count += len(raw_ascii)
            raw_visible_ascii_target_count += bool(raw_ascii)
            raw_space_target_count += b"\x20" in final_raw
            semantic_records.append((corpus_record, actual))
            metadata_count += 1

    glyph_advance_px = reference["format"]["glyph_advance_px"]
    line_step_y = reference["format"]["line_step_y"]
    max_last_glyph_x = reference["format"]["max_last_glyph_x"]
    page_count = 0
    text_record_count = 0
    reflowed_record_count = 0
    horizontally_reflowed_record_count = 0
    vertically_reflowed_record_count = 0
    fixed_column_line_count = 0
    empty_translation_record_count = 0
    source_style_counts = Counter()
    for page_index, (corpus_page, source_page, final_page) in enumerate(
        zip(corpus["pages"], source_qa["pages"], final_qa["pages"]),
        start=1,
    ):
        corpus_records = corpus_page.get("records")
        if (
            corpus_page.get("page") != page_index
            or len(corpus_records) != len(source_page["records"])
            or len(final_page["records"]) != len(source_page["records"])
            or final_page["size"] != source_page["size"]
            or final_page["sprite_size"] != source_page["sprite_size"]
            or final_page["sprite_bytes"] != source_page["sprite_bytes"]
        ):
            raise SystemExit(
                f"final ISO Strategy Q&A page structure drift: {page_index}"
            )
        page_layout = layout_nisv_strategy_qa_page(
            source_page,
            corpus_records,
            glyph_advance_px=glyph_advance_px,
            line_step_y=line_step_y,
            max_last_glyph_x=max_last_glyph_x,
        )
        fixed_column_line_count += page_layout["fixed_column_line_count"]
        empty_translation_record_count += page_layout[
            "empty_translation_record_count"
        ]
        for corpus_record, source_record, final_record, expected_position in zip(
            corpus_records,
            source_page["records"],
            final_page["records"],
            page_layout["positions"],
        ):
            record_id = corpus_record["id"]
            if source_record["raw"] != corpus_record["source"].encode("cp932"):
                raise SystemExit(
                    f"final ISO Strategy Q&A source preimage drift: {record_id}"
                )
            actual = normalize_two_byte_visible_spaces(
                decode_text(final_record["raw"] + b"\x00", 0, output_table).text
            )
            if actual != corpus_record["translation"]:
                raise SystemExit(
                    f"final ISO Strategy Q&A text mismatch: {record_id}"
                )
            if (
                final_record["style0"] != source_record["style0"]
                or final_record["style1"] != source_record["style1"]
                or final_record["z"] != source_record["z"]
            ):
                raise SystemExit(
                    f"final ISO Strategy Q&A visual style drift: {record_id}"
                )
            if (
                final_record["x"],
                final_record["y"],
                final_record["z"],
            ) != expected_position:
                raise SystemExit(
                    f"final ISO Strategy Q&A positioned layout drift: {record_id}"
                )
            reflowed_record_count += (
                final_record["x"], final_record["y"]
            ) != (source_record["x"], source_record["y"])
            horizontally_reflowed_record_count += (
                final_record["x"] != source_record["x"]
            )
            vertically_reflowed_record_count += (
                final_record["y"] != source_record["y"]
            )
            raw_ascii = raw_visible_ascii_glyphs(final_record["raw"])
            raw_visible_ascii_glyph_count += len(raw_ascii)
            raw_visible_ascii_target_count += bool(raw_ascii)
            raw_space_target_count += b"\x20" in final_record["raw"]
            source_style_counts[
                (source_record["style0"], source_record["style1"])
            ] += 1
            semantic_records.append((corpus_record, actual))
            text_record_count += 1
        page_count += 1

    if (
        metadata_count != QA_METADATA_STRING_COUNT
        or page_count != QA_PAGE_COUNT
        or text_record_count != QA_TEXT_RECORD_COUNT
        or raw_visible_ascii_glyph_count
        or raw_visible_ascii_target_count
        or raw_space_target_count
    ):
        raise SystemExit(
            "final ISO Strategy Q&A inventory or storage drift: "
            f"metadata={metadata_count}, pages={page_count}, "
            f"records={text_record_count}, raw_ascii="
            f"{raw_visible_ascii_glyph_count}, raw_ascii_targets="
            f"{raw_visible_ascii_target_count}, raw_space_targets="
            f"{raw_space_target_count}"
        )
    component_report = (
        component_manifest.get("nisv_strategy_qa", {})
        if component_manifest is not None
        else {}
    )
    if (
        component_report.get("metadata_string_count") != metadata_count
        or component_report.get("page_count") != page_count
        or component_report.get("text_record_count") != text_record_count
        or component_report.get("output_encoded_size") != final_decoded.consumed
        or component_report.get("record_styles_preserved") is not True
        or component_report.get("record_z_coordinates_preserved") is not True
        or component_report.get("mixed_style_line_flow") is not True
        or component_report.get("empty_continuation_rows_collapsed") is not True
        or component_report.get("fixed_column_anchors_aligned") is not True
        or component_report.get("empty_records_extend_scroll_height") is not False
        or component_report.get("translated_reread_exact") is not True
    ):
        raise SystemExit("final ISO Strategy Q&A component report drift")

    effect_reference = config["nisv_effect_names"]
    effect_corpus_reference = effect_reference["translations"]
    effect_corpus_data = project_path(
        Path(effect_corpus_reference["path"])
    ).read_bytes()
    if (
        len(effect_corpus_data) != effect_corpus_reference["size"]
        or sha256_bytes(effect_corpus_data)
        != effect_corpus_reference["sha256"]
    ):
        raise SystemExit("NisVData effect-name corpus lock drift")
    effect_terms = json.loads(effect_corpus_data.decode("utf-8"))[
        "nisv_effect_names"
    ]
    effect_reports = []
    for item in effect_terms:
        matches = [
            (record, actual)
            for record, actual in semantic_records
            if item["source"] in record["source"]
        ]
        if (
            len(matches) != len(item["decoded_offsets"])
            or any(item["translation"] not in actual for _record, actual in matches)
            or any(
                item["source"] in actual
                for _record, actual in semantic_records
            )
        ):
            raise SystemExit(
                "final ISO Strategy Q&A effect-name semantic mismatch: "
                f"{item['source']}"
            )
        effect_reports.append(
            {
                "source": item["source"],
                "translation": item["translation"],
                "record_ids": [record["id"] for record, _actual in matches],
                "occurrence_count": len(matches),
                "residual_source_occurrence_count": 0,
                "reread_exact": True,
            }
        )
    effect_names = {
        "member": archive_spec["member"],
        "chunk_index": chunk_index,
        "term_count": len(effect_reports),
        "occurrence_count": sum(
            item["occurrence_count"] for item in effect_reports
        ),
        "terms": effect_reports,
        "codec_padding_zero": True,
        "archive_offsets_preserved": True,
        "all_source_occurrences_absent": True,
        "raw_visible_ascii_glyph_count": 0,
        "raw_visible_ascii_target_count": 0,
        "raw_space_target_count": 0,
        "runtime_control_tokens_excluded": True,
        "translated_reread_exact": True,
    }
    return {
        "member": archive_spec["member"],
        "chunk_index": chunk_index,
        "metadata_string_count": metadata_count,
        "page_count": page_count,
        "text_record_count": text_record_count,
        "style_counts": {
            f"{style0:02X}:{style1:02X}": count
            for (style0, style1), count in sorted(source_style_counts.items())
        },
        "output_encoded_size": final_decoded.consumed,
        "output_padding_size": len(final_stored) - final_decoded.consumed,
        "reflowed_record_count": reflowed_record_count,
        "horizontally_reflowed_record_count": horizontally_reflowed_record_count,
        "vertically_reflowed_record_count": vertically_reflowed_record_count,
        "fixed_column_line_count": fixed_column_line_count,
        "empty_translation_record_count": empty_translation_record_count,
        "allocation_table_preserved": True,
        "metadata_indexes_preserved": True,
        "page_allocations_preserved": True,
        "record_styles_preserved": True,
        "record_z_coordinates_preserved": True,
        "mixed_style_line_flow": True,
        "empty_continuation_rows_collapsed": True,
        "fixed_column_anchors_aligned": True,
        "empty_records_extend_scroll_height": False,
        "glyph_advance_px": glyph_advance_px,
        "line_step_y": line_step_y,
        "max_last_glyph_x": max_last_glyph_x,
        "sprite_sections_preserved": True,
        "archive_offsets_preserved": True,
        "codec_padding_zero": True,
        "raw_visible_ascii_glyph_count": 0,
        "raw_visible_ascii_target_count": 0,
        "raw_space_target_count": 0,
        "translated_reread_exact": True,
        "effect_names": effect_names,
    }


def verify_stage_fixed_formation(
    stage: bytes,
    hb: bytes,
    source_table: TextTable,
    output_table: TextTable,
) -> dict:
    """Reread the nine fixed default-squad names from STAGE chunk 101."""

    component_config = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )
    remaining_config = component_config["remaining_ui"]
    expected = remaining_config["expected"]
    document = json.loads(
        (
            PROJECT_ROOT / remaining_config["translations"]["path"]
        ).read_text(encoding="utf-8")
    )
    translations = document.get("stage_fixed_formation_by_offset")
    chunk_index = expected.get("stage_fixed_formation_chunk_index")
    if (
        not isinstance(translations, dict)
        or len(translations)
        != expected.get("stage_fixed_formation_entry_count")
        or not isinstance(chunk_index, int)
    ):
        raise SystemExit("fixed formation-name selection drift")
    original_stage_path = (
        PROJECT_ROOT / remaining_config["original_stage"]["path"]
    )
    original_stage = original_stage_path.read_bytes()
    if (
        len(original_stage) != remaining_config["original_stage"]["size"]
        or sha256_bytes(original_stage)
        != remaining_config["original_stage"]["sha256"]
        or len(original_stage) != len(stage)
    ):
        raise SystemExit("original STAGE baseline drift")

    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member="HEDBDY/HB.BIN",
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(hb, offset_spec, len(stage))
    if chunk_index + 1 >= len(offsets):
        raise SystemExit("fixed formation-name STAGE chunk is missing")
    start, end = offsets[chunk_index : chunk_index + 2]
    current_stored = stage[start:end]
    original_stored = original_stage[start:end]
    current = decode(current_stored)
    original = decode(original_stored)
    if (
        any(current_stored[current.consumed :])
        or any(original_stored[original.consumed :])
        or len(current.output) != len(original.output)
    ):
        raise SystemExit("fixed formation-name STAGE chunk decode drift")

    minimum_headroom = None
    for raw_offset, raw_translation in translations.items():
        offset = int(raw_offset, 16)
        source = decode_text(original.output, offset, source_table)
        actual = decode_text(current.output, offset, output_table)
        translation = normalize_original_fullwidth_ascii(raw_translation)
        if source.text != "別働隊":
            raise SystemExit(
                f"fixed formation-name source drift at {raw_offset}"
            )
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
                f"fixed formation-name control-token drift at {raw_offset}"
            )
        if actual.text != translation or actual.consumed > source.consumed:
            raise SystemExit(
                f"fixed formation-name mismatch at {raw_offset}: "
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
        "chunk_index": chunk_index,
        "source_text": "別働隊",
        "translation": "别动队",
        "minimum_output_headroom": minimum_headroom,
        "placeholder_control_tokens_preserved": True,
        "archive_padding_zero": True,
        "readback_exact": True,
    }


def verify_stage_default_formation(
    stage: bytes,
    hb: bytes,
    source_table: TextTable,
    output_table: TextTable,
) -> dict:
    """Reread every reviewed fixed-position formation name from final STAGE."""

    component_config = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )
    remaining_config = component_config["remaining_ui"]
    expected = remaining_config["expected"]
    corpus_reference = remaining_config.get("stage_default_formations")
    if not isinstance(corpus_reference, dict):
        raise SystemExit("default formation-name corpus contract drift")
    corpus_path = PROJECT_ROOT / corpus_reference["path"]
    corpus_data = corpus_path.read_bytes()
    if (
        len(corpus_data) != corpus_reference.get("size")
        or sha256_bytes(corpus_data) != corpus_reference.get("sha256")
    ):
        raise SystemExit("default formation-name corpus lock drift")
    inventory_reference = remaining_config.get(
        "stage_default_formation_inventory"
    )
    if not isinstance(inventory_reference, dict):
        raise SystemExit("default formation-name inventory contract drift")
    inventory_path = PROJECT_ROOT / inventory_reference["path"]
    inventory_data = inventory_path.read_bytes()
    if (
        len(inventory_data) != inventory_reference.get("size")
        or sha256_bytes(inventory_data) != inventory_reference.get("sha256")
    ):
        raise SystemExit("default formation-name inventory lock drift")
    document = json.loads(corpus_data.decode("utf-8"))
    inventory_document = json.loads(inventory_data.decode("utf-8"))
    translations_by_source = document.get("translations_by_source_text")
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
    ):
        raise SystemExit("default formation-name corpus drift")
    original_stage = (
        PROJECT_ROOT / remaining_config["original_stage"]["path"]
    ).read_bytes()
    if (
        len(original_stage) != remaining_config["original_stage"]["size"]
        or sha256_bytes(original_stage)
        != remaining_config["original_stage"]["sha256"]
        or len(original_stage) != len(stage)
    ):
        raise SystemExit("original STAGE baseline drift")

    try:
        groups = load_locked_stage_default_formations(
            original_stage,
            hb,
            source_table,
            inventory_document,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    locked_source_texts = {
        cell.source_text for group in groups for cell in group.cells
    }
    if set(translations_by_source) != locked_source_texts:
        missing = sorted(locked_source_texts - set(translations_by_source))
        extra = sorted(set(translations_by_source) - locked_source_texts)
        raise SystemExit(
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
        for layout in sorted({group.layout for group in groups})
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
    ):
        raise SystemExit("default formation-name inventory drift")

    offsets = read_executable_archive_offsets(
        hb, STAGE_OFFSET_SPEC, len(stage)
    )
    decoded_by_stage = {}
    original_by_stage = {}
    minimum_headroom = None
    translations = set()
    compact_ascii_entry_count = 0
    ranges_by_stage: dict[int, list[tuple[int, int]]] = {}
    indexed_cells = sorted(
        (
            (group.stage_index, group, cell)
            for group in groups
            for cell in group.cells
        ),
        key=lambda item: (item[0], item[2].offset),
    )
    for stage_index, group, cell in indexed_cells:
        slot_size = group.slot_size
        if stage_index < 0 or stage_index + 1 >= len(offsets):
            raise SystemExit("default formation-name group contract drift")
        if stage_index not in decoded_by_stage:
            start, end = offsets[stage_index : stage_index + 2]
            stored = stage[start:end]
            original_stored = original_stage[start:end]
            decoded = decode(stored)
            original = decode(original_stored)
            if (
                any(stored[decoded.consumed :])
                or any(original_stored[original.consumed :])
                or len(decoded.output) != len(original.output)
            ):
                raise SystemExit(
                    f"default formation-name decode drift: {stage_index}"
                )
            decoded_by_stage[stage_index] = decoded.output
            original_by_stage[stage_index] = original.output
            ranges_by_stage[stage_index] = []
        decoded = decoded_by_stage[stage_index]
        original = original_by_stage[stage_index]
        decoded_offset = cell.offset
        raw_offset = f"0x{decoded_offset:X}"
        slot_end = decoded_offset + slot_size
        if slot_end > len(decoded):
            raise SystemExit(
                f"default formation-name entry drift: {raw_offset!r}"
            )
        ranges = ranges_by_stage[stage_index]
        if ranges and decoded_offset < ranges[-1][1]:
            raise SystemExit(
                f"default formation-name overlap: {raw_offset}"
            )
        ranges.append((decoded_offset, slot_end))
        source = decode_text(
            original, decoded_offset, source_table, end=slot_end
        )
        actual = decode_text(decoded, decoded_offset, output_table)
        translation = normalize_original_fullwidth_ascii(
            translations_by_source[cell.source_text]
        )
        expected_compact = compact_formation_ascii_replacement(
            source_text=source.text,
            translation=translation,
            layout=group.layout,
            slot_size=slot_size,
        )
        if (
            source.text != cell.source_text
            or source.consumed != cell.source_consumed
            or any(original[decoded_offset + source.consumed : slot_end])
            or actual.text != translation
            or actual.consumed > slot_size
            or any(decoded[decoded_offset + actual.consumed : slot_end])
        ):
            raise SystemExit(
                f"default formation-name mismatch at stage "
                f"{stage_index} {raw_offset}"
            )
        if group.layout.startswith("pointer8-") and (
            not has_stage_formation_pointer_owner(original, decoded_offset)
            or not has_stage_formation_pointer_owner(decoded, decoded_offset)
        ):
            raise SystemExit(
                "default formation-name pointer owner mismatch at stage "
                f"{stage_index} {raw_offset}"
            )
        if expected_compact is not None:
            if decoded[decoded_offset:slot_end] != expected_compact:
                raise SystemExit(
                    "default formation-name compact ASCII drift at stage "
                    f"{stage_index} {raw_offset}"
                )
            compact_ascii_entry_count += 1
        if group.layout in {"record6+23", "formation18+33+1"}:
            prefix_size = 6 if group.layout == "record6+23" else 18
            metadata_start = decoded_offset - prefix_size
            expected_metadata = bytes.fromhex(cell.prefix_hex)
            if (
                metadata_start < 0
                or len(expected_metadata) != prefix_size
                or original[metadata_start:decoded_offset] != expected_metadata
                or decoded[metadata_start:decoded_offset] != expected_metadata
            ):
                raise SystemExit(
                    "default formation-name metadata mismatch at stage "
                    f"{stage_index} {raw_offset}"
                )
            if group.layout == "formation18+33+1":
                expected_trailer = bytes.fromhex(cell.trailer_hex)
                if (
                    len(expected_trailer) != 1
                    or original[slot_end : slot_end + 1] != expected_trailer
                    or decoded[slot_end : slot_end + 1] != expected_trailer
                ):
                    raise SystemExit(
                        "default formation-name trailer mismatch at stage "
                        f"{stage_index} {raw_offset}"
                    )
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
                f"default formation-name control drift at {raw_offset}"
            )
        headroom = slot_size - actual.consumed
        minimum_headroom = (
            headroom
            if minimum_headroom is None
            else min(minimum_headroom, headroom)
        )
        translations.add((source.text, translation))
    if compact_ascii_entry_count != expected.get(
        "stage_default_formation_compact_ascii_entry_count"
    ):
        raise SystemExit(
            "default formation-name compact ASCII ratchet drift"
        )
    return {
        "group_count": len(groups),
        "stage_count": len(decoded_by_stage),
        "stage_indices": sorted(decoded_by_stage),
        "entry_count": entry_count,
        "unique_source_count": len(source_texts),
        "layout_group_counts": layout_counts,
        "record_metadata_count": record_metadata_count,
        "compact_ascii_entry_count": compact_ascii_entry_count,
        "inventory_sha256": inventory_sha256,
        "translations": [
            {"source": source, "translation": translation}
            for source, translation in sorted(translations)
        ],
        "minimum_slot_headroom": minimum_headroom,
        "source_preimages_exact": True,
        "fixed_allocations_preserved": True,
        "record_metadata_preserved_byte_exact": True,
        "slot_padding_zero": True,
        "archive_padding_zero": True,
        "placeholder_control_tokens_preserved": True,
        "readback_exact": True,
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
    unit_corpus_path = PROJECT_ROOT / pilot_config["unit_names"]["path"]
    unit_decisions, unit_corpus_report = load_full_unit_name_corpus(
        PROJECT_ROOT,
        unit_corpus_path,
        source_names.unit_entries,
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
        or len(unit_decisions) != expected["unit_name_entry_count"]
    ):
        raise SystemExit("display-name source selection drift")

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

    unit_by_id = {
        entry.entry_id: entry for entry in reread.unit_entries
    }
    unit_examples = {}
    raw_unit_relocations = pilot_config.get("unit_name_relocations", [])
    if not isinstance(raw_unit_relocations, list):
        raise SystemExit("final ISO unit-name relocations are malformed")
    unit_relocations = {}
    for item in raw_unit_relocations:
        if not isinstance(item, dict) or not isinstance(
            item.get("entry_id"), str
        ):
            raise SystemExit("final ISO unit-name relocation is malformed")
        entry_id = item["entry_id"]
        if entry_id in unit_relocations:
            raise SystemExit("final ISO unit-name relocation ID is duplicated")
        try:
            unit_relocations[entry_id] = {
                "source_target_offset": int(
                    str(item.get("source_target_offset")), 0
                ),
                "target_offset": int(str(item.get("target_offset")), 0),
            }
        except (TypeError, ValueError) as error:
            raise SystemExit(
                f"final ISO unit-name relocation offsets are invalid: {entry_id}"
            ) from error
    unit_pointer_base = int(
        str(structure["unit_table"]["pointer_base_address"]), 0
    )
    relocated_pointer_count = 0
    unit_space_code = output_table.inverse_characters.get("\u3000")
    if unit_space_code is None or unit_space_code < 0x8000:
        raise SystemExit("final ISO unit-name two-byte space code is absent")
    unit_space_payload = unit_space_code.to_bytes(2, "big")
    unit_two_byte_space_ids = []
    unit_example_ids = {
        "display-name/unit/0157/name",
        "display-name/unit/0158/name",
    }
    for source_entry in source_names.unit_entries:
        actual_entry = unit_by_id.get(source_entry.entry_id)
        relocation = unit_relocations.get(source_entry.entry_id)
        expected_target = (
            source_entry.target_offset
            if relocation is None
            else relocation["target_offset"]
        )
        if (
            actual_entry is None
            or actual_entry.target_offset != expected_target
            or actual_entry.pointer_offsets != source_entry.pointer_offsets
            or (
                relocation is not None
                and relocation["source_target_offset"]
                != source_entry.target_offset
            )
        ):
            raise SystemExit(
                "final ISO unit-name target or pointer-site mismatch: "
                f"{source_entry.entry_id}"
            )
        if relocation is not None:
            pointer_payload = struct.pack(
                "<I", unit_pointer_base + expected_target
            )
            for pointer_offset in actual_entry.pointer_offsets:
                if (
                    decoded_compdata.output[
                        pointer_offset : pointer_offset + 4
                    ]
                    != pointer_payload
                ):
                    raise SystemExit(
                        "final ISO relocated unit pointer mismatch: "
                        f"{source_entry.entry_id}"
                    )
                relocated_pointer_count += 1
        expected_unit = normalize_original_fullwidth_ascii(
            unit_decisions[source_entry.entry_id]["translation"]
        )
        actual_unit = (
            None
            if actual_entry is None
            else actual_entry.text.replace("\u3000", " ")
        )
        if actual_unit != expected_unit:
            raise SystemExit(
                f"final ISO unit-name mismatch: {source_entry.entry_id}: "
                f"expected {expected_unit!r}, got "
                f"{actual_unit!r}"
            )
        if " " in expected_unit:
            field_payload = decoded_compdata.output[
                actual_entry.target_offset :
                actual_entry.target_offset + actual_entry.encoded_size
            ]
            if (
                b"\x20" in field_payload
                or field_payload.count(unit_space_payload)
                != expected_unit.count(" ")
            ):
                raise SystemExit(
                    "final ISO unit-name space storage mismatch: "
                    f"{source_entry.entry_id}"
                )
            unit_two_byte_space_ids.append(source_entry.entry_id)
        if source_entry.entry_id in unit_example_ids:
            unit_examples[source_entry.entry_id] = actual_unit

    descriptors = json.loads(MENU_DESCRIPTOR.read_text(encoding="utf-8"))
    descriptor = next(
        item for item in descriptors if item.get("friendly_name") == "Compdata"
    )
    parsed_menu = parse_menu_file(
        decoded_compdata.output,
        descriptor,
        output_table,
    )
    slps_descriptor = next(
        item for item in descriptors if item.get("friendly_name") == "SLPS"
    )
    parsed_slps_menu = parse_menu_file(slps, slps_descriptor, output_table)

    ascii_audit_config = component_config.get("ability_visible_ascii_audit")
    if not isinstance(ascii_audit_config, dict):
        raise SystemExit("ability visible-ASCII audit config is missing")

    def locked_menu_audit_family(config_key: str, label: str):
        reference = ascii_audit_config.get(config_key)
        if not isinstance(reference, dict):
            raise SystemExit(f"{label} audit config is missing")
        corpus_reference = reference.get("corpus")
        expected = reference.get("expected")
        prefix = reference.get("entry_id_prefix")
        if (
            not isinstance(corpus_reference, dict)
            or not isinstance(expected, dict)
            or not isinstance(prefix, str)
            or not prefix
        ):
            raise SystemExit(f"{label} audit config drift")
        corpus_path = PROJECT_ROOT / str(corpus_reference.get("path", ""))
        corpus_data = corpus_path.read_bytes()
        if (
            len(corpus_data) != corpus_reference.get("size")
            or sha256_bytes(corpus_data) != corpus_reference.get("sha256")
        ):
            raise SystemExit(f"{label} audit corpus lock drift")
        document = json.loads(corpus_data.decode("utf-8"))
        corpus_entries = document.get("entries")
        if (
            not isinstance(corpus_entries, list)
            or len(corpus_entries) != expected.get("entry_count")
        ):
            raise SystemExit(f"{label} audit corpus inventory drift")
        corpus_ids = [item.get("id") for item in corpus_entries]
        expected_ids = [
            f"{prefix}{ordinal:04d}" for ordinal in range(len(corpus_entries))
        ]
        menu_entries = [
            entry
            for entry in parsed_slps_menu.entries
            if entry.entry_id.startswith(prefix)
        ]
        if (
            corpus_ids != expected_ids
            or [entry.entry_id for entry in menu_entries] != expected_ids
        ):
            raise SystemExit(f"{label} audit menu inventory drift")
        return menu_entries, expected

    def audit_menu_visible_ascii(data: bytes, entries, expected: dict, label: str) -> dict:
        target_occurrence_count = sum(
            len(entry.target_offsets) for entry in entries
        )
        target_offsets = sorted(
            {
                offset
                for entry in entries
                for offset in entry.target_offsets
            }
        )
        raw_visible_ascii_glyph_count = 0
        raw_visible_ascii_target_count = 0
        raw_space_target_count = 0
        for offset in target_offsets:
            actual = decode_text(data, offset, output_table)
            payload = data[offset : offset + actual.consumed]
            raw_ascii = raw_visible_ascii_glyphs(payload)
            raw_visible_ascii_glyph_count += len(raw_ascii)
            raw_visible_ascii_target_count += bool(raw_ascii)
            raw_space_target_count += b"\x20" in payload
        if (
            len(entries) != expected.get("entry_count")
            or target_occurrence_count
            != expected.get("target_occurrence_count")
            or len(target_offsets) != expected.get("unique_target_count")
            or raw_visible_ascii_glyph_count
            or raw_visible_ascii_target_count
            or raw_space_target_count
            or any(entry.unknown_code_count for entry in entries)
        ):
            raise SystemExit(f"{label} contains unsafe single-byte text")
        return {
            "entry_count": len(entries),
            "target_occurrence_count": target_occurrence_count,
            "unique_target_count": len(target_offsets),
            "logical_visible_ascii_entry_count": sum(
                any("!" <= character <= "~" for character in entry.text)
                for entry in entries
            ),
            "runtime_control_token_count": sum(
                len(control_notation_tokens(entry.text)) for entry in entries
            ),
            "raw_visible_ascii_glyph_count": 0,
            "raw_visible_ascii_target_count": 0,
            "raw_space_target_count": 0,
            "runtime_control_tokens_excluded": True,
            "unknown_code_count": 0,
            "readback_exact": True,
        }

    pilot_skill_entries, pilot_skill_expected = locked_menu_audit_family(
        "pilot_skills", "pilot special skills"
    )
    pilot_skill_ascii_report = audit_menu_visible_ascii(
        slps,
        pilot_skill_entries,
        pilot_skill_expected,
        "pilot special skills",
    )
    unit_ui_entries, unit_ui_expected = locked_menu_audit_family(
        "unit_mech_pilot_weapon_ui", "unit/mech/pilot/weapon UI"
    )
    unit_ui_ascii_report = audit_menu_visible_ascii(
        slps,
        unit_ui_entries,
        unit_ui_expected,
        "unit/mech/pilot/weapon UI",
    )
    weapon_effect_1_ids = {
        f"menu/SLPS/11/{ordinal:04d}" for ordinal in range(5, 13)
    }
    weapon_effect_1_entries = [
        entry
        for entry in unit_ui_entries
        if entry.entry_id in weapon_effect_1_ids
    ]
    weapon_effect_1_ascii_report = audit_menu_visible_ascii(
        slps,
        weapon_effect_1_entries,
        {
            "entry_count": unit_ui_expected.get(
                "weapon_special_effect_1_entry_count"
            ),
            "target_occurrence_count": 8,
            "unique_target_count": 8,
        },
        "weapon special effect 1",
    )
    weapon_effect_label_ids = {
        "menu/SLPS/11/0092",
        "menu/SLPS/11/0093",
    }
    weapon_effect_label_entries = [
        entry
        for entry in unit_ui_entries
        if entry.entry_id in weapon_effect_label_ids
    ]
    weapon_effect_label_ascii_report = audit_menu_visible_ascii(
        slps,
        weapon_effect_label_entries,
        {
            "entry_count": unit_ui_expected.get(
                "weapon_special_effect_label_entry_count"
            ),
            "target_occurrence_count": 2,
            "unique_target_count": 2,
        },
        "weapon special-effect labels",
    )

    weapon_effect_help = {
        "0x77100": remaining_document["compdata_context_help_by_offset"].get(
            "0x77100"
        ),
        **{
            offset: item.get("translation")
            for offset, item in remaining_document[
                "compdata_inline_by_offset"
            ].items()
        },
    }
    if (
        len(weapon_effect_help)
        != unit_ui_expected.get("weapon_special_effect_help_entry_count")
        or any(not isinstance(text, str) for text in weapon_effect_help.values())
    ):
        raise SystemExit("weapon special-effect help inventory drift")
    help_raw_visible_ascii_glyph_count = 0
    help_raw_visible_ascii_target_count = 0
    help_raw_space_target_count = 0
    for raw_offset, translation in weapon_effect_help.items():
        offset = int(raw_offset, 16)
        actual = decode_text(decoded_compdata.output, offset, output_table)
        normalized_translation = normalize_original_fullwidth_ascii(
            translation
        )
        translation_size = len(
            encode_text(
                normalized_translation,
                output_table,
                terminate=False,
            )
        )
        payload = decoded_compdata.output[
            offset : offset + translation_size
        ]
        raw_ascii = raw_visible_ascii_glyphs(payload)
        if not actual.text.startswith(normalized_translation):
            raise SystemExit(
                f"weapon special-effect help mismatch at {raw_offset}"
            )
        help_raw_visible_ascii_glyph_count += len(raw_ascii)
        help_raw_visible_ascii_target_count += bool(raw_ascii)
        help_raw_space_target_count += b"\x20" in payload
    if (
        help_raw_visible_ascii_glyph_count
        or help_raw_visible_ascii_target_count
        or help_raw_space_target_count
    ):
        raise SystemExit(
            "weapon special-effect help contains unsafe single-byte text"
        )
    weapon_effect_help_ascii_report = {
        "entry_count": len(weapon_effect_help),
        "offsets": list(weapon_effect_help),
        "logical_visible_ascii_entry_count": sum(
            any("!" <= character <= "~" for character in text)
            for text in weapon_effect_help.values()
        ),
        "raw_visible_ascii_glyph_count": 0,
        "raw_visible_ascii_target_count": 0,
        "raw_space_target_count": 0,
        "runtime_control_tokens_excluded": True,
        "readback_exact": True,
    }
    ability_visible_ascii_report = {
        "pilot_special_skills": pilot_skill_ascii_report,
        "unit_mech_pilot_weapon_ui": unit_ui_ascii_report,
        "weapon_special_effect_1": weapon_effect_1_ascii_report,
        "weapon_special_effect_labels": weapon_effect_label_ascii_report,
        "weapon_special_effect_help": weapon_effect_help_ascii_report,
        "all_checked_fields_use_two_byte_visible_ascii": True,
    }

    display_name_raw_space_count = sum(
        b"\x20"
        in decoded_compdata.output[
            entry.target_offset : entry.target_offset + entry.encoded_size
        ]
        for entry in reread.entries
    )

    def raw_menu_space_count(data: bytes, entries) -> int:
        count = 0
        seen_offsets = set()
        for entry in entries:
            for offset in entry.target_offsets:
                if offset in seen_offsets:
                    continue
                seen_offsets.add(offset)
                decoded_entry = decode_text(data, offset, output_table)
                count += b"\x20" in data[
                    offset : offset + decoded_entry.consumed
                ]
        return count

    compdata_menu_raw_space_count = raw_menu_space_count(
        decoded_compdata.output, parsed_menu.entries
    )
    slps_menu_raw_space_count = raw_menu_space_count(
        slps, parsed_slps_menu.entries
    )
    if any(
        (
            display_name_raw_space_count,
            compdata_menu_raw_space_count,
            slps_menu_raw_space_count,
        )
    ):
        raise SystemExit("final ISO display/menu text contains raw spaces")
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

    def verify_inline_offset_map(
        data: bytes,
        original: bytes,
        translations: dict[str, dict[str, str]],
        label: str,
    ) -> dict:
        minimum_headroom = None
        ranges = []
        for raw_offset, entry in sorted(
            translations.items(), key=lambda item: int(item[0], 16)
        ):
            offset = int(raw_offset, 16)
            source = entry["source"]
            translation = normalize_original_fullwidth_ascii(
                entry["translation"]
            )
            source_encoded = encode_text(
                source, source_table, terminate=False
            )
            end = offset + len(source_encoded)
            if original[offset:end] != source_encoded:
                raise SystemExit(
                    f"{label} source preimage drift at {raw_offset}"
                )
            if ranges and offset < ranges[-1][1]:
                raise SystemExit(f"{label} overlap at {raw_offset}")
            ranges.append((offset, end))
            actual = decode_text(data[offset:end] + b"\0", 0, output_table)
            source_tokens = tuple(
                (token.kind, token.text)
                for token in control_notation_tokens(source)
            )
            target_tokens = tuple(
                (token.kind, token.text)
                for token in control_notation_tokens(translation)
            )
            if source_tokens != target_tokens:
                raise SystemExit(
                    f"{label} control-token drift at {raw_offset}"
                )
            if (
                actual.consumed != len(source_encoded) + 1
                or actual.text.rstrip("　") != translation
                or not set(actual.text[len(translation):]) <= {"　"}
            ):
                raise SystemExit(
                    f"{label} mismatch at {raw_offset}: "
                    f"expected={translation!r} actual={actual.text!r}"
                )
            headroom = len(actual.text) - len(translation)
            minimum_headroom = (
                headroom
                if minimum_headroom is None
                else min(minimum_headroom, headroom)
            )
        return {
            "entry_count": len(translations),
            "minimum_output_headroom_glyphs": minimum_headroom,
            "internal_entry_offsets_preserved": True,
            "fullwidth_space_padding_only": True,
            "placeholder_control_tokens_preserved": True,
            "readback_exact": True,
        }

    def verify_library_work_title_slots(
        data: bytes,
        original: bytes,
        references: dict[str, dict],
        canonical: dict,
    ) -> dict:
        entries = canonical.get("entries")
        if not isinstance(entries, list) or not entries:
            raise SystemExit("canonical LIBRARY work-title corpus drift")
        canonical_by_id = {entry.get("id"): entry for entry in entries}
        if (
            len(canonical_by_id) != len(entries)
            or set(canonical_by_id)
            != {f"auto-demo/title/{index:02d}" for index in range(len(entries))}
        ):
            raise SystemExit("canonical LIBRARY work-title IDs drift")
        if {
            reference.get("title_id") for reference in references.values()
        } != set(canonical_by_id):
            raise SystemExit("LIBRARY work-title slot coverage drift")

        minimum_headroom = None
        titles = []
        ranges = []
        for raw_offset, reference in sorted(
            references.items(), key=lambda item: int(item[0], 16)
        ):
            offset = int(raw_offset, 16)
            capacity = reference["capacity"]
            end = offset + capacity
            if ranges and offset < ranges[-1][1]:
                raise SystemExit(
                    f"LIBRARY work-title overlap at {raw_offset}"
                )
            ranges.append((offset, end))
            title_id = reference["title_id"]
            entry = canonical_by_id[title_id]
            source_span = original[offset:end]
            terminator = source_span.find(b"\0")
            try:
                source_text = source_span[:terminator].decode("cp932")
            except UnicodeDecodeError as error:
                raise SystemExit(
                    f"LIBRARY work-title source cannot decode: {title_id}"
                ) from error
            if (
                terminator <= 0
                or source_text != entry.get("source_text")
                or sha256_bytes(source_span)
                != reference.get("source_span_sha256")
                or any(source_span[terminator + 1 :])
            ):
                raise SystemExit(
                    f"LIBRARY work-title source preimage drift: {title_id}"
                )
            expected = normalize_original_fullwidth_ascii(
                entry["translation"]
            ).replace(" ", "\u3000")
            actual = decode_text(data, offset, output_table, end=end)
            if actual.text != expected or any(data[offset + actual.consumed : end]):
                raise SystemExit(
                    f"LIBRARY work-title mismatch: {title_id}: "
                    f"expected={expected!r} actual={actual.text!r}"
                )
            headroom = capacity - actual.consumed
            minimum_headroom = (
                headroom
                if minimum_headroom is None
                else min(minimum_headroom, headroom)
            )
            titles.append(
                {
                    "id": title_id,
                    "offset": offset,
                    "capacity": capacity,
                    "translation": entry["translation"],
                    "stored_translation": actual.text,
                    "headroom": headroom,
                }
            )
        return {
            "entry_count": len(titles),
            "minimum_output_headroom": minimum_headroom,
            "titles": titles,
            "canonical_title_corpus_reused": True,
            "source_preimages_sha256_exact": True,
            "fixed_spans_preserved": True,
            "zero_padding_preserved": True,
            "readback_exact": True,
        }

    direct_report = verify_offset_map(
        decoded_compdata.output,
        original_compdata.output,
        remaining_document["compdata_direct_by_offset"],
        "remaining COMPDATA UI",
    )
    canonical_work_titles = json.loads(
        (
            PROJECT_ROOT
            / component_config["auto_demo_overlays"]["title_corpus"]["path"]
        ).read_text(encoding="utf-8")
    )
    library_work_title_report = verify_library_work_title_slots(
        decoded_compdata.output,
        original_compdata.output,
        remaining_document["compdata_library_work_titles_by_offset"],
        canonical_work_titles,
    )
    context_help_report = verify_offset_map(
        decoded_compdata.output,
        original_compdata.output,
        remaining_document["compdata_context_help_by_offset"],
        "remaining COMPDATA context help",
    )
    inline_report = verify_inline_offset_map(
        decoded_compdata.output,
        original_compdata.output,
        remaining_document["compdata_inline_by_offset"],
        "remaining COMPDATA inline UI",
    )
    leadership_report = verify_offset_map(
        decoded_compdata.output,
        original_compdata.output,
        remaining_document["leadership_effect_by_offset"],
        "leadership effects",
    )
    slps_context_report = verify_offset_map(
        slps,
        original_slps,
        remaining_document["slps_context_ui_by_offset"],
        "remaining SLPS context UI",
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
    male_default_unit_name_expectations = {
        "0x3479E0": "钢狮子",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in male_default_unit_name_expectations
    } != male_default_unit_name_expectations:
        raise SystemExit("male default-unit-name offset contract drift")
    female_default_name_expectations = {
        "0x337728": "节子",
        "0x337730": "小原",
        "0x33B458": "节子",
        "0x33B460": "小原",
        "0x33E318": "小原节子",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in female_default_name_expectations
    } != female_default_name_expectations:
        raise SystemExit("female new-game default-name offset contract drift")
    female_default_unit_name_expectations = {
        "0x347A00": "巴尔戈拉",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in female_default_unit_name_expectations
    } != female_default_unit_name_expectations:
        raise SystemExit("female default-unit-name offset contract drift")
    formation_action_label_expectations = {
        "0x342580": "攻击",
        "0x3425B0": "反击",
        "0x3425C4": "参与攻击",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in formation_action_label_expectations
    } != formation_action_label_expectations:
        raise SystemExit("formation action-label offset contract drift")
    map_formation_name_expectations = {
        "0x345DC8": "TRI",
        "0x345DD0": "中央",
        "0x345DE0": "广域",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in map_formation_name_expectations
    } != map_formation_name_expectations:
        raise SystemExit("map formation-name offset contract drift")
    weapon_effect_1_expectations = {
        "0x3462A0": "SP降低（P系）",
        "0x3462C0": "运动性降低（R系）",
        "0x3462E0": "气力降低（P系）",
        "0x346300": "行动不能（P系）",
        "0x346320": "装甲值降低（R系）",
        "0x346340": "能力减半（P系）",
        "0x346360": "瞄准值降低（R系）",
        "0x346380": "EN降低（R系）",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in weapon_effect_1_expectations
    } != weapon_effect_1_expectations:
        raise SystemExit("weapon special-effect-1 offset contract drift")
    squad_formation_name_expectations = {
        "0x7F580": "TRI队形",
        "0x7F5A0": "中央队形",
        "0x7F5C0": "广域队形",
        "0x7F5E0": "TRI",
        "0x7F5E8": "中央",
        "0x7F5F8": "广域",
    }
    if {
        offset: remaining_document["compdata_direct_by_offset"].get(offset)
        for offset in squad_formation_name_expectations
    } != squad_formation_name_expectations:
        raise SystemExit("squad formation-name offset contract drift")
    spirit_acronym_expectations = {
        "0x343FB0": "热魂闪不铁集必加迅觉手狙直努乱分",
        "0x343FE0": "热魂闪不铁集必加迅觉手狙直幸努乱",
        "0x344010": "热魂闪不铁集必加迅觉手狙直努／乱分",
        "0x344040": "热魂闪不铁集必加迅觉手狙直幸努／乱",
        "0x344070": "热魂闪不铁集必加\n迅觉手狙直努乱分",
        "0x3440A0": "热魂闪不铁集必加\n迅觉手狙直幸努乱",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in spirit_acronym_expectations
    } != spirit_acronym_expectations:
        raise SystemExit("spirit-acronym offset contract drift")
    scenario_button_expectations = {
        "0x33BD4A": "：确定",
        "0x33BD58": "：取消",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in scenario_button_expectations
    } != scenario_button_expectations:
        raise SystemExit("scenario-select button-label offset contract drift")
    library_runtime_text_expectations = {
        "0x340BD8": "攻略Q&A",
        "0x340C08": "：确定",
        "0x340C10": "：返回",
        "0x340C18": "：切换页面",
        "0x3472B0": "　　＜机体图鉴＞　",
        "0x3472D0": "　　＜角色事典＞　　",
        "0x3472E8": "＜术语事典＞",
        "0x347300": "　　＜音乐选择＞　　",
        "0x347320": "　　＜剧情流程＞　　",
        "0x347338": "＜攻略Q&A＞",
    }
    if {
        offset: {
            **remaining_document["slps_context_ui_by_offset"],
            **remaining_document["slps_by_offset"],
        }.get(offset)
        for offset in library_runtime_text_expectations
    } != library_runtime_text_expectations:
        raise SystemExit("LIBRARY runtime-text offset contract drift")
    confirm_prompt_expectations = {
        "0x3407B0": "：确定",
        "0x340C08": "：确定",
        "0x340CA8": "：确定",
        "0x340E38": "：确定",
        "0x3434B0": "：确定",
        "0x3435C0": "：确定",
        "0x347870": "：确定",
    }
    if {
        offset: {
            **remaining_document["slps_context_ui_by_offset"],
            **remaining_document["slps_by_offset"],
        }.get(offset)
        for offset in confirm_prompt_expectations
    } != confirm_prompt_expectations:
        raise SystemExit("global confirm-prompt offset contract drift")
    raw_decision_glyph = bytes.fromhex("8c8892e8")
    residual_raw_decision_count = slps.count(raw_decision_glyph)
    if residual_raw_decision_count:
        raise SystemExit(
            "final SLPS still contains raw 決定 glyph codes: "
            f"{residual_raw_decision_count}"
        )
    male_profile = remaining_document["compdata_direct_by_offset"].get(
        "0x7FD20"
    )
    expected_profile = (
        "与同伴在荒野当修理店老板的男人。\n"
        "自称“烈焰”，豪爽而有血性。\n"
        "但有时会冲得太猛。"
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

    special_config = component_config["special_abilities"]
    special_document = json.loads(
        (PROJECT_ROOT / special_config["corpus"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    special_entries = special_document.get("entries")
    special_expected = special_config.get("expected")
    if (
        special_document.get("batch_id") != "v1-menu-system-ui"
        or special_document.get("scope", {}).get("section")
        != "Special Abilities"
        or not isinstance(special_entries, list)
        or not isinstance(special_expected, dict)
        or len(special_entries) != special_expected.get("entry_count")
    ):
        raise SystemExit("special-ability corpus contract drift")
    special_target_occurrence_count = 0
    special_targets = set()
    special_translated_entry_count = 0
    special_preserved_entry_count = 0
    special_raw_visible_ascii_glyph_count = 0
    special_raw_visible_ascii_target_count = 0
    special_raw_space_target_count = 0
    vps_readback = None
    for ordinal, item in enumerate(special_entries):
        entry_id = f"menu/Compdata/04/{ordinal:04d}"
        source_entry = original_menu_by_id.get(entry_id)
        if (
            not isinstance(item, dict)
            or item.get("id") != entry_id
            or source_entry is None
            or source_entry.section != "Special Abilities"
            or sha256_bytes(source_entry.text.encode("utf-8"))
            != item.get("source_text_sha256")
        ):
            raise SystemExit(f"special-ability source drift: {entry_id}")
        action = item.get("translation_action", "translate")
        if action == "preserve":
            if (
                item.get("editorial_status") != "final"
                or item.get("translation") != source_entry.text
            ):
                raise SystemExit(
                    f"special-ability preserve decision drift: {entry_id}"
                )
            expected_text = source_entry.text
            special_preserved_entry_count += 1
        else:
            if (
                action != "translate"
                or item.get("editorial_status") != "reviewed"
                or not isinstance(item.get("translation"), str)
                or not item["translation"]
            ):
                raise SystemExit(
                    f"special-ability translation decision drift: {entry_id}"
                )
            expected_text = normalize_original_fullwidth_ascii(
                item["translation"]
            ).replace(" ", "　")
            special_translated_entry_count += 1
        special_target_occurrence_count += len(source_entry.target_offsets)
        for target_offset in source_entry.target_offsets:
            special_targets.add(target_offset)
            actual = decode_text(
                decoded_compdata.output,
                target_offset,
                output_table,
            )
            if normalize_original_fullwidth_ascii(actual.text) != expected_text:
                raise SystemExit(
                    f"special-ability mismatch: {entry_id} at "
                    f"0x{target_offset:X}: expected={expected_text!r} "
                    f"actual={actual.text!r}"
                )
            payload = decoded_compdata.output[
                target_offset : target_offset + actual.consumed
            ]
            raw_ascii = raw_visible_ascii_glyphs(payload)
            special_raw_visible_ascii_glyph_count += len(raw_ascii)
            special_raw_visible_ascii_target_count += bool(raw_ascii)
            special_raw_space_target_count += b"\x20" in payload
            if entry_id == "menu/Compdata/04/0035":
                prefix = decoded_compdata.output[
                    target_offset : target_offset + 6
                ]
                vps_readback = {
                    "entry_id": entry_id,
                    "target_offset": target_offset,
                    "translation": "VPS装甲",
                    "readback": normalize_original_fullwidth_ascii(actual.text),
                    "stored_prefix_hex": prefix.hex(),
                    "two_byte_latin_storage": prefix.hex()
                    == "8275826f8272",
                }
    if (
        special_target_occurrence_count
        != special_expected.get("target_occurrence_count")
        or len(special_targets) != special_expected.get("unique_target_count")
        or special_translated_entry_count
        != special_expected.get("translated_entry_count")
        or special_preserved_entry_count
        != special_expected.get("preserved_structure_entry_count")
        or special_raw_visible_ascii_glyph_count
        or special_raw_visible_ascii_target_count
        or special_raw_space_target_count
        or vps_readback is None
        or not vps_readback["two_byte_latin_storage"]
    ):
        raise SystemExit("special-ability final-ISO readback failed")
    special_ability_report = {
        "corpus_entry_count": len(special_entries),
        "translated_entry_count": special_translated_entry_count,
        "preserved_structure_entry_count": special_preserved_entry_count,
        "target_occurrence_count": special_target_occurrence_count,
        "unique_target_count": len(special_targets),
        "source_preimages_sha256_exact": True,
        "target_offset_readback_exact": True,
        "raw_visible_ascii_glyph_count": 0,
        "raw_visible_ascii_target_count": 0,
        "raw_space_target_count": 0,
        "vps_armor": vps_readback,
    }

    battle_config = component_config["compdata_battle_lines"]
    battle_document = json.loads(
        (PROJECT_ROOT / battle_config["corpus"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    battle_entries = battle_document.get("entries")
    battle_expected = battle_config.get("expected")
    if (
        battle_document.get("batch_id") != "v1-menu-battle-lines"
        or not isinstance(battle_entries, list)
        or not isinstance(battle_expected, dict)
        or len(battle_entries) != battle_expected.get("entry_count")
    ):
        raise SystemExit("COMPDATA battle-line corpus contract drift")
    battle_target_occurrence_count = 0
    battle_unique_targets = set()
    battle_examples = {}
    for ordinal, item in enumerate(battle_entries):
        entry_id = f"menu/Compdata/00/{ordinal:04d}"
        source_entry = original_menu_by_id.get(entry_id)
        if (
            item.get("id") != entry_id
            or source_entry is None
            or source_entry.section != "Battle Lines"
            or sha256_bytes(source_entry.text.encode("utf-8"))
            != item.get("source_text_sha256")
        ):
            raise SystemExit(f"COMPDATA battle-line source drift: {entry_id}")
        expected_text = normalize_original_fullwidth_ascii(
            item["translation"]
        ).replace(" ", "　")
        battle_target_occurrence_count += len(source_entry.target_offsets)
        for target_offset in source_entry.target_offsets:
            battle_unique_targets.add(target_offset)
            actual = normalize_original_fullwidth_ascii(
                decode_text(
                    decoded_compdata.output,
                    target_offset,
                    output_table,
                ).text
            )
            if actual != expected_text:
                raise SystemExit(
                    f"COMPDATA battle-line mismatch: {entry_id} at "
                    f"0x{target_offset:X}: expected={expected_text!r} "
                    f"actual={actual!r}"
                )
        if ordinal in {216, 217}:
            battle_examples[entry_id] = {
                "target_offsets": [
                    f"0x{offset:X}" for offset in source_entry.target_offsets
                ],
                "translation": expected_text,
            }
    if (
        battle_target_occurrence_count
        != battle_expected.get("target_occurrence_count")
        or len(battle_unique_targets)
        != battle_expected.get("unique_target_count")
    ):
        raise SystemExit("COMPDATA battle-line target inventory drift")
    battle_line_report = {
        "corpus_entry_count": len(battle_entries),
        "target_occurrence_count": battle_target_occurrence_count,
        "unique_target_count": len(battle_unique_targets),
        "source_preimages_sha256_exact": True,
        "target_offset_readback_exact": True,
        "examples": battle_examples,
    }

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
        if actual_entry.text.replace("\u3000", " ") != expected_part.replace(
            "\u3000", " "
        ):
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

    unit_ascii_expectations = {
        "display-name/unit/0089/name": {
            "text": "钢铁齿轮（LS）",
            "token": "LS",
            "stored_hex": "826b8272",
        },
        "display-name/unit/0090/name": {
            "text": "钢铁齿轮（WM）",
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
        "unit_names": {
            "corpus_batch_id": unit_corpus_report["batch_id"],
            "entry_count": len(unit_decisions),
            "two_byte_space_code": f"{unit_space_code:04x}",
            "two_byte_space_entry_count": len(unit_two_byte_space_ids),
            "two_byte_space_entry_ids": unit_two_byte_space_ids,
            "raw_single_byte_space_count": 0,
            "two_byte_spaces_exact": True,
            "relocated_entry_count": len(unit_relocations),
            "relocated_entry_ids": list(unit_relocations),
            "relocated_pointer_count": relocated_pointer_count,
            "pointer_relocations_exact": True,
            "readback_exact": True,
            "examples": unit_examples,
        },
        "button_prompts": button_prompts,
        "button_prompts_exact": True,
        "unit_ascii_storage_examples": unit_ascii_storage_examples,
        "unit_ascii_storage_examples_exact": True,
        "visible_space_storage": {
            "display_name_raw_space_entry_count": (
                display_name_raw_space_count
            ),
            "compdata_menu_raw_space_target_count": (
                compdata_menu_raw_space_count
            ),
            "slps_menu_raw_space_target_count": slps_menu_raw_space_count,
            "raw_space_count_zero": True,
        },
        "surface_safe_alias_count": len(surface_aliases),
        "surface_safe_aliases_readback_exact": True,
        "remaining_ui": {
            "compdata_direct": direct_report,
            "compdata_library_work_titles": library_work_title_report,
            "compdata_context_help": context_help_report,
            "compdata_inline": inline_report,
            "leadership_effects": leadership_report,
            "slps_context_ui": slps_context_report,
            "slps": slps_report,
            "parts": parts_report,
            "readback_exact": True,
        },
        "battle_lines": battle_line_report,
        "special_abilities": special_ability_report,
        "ability_visible_ascii_audit": ability_visible_ascii_report,
        "formation_regressions": {
            "map_name_offsets": map_formation_name_expectations,
            "map_names_readback_exact": True,
            "squad_name_offsets": squad_formation_name_expectations,
            "squad_names_readback_exact": True,
        },
        "library_regressions": {
            "runtime_text_offsets": library_runtime_text_expectations,
            "runtime_text_readback_exact": True,
            "confirm_prompt_offsets": confirm_prompt_expectations,
            "confirm_prompts_readback_exact": True,
            "residual_raw_decision_glyph_count": (
                residual_raw_decision_count
            ),
            "raw_decision_glyph_absent": True,
        },
        "new_game_regressions": {
            "male_default_name_offsets": new_game_name_expectations,
            "male_default_name_readback_exact": True,
            "male_default_unit_name_offsets": (
                male_default_unit_name_expectations
            ),
            "male_default_unit_name_readback_exact": True,
            "female_default_name_offsets": female_default_name_expectations,
            "female_default_name_readback_exact": True,
            "female_default_unit_name_offsets": (
                female_default_unit_name_expectations
            ),
            "female_default_unit_name_readback_exact": True,
            "formation_action_label_offsets": (
                formation_action_label_expectations
            ),
            "formation_action_labels_readback_exact": True,
            "spirit_acronym_offsets": spirit_acronym_expectations,
            "spirit_acronyms_readback_exact": True,
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


def verify_post_release_runtime_surfaces(
    *,
    slps: bytes,
    mtv_prop: bytes,
    stage: bytes,
    hb: bytes,
    source_table: TextTable,
    output_table: TextTable,
    component: dict,
) -> dict:
    """Reread the five post-release data surfaces from final ISO bytes."""

    component_config = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )
    remaining = component_config["remaining_ui"]
    remaining_document = json.loads(
        (PROJECT_ROOT / remaining["translations"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    original_slps = (
        PROJECT_ROOT / remaining["original_slps"]["path"]
    ).read_bytes()
    expected_auto_roots = {
        0x31B610: "帝皇比亚路",
        0x31B624: "阿伽玛",
        0x31B638: "钢铁齿轮",
        0x31B64C: "钢铁齿轮",
        0x31B660: "格罗玛",
        0x31B674: "和平号",
        0x31B688: "月光号",
        0x31B69C: "大天使",
        0x31B6B0: "密涅瓦",
        0x31B6C4: "太阳号",
        0x31B6D8: "永恒",
        0x31B6EC: "永恒",
        0x31B700: "拉迪修",
    }
    auto_root_readbacks = {}
    for offset, translation in expected_auto_roots.items():
        raw_offset = f"0x{offset:X}"
        source = decode_text(original_slps, offset, source_table)
        actual = decode_text(slps, offset, output_table, end=offset + source.consumed)
        if (
            remaining_document["slps_by_offset"].get(raw_offset)
            != translation
            or actual.text != translation
            or actual.consumed > source.consumed
        ):
            raise SystemExit(
                f"final ISO auto-squad root mismatch at {raw_offset}"
            )
        auto_root_readbacks[raw_offset] = translation

    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member="HEDBDY/HB.BIN",
        table_start=30320,
        table_end=31144,
    )
    stage_offsets = read_executable_archive_offsets(hb, offset_spec, len(stage))

    def decoded_stage(index: int) -> bytes:
        stored = stage[stage_offsets[index] : stage_offsets[index + 1]]
        result = decode(stored)
        if any(stored[result.consumed :]):
            raise SystemExit(f"final ISO STAGE {index} has nonzero padding")
        return result.output

    z_report_expected = {
        33: {0x5BA0: "武装“米加火箭发射器”已追加"},
        36: {
            0xDD50: "莎拉队获得PP+50",
            0xDD70: "阿蒂特队获得PP+50",
        },
        66: {0x1BF40: "武装“金刚飞艇”已追加"},
        119: {0x25A80: "武装“G比特”已追加"},
        127: {0x2B1D0: "武装“G比特”已追加"},
    }
    z_report_readbacks = {}
    for stage_index, expected_by_offset in z_report_expected.items():
        z_report_stage = decoded_stage(stage_index)
        for offset, translation in expected_by_offset.items():
            actual = decode_text(
                z_report_stage,
                offset,
                output_table,
                end=offset + 64,
            )
            raw = z_report_stage[offset : offset + actual.consumed]
            if (
                actual.text != translation
                or (stage_index == 36 and b"PP+50" in raw)
            ):
                raise SystemExit(
                    "final ISO Z Report mismatch at "
                    f"stage={stage_index} offset=0x{offset:X}"
                )
            z_report_readbacks[
                f"stage-{stage_index:03d}/0x{offset:X}"
            ] = translation

    ticker_targets = (
        (
            28,
            0xC3E4,
            "埃曼特色商品齐全，唐吉的面包也有出售。",
            0x00762130,
        ),
        (
            33,
            0x2CE4,
            "西伯铁大市场，为旅客大放送超值商品。",
            0x007589C0,
        ),
        (39, 0x3B64, "西伯铁大市场，为旅客大放送超值商品。", 0),
        (43, 0x99E4, "庆祝大逃亡成功！全场大优惠！！", 0x0075F6D0),
        (66, 0xC194, "战区救援市场，物资短缺，欢迎出售。", 0x007620F0),
        (
            112,
            0xCC74,
            "应对各种状况！超级补修套件出售中！",
            0x00762740,
        ),
        (
            119,
            0xF314,
            "宇宙作战必需品喷射模组！热卖中！",
            0x00764EC0,
        ),
        (
            127,
            0x11994,
            "宇宙作战必需品喷射模组！热卖中！",
            0x00767410,
        ),
        (128, 0xD014, "冲向战场！强化推进器大放送！", 0x00762AE0),
        (
            155,
            0x1234,
            "埃曼特色商品齐全，唐吉的面包也有出售。",
            0,
        ),
        (
            156,
            0x1294,
            "埃曼特色商品齐全，唐吉的面包也有出售。",
            0,
        ),
    )
    ticker_readbacks = {}
    for stage_index, offset, translation, prefix_word in ticker_targets:
        stage_data = decoded_stage(stage_index)
        actual = decode_text(
            stage_data,
            offset,
            output_table,
            end=offset + 140,
        )
        actual_prefix_word = int.from_bytes(
            stage_data[offset - 4 : offset], byteorder="little"
        )
        if (
            actual.text != translation
            or stage_data[offset - 10 : offset - 4] != b"\xFF" * 6
            or actual_prefix_word != prefix_word
        ):
            raise SystemExit(
                f"final ISO ISSUE-020 ticker mismatch in STAGE {stage_index}"
            )
        ticker_readbacks[str(stage_index)] = {
            "decoded_offset": offset,
            "translation": actual.text,
            "prefix_kind": "zero" if prefix_word == 0 else "runtime_pointer",
            "prefix_word": f"0x{prefix_word:08X}",
        }

    tutorial_headers = {}
    for stage_index, expected_name in ((185, "stg_500.bin"), (186, "stg_501.bin")):
        data = decoded_stage(stage_index)
        name = data[0x30:0x50].split(b"\0", 1)[0].decode("ascii")
        if name != expected_name:
            raise SystemExit(
                f"final ISO tutorial binding drift in STAGE {stage_index}"
            )
        tutorial_headers[str(stage_index)] = name
    tutorial_component = component.get("story", {}).get("tutorial_binding")
    if tutorial_component != {
        "stage_names": tutorial_headers,
        "dialogue_counts": {"185": 407, "186": 431},
        "total_dialogue_count": 838,
        "source_stage_headers_exact": True,
        "translated_stage_reread_exact": True,
        "alternate_mtv_prop_text_owner_ruled_out": True,
    }:
        raise SystemExit("final ISO tutorial component binding drift")

    intertitle_component = component.get("chapter_intertitles")
    if not isinstance(intertitle_component, dict):
        raise SystemExit("final ISO chapter-intertitle receipt is missing")
    table_start = 0x32BB70
    table_end = 0x32BBD0
    mtv_offsets = struct.unpack_from(
        f"<{(table_end - table_start) // 4}I",
        slps,
        table_start,
    )
    if (
        len(mtv_offsets) != 24
        or mtv_offsets[0] != 0
        or mtv_offsets[-1] != len(mtv_prop)
    ):
        raise SystemExit("final ISO MTV_PROP offset table drift")
    intertitle_readbacks = []
    receipt_entries = {
        item["chunk_index"]: item
        for item in intertitle_component.get("entries", [])
    }
    for chunk_index in (21, 22):
        stored = mtv_prop[
            mtv_offsets[chunk_index] : mtv_offsets[chunk_index + 1]
        ]
        decoded = decode(stored)
        records = scan_tim2(decoded.output)
        if len(records) != 1 or len(records[0].pictures) != 1:
            raise SystemExit(
                f"final ISO intertitle TIM2 drift in chunk {chunk_index}"
            )
        picture = records[0].pictures[0]
        image_start = picture.offset + picture.header_size
        image_end = image_start + picture.image_size
        linear = decoded.output[image_start:image_end]
        receipt = receipt_entries.get(chunk_index)
        if (
            not isinstance(receipt, dict)
            or receipt.get("storage_layout")
            != "linear_row_major_despite_psmt8_header"
            or sha256_bytes(linear)
            != receipt.get("output_linear_indexes_sha256")
            or any(stored[decoded.consumed :])
        ):
            raise SystemExit(
                f"final ISO intertitle index readback drift in chunk {chunk_index}"
            )
        intertitle_readbacks.append(
            {
                "chunk_index": chunk_index,
                "translation": receipt["translation"],
                "storage_layout": receipt["storage_layout"],
                "output_linear_indexes_sha256": sha256_bytes(linear),
            }
        )

    return {
        "issue_011_chapter_intertitles": {
            "member": "DATA/MTV_PROP.BIN",
            "chunk_count": 23,
            "localized_chunks": intertitle_readbacks,
            "all_other_chunks_preserved_by_component_receipt": True,
            "indexed_pixels_reread_exact": True,
        },
        "issue_016_tutorial_binding": {
            "stage_headers": tutorial_headers,
            "dialogue_counts": tutorial_component["dialogue_counts"],
            "total_dialogue_count": 838,
            "translated_reread_exact": True,
        },
        "issue_020_bazaar_ticker": {
            "stage_readbacks": ticker_readbacks,
            "unique_translation_count": len(
                {
                    translation
                    for _stage, _offset, translation, _prefix_word in ticker_targets
                }
            ),
            "reported_siberian_slot": {
                "stage_index": 39,
                "decoded_offset": 0x3B64,
                "translation": ticker_targets[2][2],
            },
            "pointer_siberian_slot": {
                "stage_index": 33,
                "decoded_offset": 0x2CE4,
                "translation": ticker_targets[1][2],
            },
            "reported_exodus_slot": {
                "stage_index": 43,
                "decoded_offset": 0x99E4,
                "translation": ticker_targets[3][2],
            },
            "runtime_pointer_slot_count": sum(
                prefix_word != 0
                for _stage, _offset, _translation, prefix_word in ticker_targets
            ),
            "translated_reread_exact": True,
        },
        "issue_022_auto_squad_names": {
            "root_count": len(auto_root_readbacks),
            "root_offsets": auto_root_readbacks,
            "runtime_suffix": "队",
            "old_savedata_names_untouched": True,
            "translated_reread_exact": True,
        },
        "issue_026_z_report": {
            "stage_index": 36,
            "reward_readbacks": {
                key: value
                for key, value in z_report_readbacks.items()
                if key.startswith("stage-036/")
            },
            "raw_single_byte_pp50_absent": True,
            "translated_reread_exact": True,
        },
        "v030_028_z_report_weapon_additions": {
            "source_count": 3,
            "target_count": 4,
            "stage_indices": [33, 66, 119, 127],
            "weapon_readbacks": {
                key: value
                for key, value in z_report_readbacks.items()
                if not key.startswith("stage-036/")
            },
            "translated_reread_exact": True,
        },
        "z_report_structural_coverage": {
            "source_count": 5,
            "target_count": 6,
            "stage_indices": [33, 36, 66, 119, 127],
            "readbacks": z_report_readbacks,
            "translated_reread_exact": True,
        },
    }


def verify_issue_036_tutorial(
    *,
    slps: bytes,
    nisvdata: bytes,
    veff: bytes,
    stage: bytes,
    hb: bytes,
    source_table: TextTable,
    output_table: TextTable,
    component: dict,
) -> dict:
    """Reread tutorial headings, body records, and title effects from ISO bytes."""

    config = json.loads(FULL_COMPONENT_CONFIG.read_text(encoding="utf-8"))
    remaining_path = PROJECT_ROOT / config["remaining_ui"]["translations"]["path"]
    remaining = json.loads(remaining_path.read_text(encoding="utf-8"))
    source_slps = (
        PROJECT_ROOT / config["remaining_ui"]["original_slps"]["path"]
    ).read_bytes()
    title_offsets = (
        0x347B40,
        0x347B60,
        0x347B80,
        0x347BA0,
        0x347BD0,
        0x347C00,
        0x347C30,
        0x347C60,
        0x347C80,
        0x347CA0,
    )
    title_readbacks = []
    for offset in title_offsets:
        key = f"0x{offset:X}"
        source = decode_text(source_slps, offset, source_table)
        actual = decode_text(slps, offset, output_table, end=offset + source.consumed)
        expected = remaining["slps_by_offset"].get(key)
        if actual.text != expected or actual.consumed > source.consumed:
            raise SystemExit(f"final ISO tutorial page-title mismatch at {key}")
        title_readbacks.append(
            {
                "offset": key,
                "translation": actual.text,
                "source_allocation_size": source.consumed,
            }
        )

    body_contract = config["nisv_tutorial_pages"]
    corpus_path = PROJECT_ROOT / body_contract["corpus"]["path"]
    corpus_data = corpus_path.read_bytes()
    if (
        len(corpus_data) != body_contract["corpus"]["size"]
        or sha256_bytes(corpus_data) != body_contract["corpus"]["sha256"]
    ):
        raise SystemExit("final ISO tutorial body corpus lock drift")
    corpus = json.loads(corpus_data.decode("utf-8"))
    archive = body_contract["archive"]
    nisv_offsets = read_executable_archive_offsets(
        slps,
        ExecutableOffsetSpec(
            name=archive["name"],
            member=archive["member"],
            table_start=int(archive["table_start"], 0),
            table_end=int(archive["table_end"], 0),
        ),
        len(nisvdata),
    )
    chunk_index = body_contract["target"]["chunk_index"]
    stored = nisvdata[nisv_offsets[chunk_index] : nisv_offsets[chunk_index + 1]]
    decoded = decode(stored)
    if any(stored[decoded.consumed :]):
        raise SystemExit("final ISO tutorial body compressed padding is nonzero")
    pages = parse_nisv_tutorial_pages(decoded.output)
    body_readbacks = []
    record_count = 0
    for page, corpus_page in zip(pages, corpus["pages"]):
        translations = []
        for record, corpus_record in zip(page["records"], corpus_page["records"]):
            actual = decode_text(record["raw"] + b"\0", 0, output_table)
            if actual.text != corpus_record["translation"]:
                raise SystemExit(
                    f"final ISO tutorial body mismatch: page={corpus_page['page']}"
                )
            translations.append(actual.text)
            record_count += 1
        body_readbacks.append(
            {
                "page": corpus_page["page"],
                "record_count": len(translations),
                "translations": translations,
            }
        )
    if len(pages) != 10 or record_count != 114:
        raise SystemExit("final ISO tutorial body inventory drift")

    effect_contract = config["tutorial_title_effects"]
    effect_component = component.get("tutorial_title_effects")
    if not isinstance(effect_component, dict):
        raise SystemExit("final ISO tutorial title-effect receipt is missing")
    event_binding = audit_tutorial_effect_binding(
        stage, hb, effect_contract["event_binding"]
    )
    if event_binding != effect_component.get("event_binding"):
        raise SystemExit("final ISO tutorial effect event-binding receipt drift")
    effect_archive = effect_contract["archive"]
    veff_offsets = read_executable_archive_offsets(
        slps,
        ExecutableOffsetSpec(
            name=effect_archive["name"],
            member=effect_archive["member"],
            table_start=int(effect_archive["table_start"], 0),
            table_end=int(effect_archive["table_end"], 0),
        ),
        len(veff),
    )
    target_receipts = {
        item["chunk_index"]: item for item in effect_component.get("targets", [])
    }
    effect_readbacks = []
    for target in effect_contract["targets"]:
        chunk_index = target["chunk_index"]
        stored = veff[veff_offsets[chunk_index] : veff_offsets[chunk_index + 1]]
        decoded = decode(stored)
        records = scan_tim2(decoded.output)
        record = records[effect_contract["record_index"]]
        background_record = records[effect_contract["background_record_index"]]
        receipt = target_receipts.get(chunk_index)
        if not isinstance(receipt, dict) or any(stored[decoded.consumed :]):
            raise SystemExit(
                f"final ISO tutorial VEFF receipt drift: chunk={chunk_index}"
            )
        picture_receipts = {
            item["picture_index"]: item for item in receipt.get("pictures", [])
        }
        background_picture_receipts = {
            item["picture_index"]: item
            for item in receipt.get("background_pictures", [])
        }
        picture_readbacks = []
        for picture_index, picture in enumerate(record.pictures):
            image_start = picture.offset + picture.header_size
            image_end = image_start + picture.image_size
            logical = unswizzle_psmt8(
                decoded.output[image_start:image_end], picture.width, picture.height
            )
            picture_receipt = picture_receipts.get(picture_index)
            if (
                not isinstance(picture_receipt, dict)
                or sha256_bytes(logical)
                != picture_receipt.get("output_logical_sha256")
            ):
                raise SystemExit(
                    "final ISO tutorial title picture mismatch: "
                    f"chunk={chunk_index} picture={picture_index}"
                )
            picture_readbacks.append(
                {
                    "picture_index": picture_index,
                    "translation": picture_receipt["translation"],
                    "output_logical_sha256": sha256_bytes(logical),
                }
            )
        if len(picture_readbacks) != 4:
            raise SystemExit("final ISO tutorial title picture-count drift")
        background_picture_readbacks = []
        for picture_index, picture in enumerate(background_record.pictures):
            image_start = picture.offset + picture.header_size
            image_end = image_start + picture.image_size
            logical = unswizzle_psmt4(
                decoded.output[image_start:image_end],
                picture.width,
                picture.height,
            )
            picture_receipt = background_picture_receipts.get(picture_index)
            if (
                not isinstance(picture_receipt, dict)
                or sha256_bytes(logical)
                != picture_receipt.get("output_logical_sha256")
            ):
                raise SystemExit(
                    "final ISO tutorial background picture mismatch: "
                    f"chunk={chunk_index} picture={picture_index}"
                )
            background_picture_readbacks.append(
                {
                    "picture_index": picture_index,
                    "output_logical_sha256": sha256_bytes(logical),
                }
            )
        if len(background_picture_readbacks) != 4:
            raise SystemExit(
                "final ISO tutorial background picture-count drift"
            )
        effect_readbacks.append(
            {
                "effect_id": target["effect_id"],
                "chunk_index": chunk_index,
                "pictures": picture_readbacks,
                "background_pictures": background_picture_readbacks,
            }
        )
    if len(effect_readbacks) != 4:
        raise SystemExit("final ISO tutorial title effect-count drift")
    return {
        "slps_page_titles": title_readbacks,
        "page_title_count": len(title_readbacks),
        "nisv_body_pages": body_readbacks,
        "body_page_count": len(body_readbacks),
        "body_record_count": record_count,
        "event_binding": event_binding,
        "title_effects": effect_readbacks,
        "title_effect_count": len(effect_readbacks),
        "title_picture_count": sum(
            len(item["pictures"]) for item in effect_readbacks
        ),
        "background_title_picture_count": sum(
            len(item["background_pictures"]) for item in effect_readbacks
        ),
        "translated_reread_exact": True,
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
    component_report_path = args.component_report
    if component_report_path is None:
        component_report_path = (
            Path(component_manifest_path)
            if component_manifest_path
            else COMPONENT_REPORT
        )
    component = json.loads(
        project_path(component_report_path).read_text(encoding="utf-8")
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

    library_members = {
        "DATA/JTIM.BIN",
        "DATA/MTVZKNRT.BIN",
        "DATA/MTVZKNPT.BIN",
        "DATA/MTVZKNKW.BIN",
    }
    library_component = component.get("library")
    library_translation = (
        library_component.get("translation", {})
        if isinstance(library_component, dict)
        else {}
    )
    library_acceptance = (
        library_component.get("acceptance", {})
        if isinstance(library_component, dict)
        else {}
    )
    library_menu = (
        library_component.get("library_menu", {})
        if isinstance(library_component, dict)
        else {}
    )
    legacy_jtim = (
        library_component.get("legacy_jtim_restoration", {})
        if isinstance(library_component, dict)
        else {}
    )
    if (
        not library_members <= set(members)
        or not isinstance(library_component, dict)
        or library_component.get("status")
        != "library_v0.2_reviewed_components_static_validated"
        or library_component.get("release_eligible") is not True
        or library_translation.get("unique_text_count") != 2709
        or library_translation.get("used_unique_text_count") != 2709
        or library_translation.get("field_reference_count") != 4921
        or not isinstance(library_menu, dict)
        or library_menu.get("all_six_labels_written") is not True
        or library_menu.get("tim2_metadata_preserved") is not True
        or not isinstance(legacy_jtim, dict)
        or legacy_jtim.get("restored_original_byte_exact") is not True
        or not library_acceptance
        or not all(library_acceptance.values())
    ):
        raise SystemExit("final ISO reviewed LIBRARY component proof is incomplete")

    jtim = members["DATA/JTIM.BIN"]
    if (
        len(jtim) != legacy_jtim.get("output_size")
        or sha256_bytes(jtim) != legacy_jtim.get("output_sha256")
        or legacy_jtim.get("source_sha256") != legacy_jtim.get("output_sha256")
    ):
        raise SystemExit("final ISO legacy JTIM restoration drift")

    library_scope = json.loads(
        (PROJECT_ROOT / "config/library/v0.2.0.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_contract = library_scope["library_menu_runtime_tim2"]
    runtime_target = runtime_contract["target"]
    nisvdata = members["DATA/NISVDATA.BIN"]
    stored_start = int(runtime_target["stored_start"])
    stored_end = int(runtime_target["stored_end"])
    stored_menu = nisvdata[stored_start:stored_end]
    decoded_menu = decode(stored_menu)
    if any(stored_menu[decoded_menu.consumed :]):
        raise SystemExit("final ISO runtime LIBRARY menu padding is nonzero")
    runtime_records = scan_tim2(decoded_menu.output)
    runtime_record_index = int(runtime_target["record_index"])
    if not 0 <= runtime_record_index < len(runtime_records):
        raise SystemExit("final ISO runtime LIBRARY menu record is missing")
    runtime_record = runtime_records[runtime_record_index]
    if len(runtime_record.pictures) != 1:
        raise SystemExit("final ISO runtime LIBRARY menu picture-count drift")
    runtime_picture = runtime_record.pictures[0]
    runtime_image_start = runtime_picture.offset + runtime_picture.header_size
    runtime_image_end = runtime_image_start + runtime_picture.image_size
    logical_menu = unswizzle_psmt8(
        decoded_menu.output[runtime_image_start:runtime_image_end],
        runtime_picture.width,
        runtime_picture.height,
    )
    if (
        runtime_record.offset != library_menu.get("record_offset")
        or sha256_bytes(
            decoded_menu.output[runtime_record.offset : runtime_record.end]
        )
        != library_menu.get("output_record_sha256")
        or sha256_bytes(logical_menu)
        != library_menu.get("output_logical_indexes_sha256")
    ):
        raise SystemExit("final ISO runtime LIBRARY menu readback drift")
    menu_label_reports = library_menu.get("labels")
    if not isinstance(menu_label_reports, list) or len(menu_label_reports) != 6:
        raise SystemExit("final ISO LIBRARY menu label proof is incomplete")
    menu_label_readbacks = []
    for label in menu_label_reports:
        if not isinstance(label, dict):
            raise SystemExit("final ISO LIBRARY menu label proof is malformed")
        x = int(label["x"])
        y = int(label["y"])
        width = int(label["width"])
        height = int(label["height"])
        crop = b"".join(
            logical_menu[
                (y + row) * runtime_picture.width + x :
                (y + row) * runtime_picture.width + x + width
            ]
            for row in range(height)
        )
        if (
            sha256_bytes(crop) != label.get("output_indexes_sha256")
            or not any(crop)
        ):
            raise SystemExit(
                "final ISO LIBRARY menu label readback drift: "
                f"{label.get('id')}"
            )
        menu_label_readbacks.append(
            {
                "id": label["id"],
                "translation": label["translation"],
                "output_indexes_sha256": label["output_indexes_sha256"],
                "visible_pixel_count": sum(value != 0 for value in crop),
                "readback_exact": True,
            }
        )
    library_menu_readback = {
        "member": "DATA/NISVDATA.BIN",
        "chunk_index": int(runtime_target["chunk_index"]),
        "record_index": runtime_record_index,
        "record_offset": runtime_record.offset,
        "record_size": runtime_record.size,
        "record_sha256": library_menu["output_record_sha256"],
        "label_variant_count": len(menu_label_readbacks),
        "unique_translation_count": len(
            {item["translation"] for item in menu_label_readbacks}
        ),
        "labels": menu_label_readbacks,
        "all_six_labels_written": True,
        "fixed_index_rectangles_reread_exact": True,
        "legacy_jtim_restored_original_byte_exact": True,
    }

    sound_select_component = library_menu.get("sound_select")
    sound_contract = library_scope["sound_select_runtime_tim2"]
    sound_target = sound_contract["target"]
    sound_writeback = sound_contract.get("writeback")
    sound_source_lock = library_scope.get("source_member_locks", {}).get(
        "DATA/NISVDATA.BIN"
    )
    if (
        not isinstance(sound_select_component, dict)
        or sound_select_component.get("sound_select_title_written") is not True
        or sound_select_component.get("alpha_mask_preserved") is not True
        or not isinstance(sound_writeback, dict)
        or not isinstance(sound_source_lock, dict)
    ):
        raise SystemExit("final ISO sound-select component proof is incomplete")
    source_nisvdata_path = project_path(Path(sound_source_lock.get("path", "")))
    source_nisvdata = source_nisvdata_path.read_bytes()
    if (
        len(source_nisvdata) != sound_source_lock.get("size")
        or sha256_bytes(source_nisvdata) != sound_source_lock.get("sha256")
    ):
        raise SystemExit("source sound-select NISVDATA member drift")
    sound_stored_start = int(sound_target["stored_start"])
    sound_stored_end = int(sound_target["stored_end"])
    original_sound_stored = source_nisvdata[
        sound_stored_start:sound_stored_end
    ]
    final_sound_stored = nisvdata[sound_stored_start:sound_stored_end]
    if (
        len(original_sound_stored) != sound_target.get("stored_size")
        or sha256_bytes(original_sound_stored)
        != sound_target.get("stored_sha256")
    ):
        raise SystemExit("final ISO sound-select source contract drift")
    original_sound_decoded = decode(original_sound_stored)
    final_sound_decoded = decode(final_sound_stored)
    if (
        original_sound_decoded.consumed
        != sound_target.get("stored_consumed")
        or len(original_sound_decoded.output) != sound_target.get("decoded_size")
        or sha256_bytes(original_sound_decoded.output)
        != sound_target.get("decoded_sha256")
        or any(original_sound_stored[original_sound_decoded.consumed:])
        or any(final_sound_stored[final_sound_decoded.consumed:])
        or final_sound_decoded.consumed
        != sound_select_component.get("output_encoded_size")
    ):
        raise SystemExit("final ISO sound-select chunk decode drift")
    original_sound_records = scan_tim2(original_sound_decoded.output)
    final_sound_records = scan_tim2(final_sound_decoded.output)
    sound_record_index = int(sound_target["record_index"])
    if (
        not 0 <= sound_record_index < len(original_sound_records)
        or len(original_sound_records) != len(final_sound_records)
    ):
        raise SystemExit("final ISO sound-select TIM2 record is missing")
    original_sound_record = original_sound_records[sound_record_index]
    sound_record = final_sound_records[sound_record_index]
    if (
        original_sound_record.offset != sound_target.get("record_offset")
        or original_sound_record.size != sound_target.get("record_size")
        or original_sound_record != sound_record
        or sha256_bytes(
            original_sound_decoded.output[
                original_sound_record.offset:original_sound_record.end
            ]
        )
        != sound_target.get("record_sha256")
        or len(original_sound_record.pictures) != 1
    ):
        raise SystemExit("final ISO sound-select TIM2 metadata drift")
    sound_picture = original_sound_record.pictures[0]
    sound_image_start = sound_picture.offset + sound_picture.header_size
    sound_image_end = sound_image_start + sound_picture.image_size
    sound_palette_end = sound_image_end + sound_picture.clut_size
    original_logical_sound = unswizzle_psmt8(
        original_sound_decoded.output[sound_image_start:sound_image_end],
        sound_picture.width,
        sound_picture.height,
    )
    logical_sound = unswizzle_psmt8(
        final_sound_decoded.output[sound_image_start:sound_image_end],
        sound_picture.width,
        sound_picture.height,
    )
    original_sound_palette = original_sound_decoded.output[
        sound_image_end:sound_palette_end
    ]
    final_sound_palette = final_sound_decoded.output[
        sound_image_end:sound_palette_end
    ]
    sound_labels = sound_select_component.get("labels")
    if (
        sound_target.get("storage_layout") != "gs_psmt8"
        or sound_picture.width != sound_target.get("width")
        or sound_picture.height != sound_target.get("height")
        or sound_picture.image_type != sound_target.get("image_type")
        or sound_picture.image_size
        != sound_picture.width * sound_picture.height
        or sound_picture.clut_size != 256 * 4
        or sha256_bytes(original_logical_sound)
        != sound_target.get("logical_indexes_sha256")
        or sound_record.offset != sound_select_component.get("record_offset")
        or sha256_bytes(
            final_sound_decoded.output[sound_record.offset:sound_record.end]
        )
        != sound_select_component.get("output_record_sha256")
        or sha256_bytes(logical_sound)
        != sound_select_component.get("output_logical_indexes_sha256")
        or original_sound_palette != final_sound_palette
        or (
            original_sound_decoded.output[:sound_image_start]
            + original_sound_decoded.output[sound_image_end:]
        )
        != (
            final_sound_decoded.output[:sound_image_start]
            + final_sound_decoded.output[sound_image_end:]
        )
        or not isinstance(sound_labels, list)
        or len(sound_labels) != 1
    ):
        raise SystemExit("final ISO sound-select texture readback drift")

    original_sound_alpha = indexed_alpha_plane(
        original_logical_sound,
        original_sound_palette,
    )
    final_sound_alpha = indexed_alpha_plane(
        logical_sound,
        final_sound_palette,
    )
    if (
        sha256_bytes(original_sound_alpha)
        != sound_target.get("source_alpha_plane_sha256")
        or original_sound_alpha != final_sound_alpha
        or sha256_bytes(original_sound_alpha)
        != sound_select_component.get("source_alpha_plane_sha256")
        or sha256_bytes(final_sound_alpha)
        != sound_select_component.get("output_alpha_plane_sha256")
        or original_sound_alpha.count(0)
        != sound_select_component.get("source_transparent_pixel_count")
        or final_sound_alpha.count(0)
        != sound_select_component.get("output_transparent_pixel_count")
    ):
        raise SystemExit("final ISO sound-select alpha mask drift")

    sound_masks = sound_writeback.get("masks")
    if not isinstance(sound_masks, list) or len(sound_masks) != 1:
        raise SystemExit("final ISO sound-select title selection drift")
    sound_mask = sound_masks[0]
    sound_label = sound_labels[0]
    sound_restore = sound_mask.get("background_restore")
    if not isinstance(sound_restore, dict):
        raise SystemExit("final ISO sound-select background restore is missing")
    sound_restore_x = int(sound_restore.get("x", -1))
    sound_restore_y = int(sound_restore.get("y", -1))
    sound_restore_width = int(sound_restore.get("width", -1))
    sound_restore_rows = sound_restore.get("row_indexes")
    sound_source_index_start = sound_restore.get("source_index_start")
    sound_source_index_stop = sound_restore.get("source_index_stop")
    sound_source_dilation_radius = sound_restore.get(
        "source_dilation_radius"
    )
    if (
        not isinstance(sound_restore_rows, list)
        or not sound_restore_rows
        or (sound_restore_x, sound_restore_y, sound_restore_width)
        != (14, 3, 193)
        or sound_restore_rows != [5, 3] + [2] * 28 + [3]
        or sound_source_index_start != 14
        or sound_source_index_stop != 31
        or sound_source_dilation_radius != 1
        or sound_restore_x + sound_restore_width > sound_picture.width
        or sound_restore_y + len(sound_restore_rows) > sound_picture.height
    ):
        raise SystemExit("final ISO sound-select background geometry drift")
    sound_restore_offsets = {
        row * sound_picture.width + column
        for row in range(
            sound_restore_y,
            sound_restore_y + len(sound_restore_rows),
        )
        for column in range(
            sound_restore_x,
            sound_restore_x + sound_restore_width,
        )
    }
    if any(
        source_index != final_index
        for offset, (source_index, final_index) in enumerate(
            zip(original_logical_sound, logical_sound)
        )
        if offset not in sound_restore_offsets
    ):
        raise SystemExit("final ISO sound-select changed outside title interior")
    source_sound_restore_crop = b"".join(
        original_logical_sound[
            (sound_restore_y + row) * sound_picture.width + sound_restore_x:
            (sound_restore_y + row) * sound_picture.width
            + sound_restore_x
            + sound_restore_width
        ]
        for row in range(len(sound_restore_rows))
    )
    if (
        sha256_bytes(source_sound_restore_crop)
        != sound_mask.get("source_indexes_sha256")
        or indexed_alpha_plane(
            source_sound_restore_crop,
            original_sound_palette,
        ).count(0)
        != 0
    ):
        raise SystemExit(
            "final ISO sound-select restore rectangle crosses transparency"
        )
    sound_source_title_offsets = {
        row * sound_picture.width + column
        for row in range(
            sound_restore_y,
            sound_restore_y + len(sound_restore_rows),
        )
        for column in range(
            sound_restore_x,
            sound_restore_x + sound_restore_width,
        )
        if sound_source_index_start
        <= original_logical_sound[row * sound_picture.width + column]
        <= sound_source_index_stop
    }
    sound_selective_restore_offsets = {
        target_row * sound_picture.width + target_column
        for source_offset in sound_source_title_offsets
        for target_row in range(
            max(
                sound_restore_y,
                source_offset // sound_picture.width
                - sound_source_dilation_radius,
            ),
            min(
                sound_restore_y + len(sound_restore_rows),
                source_offset // sound_picture.width
                + sound_source_dilation_radius
                + 1,
            ),
        )
        for target_column in range(
            max(
                sound_restore_x,
                source_offset % sound_picture.width
                - sound_source_dilation_radius,
            ),
            min(
                sound_restore_x + sound_restore_width,
                source_offset % sound_picture.width
                + sound_source_dilation_radius
                + 1,
            ),
        )
    }
    sound_source_title_bbox = (
        min(offset % sound_picture.width for offset in sound_source_title_offsets),
        min(offset // sound_picture.width for offset in sound_source_title_offsets),
        max(offset % sound_picture.width for offset in sound_source_title_offsets),
        max(offset // sound_picture.width for offset in sound_source_title_offsets),
    )
    sound_restore_report = sound_label.get("background_restore")
    if (
        len(sound_source_title_offsets) != 3690
        or len(sound_selective_restore_offsets) != 4451
        or sound_source_title_bbox != (15, 4, 205, 32)
        or not isinstance(sound_restore_report, dict)
        or sound_restore_report.get("source_index_start") != 14
        or sound_restore_report.get("source_index_stop") != 31
        or sound_restore_report.get("source_dilation_radius") != 1
        or sound_restore_report.get("restored_pixel_count") != 4451
    ):
        raise SystemExit(
            "final ISO sound-select source-glyph selective restore drift"
        )
    sound_label_x = int(sound_label.get("x", -1))
    sound_label_y = int(sound_label.get("y", -1))
    sound_label_width = int(sound_label.get("width", -1))
    sound_label_height = int(sound_label.get("height", -1))
    if (
        sound_label.get("id") != sound_mask.get("id")
        or sound_label_x != int(sound_mask.get("x", -1))
        or sound_label_y != int(sound_mask.get("y", -1))
        or sound_label_width != int(sound_mask.get("width", -1))
        or sound_label_height != int(sound_mask.get("height", -1))
        or sound_label_x < 0
        or sound_label_y < 0
        or sound_label_width <= 0
        or sound_label_height <= 0
        or sound_label_x + sound_label_width > sound_picture.width
        or sound_label_y + sound_label_height > sound_picture.height
    ):
        raise SystemExit("final ISO sound-select label geometry drift")
    sound_crop = b"".join(
        logical_sound[
            (sound_label_y + row) * sound_picture.width + sound_label_x:
            (sound_label_y + row) * sound_picture.width
            + sound_label_x
            + sound_label_width
        ]
        for row in range(sound_label_height)
    )
    if (
        sound_label.get("id") != "sound-select-title"
        or sound_label.get("translation") != "音乐选择"
        or sha256_bytes(sound_crop) != sound_label.get("output_indexes_sha256")
        or not any(sound_crop)
    ):
        raise SystemExit("final ISO sound-select title rectangle drift")

    sound_span = SoundTitleSpanLock.from_mapping(
        library_scope["sound_select"]["decoded_compdata"]
    )
    source_compdata = decode(
        (PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN").read_bytes()
    ).output
    final_compdata = decode(members["DATA/COMPDATA.BN"]).output
    sound_titles = verify_sound_title_source(
        source_compdata,
        load_text_table(TEXT_TABLE),
        sound_span,
    )
    verify_sound_titles_preserved(
        source_compdata,
        final_compdata,
        sound_span,
    )
    unlock_contract = library_scope["sound_select_default_unlock"]
    _verified_slps, unlock_instruction_readback = (
        apply_sound_select_default_unlock(
            members["SLPS_258.87"],
            unlock_contract,
        )
    )
    unlock_metadata_readback = audit_sound_select_track_metadata(
        final_compdata,
        sound_titles,
        unlock_contract,
    )
    full_unlock_component = component.get("sound_select_default_unlock")
    library_unlock_component = library_component.get(
        "sound_select_default_unlock"
    )
    if (
        not isinstance(full_unlock_component, dict)
        or not isinstance(library_unlock_component, dict)
        or unlock_instruction_readback["output_instruction_hex"]
        != full_unlock_component.get("output_instruction_hex")
        or unlock_instruction_readback["replacement_instruction_hex"]
        != library_unlock_component.get("replacement_instruction_hex")
        or unlock_metadata_readback != full_unlock_component.get("metadata")
        or unlock_metadata_readback != library_unlock_component.get("metadata")
        or unlock_instruction_readback["instruction_replacement_exact"]
        is not True
    ):
        raise SystemExit("final ISO sound-select default-unlock readback drift")
    sound_select_unlock_readback = {
        **unlock_instruction_readback,
        "metadata": unlock_metadata_readback,
        "component_receipts_exact": True,
    }
    library_unlock_contract = library_scope["library_default_unlock"]
    _verified_library_slps, library_unlock_readback = (
        apply_library_default_unlock(
            members["SLPS_258.87"],
            library_unlock_contract,
        )
    )
    full_library_unlock_component = component.get("library_default_unlock")
    reviewed_library_unlock_component = library_component.get(
        "library_default_unlock"
    )
    readback_rows = library_unlock_readback.get("patches")
    full_rows = (
        full_library_unlock_component.get("patches")
        if isinstance(full_library_unlock_component, dict)
        else None
    )
    reviewed_rows = (
        reviewed_library_unlock_component.get("patches")
        if isinstance(reviewed_library_unlock_component, dict)
        else None
    )
    receipt_fields = (
        "surface",
        "virtual_address",
        "file_offset",
        "original_instruction_hex",
        "replacement_instruction_hex",
        "output_instruction_hex",
    )
    normalized_readback = [
        tuple(row.get(field) for field in receipt_fields)
        for row in readback_rows
    ] if isinstance(readback_rows, list) else None
    normalized_full = [
        tuple(row.get(field) for field in receipt_fields)
        for row in full_rows
    ] if isinstance(full_rows, list) else None
    normalized_reviewed = [
        tuple(row.get(field) for field in receipt_fields)
        for row in reviewed_rows
    ] if isinstance(reviewed_rows, list) else None
    if (
        normalized_readback is None
        or normalized_readback != normalized_full
        or normalized_readback != normalized_reviewed
        or library_unlock_readback[
            "all_instruction_replacements_exact"
        ] is not True
        or library_unlock_readback["save_writeback_functions_unchanged"]
        is not True
    ):
        raise SystemExit("final ISO LIBRARY default-unlock readback drift")
    library_unlock_readback["component_receipts_exact"] = True
    full_name_order_contract = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )["runtime_full_name_order"]
    _verified_name_order_slps, full_name_order_readback = (
        apply_route_specific_full_name_order(
            members["SLPS_258.87"],
            full_name_order_contract,
        )
    )
    full_name_order_component = component.get("runtime_full_name_order")
    full_name_order_receipt_fields = (
        "virtual_address",
        "file_offset",
        "original_instruction_hex",
        "replacement_instruction_hex",
        "original_load_address",
        "replacement_load_address",
        "output_instruction_hex",
        "route_values",
        "output_orders",
    )
    full_name_order_site_receipt_fields = (
        "virtual_address",
        "file_offset",
        "original_instruction_hex",
        "replacement_instruction_hex",
        "output_instruction_hex",
        "instruction_replacement_exact",
    )
    if (
        not isinstance(full_name_order_component, dict)
        or any(
            full_name_order_readback.get(field)
            != full_name_order_component.get(field)
            for field in full_name_order_receipt_fields
        )
        or any(
            not isinstance(full_name_order_component.get(site), dict)
            or any(
                full_name_order_readback[site].get(field)
                != full_name_order_component[site].get(field)
                for field in full_name_order_site_receipt_fields
            )
            for site in ("savedata_formatter", "savedata_writeback")
        )
        or full_name_order_readback[
            "all_instruction_replacements_exact"
        ] is not True
        or full_name_order_readback["changed_byte_count"] != 0
    ):
        raise SystemExit("final ISO route-specific full-name order readback drift")
    full_name_order_readback["component_receipt_exact"] = True
    postgame_mode_contract = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )["postgame_mode_unlock"]
    _verified_mode_slps, postgame_mode_unlock_readback = (
        apply_postgame_mode_unlock(
            members["SLPS_258.87"],
            postgame_mode_contract,
        )
    )
    postgame_mode_component = component.get("postgame_mode_unlock")
    mode_site_fields = (
        "id",
        "surface",
        "virtual_address",
        "file_offset",
        "original_instruction_hex",
        "replacement_instruction_hex",
        "output_instruction_hex",
        "branch_target_preserved",
    )
    readback_mode_sites = postgame_mode_unlock_readback.get("patches")
    component_mode_sites = (
        postgame_mode_component.get("patches")
        if isinstance(postgame_mode_component, dict)
        else None
    )
    mode_color_fields = (
        "id",
        "surface",
        "kind",
        "virtual_address",
        "file_offset",
        "original_instruction_hex",
        "replacement_instruction_hex",
        "output_instruction_hex",
        "replacement_immediate",
        "opcode_and_registers_preserved",
    )
    readback_mode_colors = postgame_mode_unlock_readback.get(
        "runtime_color_patches"
    )
    component_mode_colors = (
        postgame_mode_component.get("runtime_color_patches")
        if isinstance(postgame_mode_component, dict)
        else None
    )
    mode_layout_fields = (
        "id",
        "surface",
        "record_file_offset",
        "text_file_offset",
        "text_virtual_address",
        "original_x",
        "replacement_x",
        "output_x",
        "y",
    )
    readback_mode_layout = postgame_mode_unlock_readback.get(
        "text_layout_patches"
    )
    component_mode_layout = (
        postgame_mode_component.get("text_layout_patches")
        if isinstance(postgame_mode_component, dict)
        else None
    )
    if (
        not isinstance(readback_mode_sites, list)
        or not isinstance(component_mode_sites, list)
        or [
            tuple(site.get(field) for field in mode_site_fields)
            for site in readback_mode_sites
        ]
        != [
            tuple(site.get(field) for field in mode_site_fields)
            for site in component_mode_sites
        ]
        or not isinstance(readback_mode_colors, list)
        or not isinstance(component_mode_colors, list)
        or [
            tuple(site.get(field) for field in mode_color_fields)
            for site in readback_mode_colors
        ]
        != [
            tuple(site.get(field) for field in mode_color_fields)
            for site in component_mode_colors
        ]
        or not isinstance(readback_mode_layout, list)
        or not isinstance(component_mode_layout, list)
        or [
            tuple(site.get(field) for field in mode_layout_fields)
            for site in readback_mode_layout
        ]
        != [
            tuple(site.get(field) for field in mode_layout_fields)
            for site in component_mode_layout
        ]
        or postgame_mode_unlock_readback["menu_modes"]
        != ["NORMAL", "EX-HARD", "SP"]
        or postgame_mode_unlock_readback["site_count"] != 6
        or postgame_mode_unlock_readback[
            "all_instruction_replacements_exact"
        ]
        is not True
        or postgame_mode_unlock_readback["runtime_color_patch_count"] != 23
        or postgame_mode_unlock_readback[
            "all_runtime_color_retargets_exact"
        ]
        is not True
        or postgame_mode_unlock_readback[
            "localized_color_parameter_writes_retargeted"
        ]
        is not True
        or postgame_mode_unlock_readback["selected_ex_special_color"]
        != "0x01"
        or postgame_mode_unlock_readback["selected_sp_special_color"]
        != "0x04"
        or postgame_mode_unlock_readback["text_layout_patch_count"] != 4
        or postgame_mode_unlock_readback[
            "all_text_layout_replacements_exact"
        ]
        is not True
        or postgame_mode_unlock_readback["text_descriptor_y_preserved"]
        is not True
        or postgame_mode_unlock_readback["save_flag_reads_bypassed"] is not True
        or postgame_mode_unlock_readback[
            "save_writeback_functions_unchanged"
        ]
        is not True
        or postgame_mode_unlock_readback["changed_byte_count"] != 0
    ):
        raise SystemExit("final ISO post-game mode unlock readback drift")
    postgame_mode_unlock_readback["component_receipt_exact"] = True
    movement_type_contract = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )["runtime_movement_type_labels"]
    _verified_movement_slps, movement_type_readback = (
        apply_runtime_movement_type_labels(
            members["SLPS_258.87"], movement_type_contract
        )
    )
    movement_type_component = component.get("runtime_movement_type_labels")
    movement_site_fields = (
        "id",
        "source_text",
        "translation",
        "virtual_address",
        "file_offset",
        "source_materialized_hex",
        "output_materialized_hex",
        "original_instruction_hex",
        "replacement_instruction_hex",
        "output_instruction_hex",
        "full_materialization_sequence_exact",
    )
    readback_movement_sites = movement_type_readback.get("sites")
    component_movement_sites = (
        movement_type_component.get("sites")
        if isinstance(movement_type_component, dict)
        else None
    )
    normalized_movement_readback = (
        [
            tuple(site.get(field) for field in movement_site_fields)
            for site in readback_movement_sites
        ]
        if isinstance(readback_movement_sites, list)
        else None
    )
    normalized_movement_component = (
        [
            tuple(site.get(field) for field in movement_site_fields)
            for site in component_movement_sites
        ]
        if isinstance(component_movement_sites, list)
        else None
    )
    if (
        normalized_movement_readback is None
        or normalized_movement_readback != normalized_movement_component
        or movement_type_readback["site_count"] != 2
        or movement_type_readback["changed_byte_count"] != 0
        or movement_type_readback["source_suffix"] != "専用"
        or movement_type_readback["output_suffix"] != "专用"
        or movement_type_readback["preserved_parallel_type"]
        != movement_type_component.get("preserved_parallel_type")
        or not movement_type_readback["all_materialization_sequences_exact"]
        or not movement_type_readback["all_replacements_exact"]
    ):
        raise SystemExit("final ISO runtime movement-type label readback drift")
    movement_type_readback["component_receipt_exact"] = True
    weapon_category_contract = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )["runtime_weapon_category_labels"]
    _verified_weapon_category_slps, weapon_category_readback = (
        apply_runtime_weapon_category_labels(
            members["SLPS_258.87"], weapon_category_contract
        )
    )
    weapon_category_component = component.get(
        "runtime_weapon_category_labels"
    )
    weapon_category_site_fields = (
        "id",
        "source_text",
        "translation",
        "virtual_address",
        "file_offset",
        "source_materialized_hex",
        "output_materialized_hex",
        "original_prefix_instruction_hex",
        "replacement_prefix_instruction_hex",
        "output_prefix_instruction_hex",
        "shared_branch_applies_to_all_matching_weapons",
        "full_materialization_sequence_exact",
    )
    readback_weapon_category_sites = weapon_category_readback.get("sites")
    component_weapon_category_sites = (
        weapon_category_component.get("sites")
        if isinstance(weapon_category_component, dict)
        else None
    )
    normalized_weapon_category_readback = (
        [
            tuple(site.get(field) for field in weapon_category_site_fields)
            for site in readback_weapon_category_sites
        ]
        if isinstance(readback_weapon_category_sites, list)
        else None
    )
    normalized_weapon_category_component = (
        [
            tuple(site.get(field) for field in weapon_category_site_fields)
            for site in component_weapon_category_sites
        ]
        if isinstance(component_weapon_category_sites, list)
        else None
    )
    if (
        _verified_weapon_category_slps != members["SLPS_258.87"]
        or normalized_weapon_category_readback is None
        or normalized_weapon_category_readback
        != normalized_weapon_category_component
        or weapon_category_readback["site_count"] != 2
        or weapon_category_readback["changed_byte_count"] != 0
        or not all(
            site["already_patched"]
            for site in weapon_category_readback["sites"]
        )
        or not weapon_category_readback[
            "all_matching_weapon_instances_covered_by_shared_branches"
        ]
        or not weapon_category_readback[
            "all_materialization_sequences_exact"
        ]
        or not weapon_category_readback["all_replacements_exact"]
    ):
        raise SystemExit(
            "final ISO runtime weapon-category label readback drift"
        )
    weapon_category_readback["component_receipt_exact"] = True
    search_alignment_contract = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )["remaining_ui"]["search_tab_alignment"]
    _verified_search_slps, search_tab_alignment_readback = (
        apply_search_tab_alignment(
            members["SLPS_258.87"], search_alignment_contract
        )
    )
    component_search_alignment = component.get("search_tab_alignment")
    readback_search_rows = search_tab_alignment_readback.get("patches")
    component_search_rows = (
        component_search_alignment.get("patches")
        if isinstance(component_search_alignment, dict)
        else None
    )
    search_receipt_fields = (
        "surface",
        "label",
        "source_text",
        "source_string_file_offset",
        "virtual_address",
        "file_offset",
        "original_byte_hex",
        "replacement_byte_hex",
        "output_byte_hex",
    )
    normalized_search_readback = [
        tuple(row.get(field) for field in search_receipt_fields)
        for row in readback_search_rows
    ] if isinstance(readback_search_rows, list) else None
    normalized_search_component = [
        tuple(row.get(field) for field in search_receipt_fields)
        for row in component_search_rows
    ] if isinstance(component_search_rows, list) else None
    if (
        normalized_search_readback is None
        or normalized_search_readback != normalized_search_component
        or search_tab_alignment_readback["surface_count"] != 5
        or search_tab_alignment_readback["center_byte_hex"] != "0F"
        or search_tab_alignment_readback["changed_byte_count"] != 0
        or search_tab_alignment_readback["all_replacements_exact"] is not True
        or search_tab_alignment_readback["executable_size_preserved"] is not True
    ):
        raise SystemExit("final ISO Search-tab alignment readback drift")
    search_tab_alignment_readback["component_receipt_exact"] = True
    intermission_library_alignment_contract = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )["remaining_ui"]["intermission_library_alignment"]
    (
        _verified_intermission_library_slps,
        intermission_library_alignment_readback,
    ) = apply_intermission_library_alignment(
        members["SLPS_258.87"],
        intermission_library_alignment_contract,
    )
    component_intermission_library_alignment = component.get(
        "intermission_library_alignment"
    )
    library_alignment_receipt_fields = (
        "policy",
        "member",
        "target_surface",
        "position_table_file_offset",
        "target_coordinate_file_offset",
        "original_x",
        "replacement_x",
        "shift_pixels",
        "entry_count",
    )
    library_alignment_entry_fields = (
        "surface",
        "label",
        "source_string_file_offset",
        "pointer_virtual_address",
        "row_file_offset",
        "output_x",
        "targeted",
    )
    normalized_library_alignment_readback = (
        tuple(
            intermission_library_alignment_readback.get(field)
            for field in library_alignment_receipt_fields
        ),
        tuple(
            tuple(entry.get(field) for field in library_alignment_entry_fields)
            for entry in intermission_library_alignment_readback.get(
                "entries", []
            )
        ),
    )
    normalized_library_alignment_component = (
        (
            tuple(
                component_intermission_library_alignment.get(field)
                for field in library_alignment_receipt_fields
            ),
            tuple(
                tuple(entry.get(field) for field in library_alignment_entry_fields)
                for entry in component_intermission_library_alignment.get(
                    "entries", []
                )
            ),
        )
        if isinstance(component_intermission_library_alignment, dict)
        else None
    )
    if (
        normalized_library_alignment_readback
        != normalized_library_alignment_component
        or intermission_library_alignment_readback["entry_count"] != 6
        or intermission_library_alignment_readback["original_x"] != -90
        or intermission_library_alignment_readback["replacement_x"] != -100
        or intermission_library_alignment_readback["shift_pixels"] != -10
        or intermission_library_alignment_readback["changed_byte_count"] != 0
        or not intermission_library_alignment_readback[
            "changed_bytes_confined_to_target_coordinate"
        ]
        or not intermission_library_alignment_readback["pointer_table_preserved"]
        or not intermission_library_alignment_readback["sibling_rows_preserved"]
        or not intermission_library_alignment_readback["target_tail_preserved"]
        or not intermission_library_alignment_readback[
            "executable_size_preserved"
        ]
    ):
        raise SystemExit(
            "final ISO intermission Library alignment readback drift"
        )
    intermission_library_alignment_readback[
        "component_receipt_exact"
    ] = True
    remaining_count_alignment_contract = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )["remaining_ui"]["remaining_squad_count_alignment"]
    (
        _verified_remaining_count_slps,
        remaining_squad_count_alignment_readback,
    ) = apply_remaining_squad_count_alignment(
        members["SLPS_258.87"], remaining_count_alignment_contract
    )
    component_remaining_count_alignment = component.get(
        "remaining_squad_count_alignment"
    )
    remaining_count_receipt_fields = (
        "policy",
        "member",
        "source_format_file_offset",
        "prefix_x",
        "original_number_x",
        "replacement_number_x",
        "suffix_x",
        "shift_pixels",
        "number_instruction_virtual_address",
        "number_instruction_file_offset",
        "original_number_instruction_hex",
        "replacement_number_instruction_hex",
        "output_number_instruction_hex",
    )
    normalized_remaining_count_readback = tuple(
        remaining_squad_count_alignment_readback.get(field)
        for field in remaining_count_receipt_fields
    )
    normalized_remaining_count_component = (
        tuple(
            component_remaining_count_alignment.get(field)
            for field in remaining_count_receipt_fields
        )
        if isinstance(component_remaining_count_alignment, dict)
        else None
    )
    if (
        normalized_remaining_count_readback
        != normalized_remaining_count_component
        or remaining_squad_count_alignment_readback["shift_pixels"] != 8
        or remaining_squad_count_alignment_readback["changed_byte_count"] != 0
        or remaining_squad_count_alignment_readback[
            "adjacent_coordinates_preserved"
        ]
        is not True
        or remaining_squad_count_alignment_readback["format_token_untouched"]
        is not True
        or remaining_squad_count_alignment_readback[
            "instruction_replacement_exact"
        ]
        is not True
        or remaining_squad_count_alignment_readback[
            "executable_size_preserved"
        ]
        is not True
    ):
        raise SystemExit(
            "final ISO remaining squad-count alignment readback drift"
        )
    remaining_squad_count_alignment_readback[
        "component_receipt_exact"
    ] = True
    sound_select_readback = {
        "member": "DATA/NISVDATA.BIN",
        "chunk_index": int(sound_target["chunk_index"]),
        "stored_start": sound_stored_start,
        "stored_end": sound_stored_end,
        "stored_size": len(final_sound_stored),
        "stored_sha256": sha256_bytes(final_sound_stored),
        "encoded_size": final_sound_decoded.consumed,
        "record_index": sound_record_index,
        "record_offset": sound_record.offset,
        "record_size": sound_record.size,
        "record_sha256": sound_select_component["output_record_sha256"],
        "title": sound_label["translation"],
        "storage_layout": "gs_psmt8",
        "output_logical_indexes_sha256": sha256_bytes(logical_sound),
        "source_alpha_plane_sha256": sha256_bytes(original_sound_alpha),
        "output_alpha_plane_sha256": sha256_bytes(final_sound_alpha),
        "transparent_pixel_count": final_sound_alpha.count(0),
        "alpha_mask_preserved": True,
        "background_restore_crosses_no_transparent_pixels": True,
        "source_title_index_bbox": list(sound_source_title_bbox),
        "source_title_index_pixel_count": len(sound_source_title_offsets),
        "selective_background_pixel_count": len(
            sound_selective_restore_offsets
        ),
        "source_title_right_edge_covered": sound_source_title_bbox[2] == 205,
        "source_title_pixels_selectively_restored": True,
        "non_title_pixels_byte_exact": True,
        "clut_and_tim2_metadata_byte_exact": True,
        "title_output_indexes_sha256": sound_label[
            "output_indexes_sha256"
        ],
        "track_title_count": len(sound_titles),
        "track_title_span_sha256": sound_span.expected_span_sha256,
        "track_titles_byte_exact": True,
        "fixed_title_rectangle_reread_exact": True,
        "policy": (
            "restore_only_source_glyph_pixels_and_preserve_plate_and_alpha"
        ),
        "default_unlock": sound_select_unlock_readback,
    }

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
    auto_demo_overlays = verify_auto_demo_overlays(
        slps,
        members,
        compdata_table,
        component_manifest,
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
    mode_select_effect = verify_scenario_select_effect(
        slps,
        members["EFF/VEFF2DX.BIN"],
        component_manifest,
        config_key="mode_select_effect",
    )
    nisv_strategy_qa = verify_nisv_strategy_qa(
        slps,
        members["DATA/NISVDATA.BIN"],
        compdata_table,
        component_manifest,
    )
    nisv_effect_names = nisv_strategy_qa["effect_names"]
    stage_overrides = dict(overrides)
    stage_overrides.update(surface_aliases)
    stage_overrides.update(ascii_overrides)
    stage_table = project_runtime_text_table(
        source_table,
        stage_overrides,
    )
    post_release_runtime_surfaces = verify_post_release_runtime_surfaces(
        slps=slps,
        mtv_prop=members["DATA/MTV_PROP.BIN"],
        stage=stage_archive,
        hb=hb,
        source_table=source_table,
        output_table=stage_table,
        component=component,
    )
    issue_036_tutorial = verify_issue_036_tutorial(
        slps=slps,
        nisvdata=members["DATA/NISVDATA.BIN"],
        veff=members["EFF/VEFF2DX.BIN"],
        stage=stage_archive,
        hb=hb,
        source_table=source_table,
        output_table=stage_table,
        component=component,
    )
    overview_overrides = dict(overrides)
    overview_overrides.update(surface_aliases)
    overview_overrides.update(ascii_overrides)
    overview_table = project_runtime_text_table(
        source_table,
        overview_overrides,
    )
    full_component_config = json.loads(
        FULL_COMPONENT_CONFIG.read_text(encoding="utf-8")
    )
    weapon_effect_config = full_component_config.get(
        "weapon_special_effect_2"
    )
    if not isinstance(weapon_effect_config, dict):
        raise SystemExit(
            "weapon special-effect-2 final-ISO configuration is missing"
        )
    weapon_effect_corpus_path = (
        PROJECT_ROOT / weapon_effect_config["corpus"]["path"]
    )
    weapon_effect_corpus_data = weapon_effect_corpus_path.read_bytes()
    if (
        len(weapon_effect_corpus_data)
        != weapon_effect_config["corpus"]["size"]
        or sha256_bytes(weapon_effect_corpus_data)
        != weapon_effect_config["corpus"]["sha256"]
    ):
        raise SystemExit("weapon special-effect-2 corpus lock drift")
    try:
        verified_slps, weapon_effect_2_readback = (
            apply_weapon_special_effect_2(
                slps,
                weapon_effect_config,
                json.loads(weapon_effect_corpus_data.decode("utf-8")),
                source_table=source_table,
                encoding_overrides=overview_overrides,
            )
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        WeaponSpecialEffectError,
    ) as error:
        raise SystemExit(
            f"weapon special-effect-2 final-ISO readback failed: {error}"
        ) from error
    if (
        verified_slps != slps
        or not all(
            row["already_patched"]
            for row in weapon_effect_2_readback["entries"]
        )
        or weapon_effect_2_readback["changed_byte_count"] != 0
        or [row["translation"] for row in weapon_effect_2_readback["entries"]]
        != weapon_effect_config["expected"]["translated_labels"]
        or component.get("weapon_special_effect_2", {}).get("entry_count")
        != weapon_effect_2_readback["entry_count"]
    ):
        raise SystemExit("weapon special-effect-2 final-ISO receipt drift")
    runtime_keyword_reference = full_component_config.get("runtime_keywords")
    if not isinstance(runtime_keyword_reference, dict):
        raise SystemExit("runtime-keyword final-ISO configuration is missing")

    def locked_runtime_keyword_input(reference: dict, label: str) -> bytes:
        path = PROJECT_ROOT / str(reference.get("path", ""))
        data = path.read_bytes()
        if (
            len(data) != reference.get("size")
            or sha256_bytes(data) != reference.get("sha256")
        ):
            raise SystemExit(f"runtime-keyword input lock drift: {label}")
        return data

    runtime_keyword_catalog = locked_runtime_keyword_input(
        runtime_keyword_reference["catalog"],
        "catalog",
    )
    locked_runtime_keyword_input(
        runtime_keyword_reference["library_archive"],
        "translated LIBRARY archive",
    )
    try:
        runtime_keyword_authority = load_keyword_authority(
            runtime_keyword_catalog,
            members["DATA/MTVZKNKW.BIN"],
            slps,
            compdata_table,
            table_start=int(
                str(runtime_keyword_reference["keyword_table_start"]), 0
            ),
            table_end=int(
                str(runtime_keyword_reference["keyword_table_end"]), 0
            ),
            expected_count=runtime_keyword_reference["expected"][
                "keyword_count"
            ],
        )
        original_compdata_stored = locked_runtime_keyword_input(
            full_component_config["remaining_ui"]["original_compdata"],
            "original COMPDATA",
        )
        original_compdata = decode(original_compdata_stored)
        final_compdata_stored = members["DATA/COMPDATA.BN"]
        final_compdata = decode(final_compdata_stored)
        if (
            original_compdata.consumed != len(original_compdata_stored)
            or final_compdata.consumed != len(final_compdata_stored)
        ):
            raise RuntimeKeywordError("COMPDATA keyword stream boundary drift")
        verified_compdata, runtime_keyword_compdata_report = (
            apply_compdata_keyword_names(
                final_compdata.output,
                original_compdata.output,
                runtime_keyword_authority,
                source_table,
                runtime_keyword_reference,
                runtime_base=int(
                    str(runtime_keyword_reference["compdata_runtime_base"]), 0
                ),
                pointer_table_offset=int(
                    str(
                        runtime_keyword_reference[
                            "compdata_pointer_table_offset"
                        ]
                    ),
                    0,
                ),
            )
        )
        if verified_compdata != final_compdata.output:
            raise RuntimeKeywordError(
                "final COMPDATA keyword list labels are not complete"
            )
        original_stage = locked_runtime_keyword_input(
            full_component_config["remaining_ui"]["original_stage"],
            "original STAGE",
        )
        verified_stage, runtime_keyword_stage_report = (
            apply_stage_keyword_popups(
                stage_archive,
                original_stage,
                hb,
                runtime_keyword_authority,
                source_table,
                runtime_keyword_reference,
                full_component_config["full_pilot_names"]["codec"],
                verify_only=True,
            )
        )
        if verified_stage != stage_archive:
            raise RuntimeKeywordError(
                "final STAGE keyword popup fields are not complete"
            )
    except (KeyError, TypeError, ValueError, RuntimeKeywordError) as error:
        raise SystemExit(f"runtime-keyword final-ISO readback failed: {error}") from error
    runtime_keyword_fields = [
        field
        for fields in runtime_keyword_authority.fields
        for field in fields.values()
    ]
    runtime_keyword_space_report = {
        "field_count": len(runtime_keyword_fields),
        "raw_visible_space_count": sum(
            field.data.count(b"\x20") for field in runtime_keyword_fields
        ),
        "two_byte_visible_space_count": sum(
            field.data.count(b"\x81\x40") for field in runtime_keyword_fields
        ),
        "all_visible_spaces_two_byte": True,
    }
    runtime_keyword_report = {
        "authority_keyword_count": len(runtime_keyword_authority.entries),
        "library_popup_fields_exact": True,
        "visible_space_storage": runtime_keyword_space_report,
        "compdata": runtime_keyword_compdata_report,
        "stage": runtime_keyword_stage_report,
        "all_three_runtime_surfaces_exact": True,
    }
    world_history_report = verify_world_history(
        slps,
        members["DATA/MTV_PROS.BIN"],
        overview_table,
        full_component_config.get("world_history", {}),
    )
    stage_system_dialogue_report = verify_stage_system_dialogues(
        stage_archive,
        offsets,
        source_table,
        stage_table,
        full_component_config,
    )
    stage_scenario_chart_prompt_report = verify_stage_scenario_chart_prompts(
        stage_archive,
        offsets,
        source_table,
        stage_table,
        full_component_config,
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
    overview_policy = overview_corpus.get("policy", {})
    overview_line_width_limit = overview_policy.get("maximum_line_width")
    if (
        overview_policy.get("reflow_profile_id")
        != "stage_scroll_overview"
        or overview_line_width_limit != 29
        or overview_policy.get("source_line_count_is_upper_bound") is not True
        or overview_policy.get("preserve_paragraph_indents") is not True
    ):
        raise SystemExit("stage-overview layout policy drift")
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
    overview_raw_space_entry_count = sum(
        b"\x20"
        in decoded_overview.output[
            entry.text_offset : entry.text_offset + entry.encoded_size
        ]
        for entry in overview_entries
    )
    if overview_raw_space_entry_count:
        raise SystemExit("final ISO stage overview contains raw spaces")
    overview_examples = {}
    overview_output_line_count = 0
    overview_paragraph_indent_count = 0
    overview_maximum_line_width = 0
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
            or entry.source_text
            != expected_text.replace(" ", "\u3000")
        ):
            raise SystemExit(
                f"final ISO stage-overview mismatch: {row.get('id')}"
            )
        overview_lines = entry.source_text.rstrip("\n").splitlines()
        overview_widths = dialogue_line_widths(entry.source_text.rstrip("\n"))
        if (
            not overview_lines
            or not overview_lines[0].startswith("　")
            or max(overview_widths, default=0) > overview_line_width_limit
        ):
            raise SystemExit(
                f"final ISO stage-overview layout drift: {row.get('id')}"
            )
        overview_output_line_count += len(overview_lines)
        overview_paragraph_indent_count += sum(
            line.startswith("　") for line in overview_lines
        )
        overview_maximum_line_width = max(
            overview_maximum_line_width,
            max(overview_widths, default=0),
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
        "raw_space_entry_count": overview_raw_space_entry_count,
        "raw_space_count_zero": True,
        "line_width_limit": overview_line_width_limit,
        "maximum_output_line_width": overview_maximum_line_width,
        "output_line_count": overview_output_line_count,
        "paragraph_indent_count": overview_paragraph_indent_count,
        "layout_policy_exact": True,
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
    hsfc_raw_space_cell_count = 0
    for record in final_hsfc_records:
        for cell_index in range(3):
            cell_offset = (
                record.record_offset
                + cell_index * HSFC_OVERVIEW_CELL_SIZE
            )
            cell = decode_text(
                final_hsfc_decoded.output,
                cell_offset,
                overview_table,
            )
            hsfc_raw_space_cell_count += b"\x20" in final_hsfc_decoded.output[
                cell_offset : cell_offset + cell.consumed
            ]
    if hsfc_raw_space_cell_count:
        raise SystemExit("final ISO HSFC overview contains raw spaces")
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
        "raw_space_cell_count": hsfc_raw_space_cell_count,
        "raw_space_count_zero": True,
    }
    scenario_stored_start = hsfc_offsets[1]
    scenario_stored_end = hsfc_offsets[2]
    original_scenario_stored = original_hsfc[
        scenario_stored_start:scenario_stored_end
    ]
    final_scenario_stored = final_hsfc[
        scenario_stored_start:scenario_stored_end
    ]
    scenario_chart_component = component.get("runtime_library_menu", {}).get(
        "scenario_chart"
    )
    scenario_chart_contract = library_scope.get("scenario_chart_runtime_tim2")
    if (
        not isinstance(scenario_chart_component, dict)
        or not isinstance(scenario_chart_contract, dict)
        or scenario_chart_component.get("scenario_chart_title_written")
        is not True
        or scenario_chart_component.get("alpha_mask_preserved") is not True
    ):
        raise SystemExit("final ISO Scenario Chart title proof is incomplete")
    scenario_target = scenario_chart_contract.get("target")
    scenario_writeback = scenario_chart_contract.get("writeback")
    if (
        not isinstance(scenario_target, dict)
        or not isinstance(scenario_writeback, dict)
        or scenario_target.get("storage_layout") != "linear_indexed8"
        or scenario_target.get("stored_start") != scenario_stored_start
        or scenario_target.get("stored_end") != scenario_stored_end
        or scenario_target.get("stored_size") != len(original_scenario_stored)
        or sha256_bytes(original_scenario_stored)
        != scenario_target.get("stored_sha256")
    ):
        raise SystemExit("final ISO Scenario Chart source contract drift")

    original_scenario_decoded = decode(original_scenario_stored)
    final_scenario_decoded = decode(final_scenario_stored)
    if (
        original_scenario_decoded.consumed
        != scenario_target.get("stored_consumed")
        or len(original_scenario_decoded.output)
        != scenario_target.get("decoded_size")
        or sha256_bytes(original_scenario_decoded.output)
        != scenario_target.get("decoded_sha256")
        or any(
            original_scenario_stored[original_scenario_decoded.consumed :]
        )
        or any(final_scenario_stored[final_scenario_decoded.consumed :])
        or final_scenario_decoded.consumed
        != scenario_chart_component.get("output_encoded_size")
    ):
        raise SystemExit("final ISO Scenario Chart chunk decode drift")
    original_scenario_records = scan_tim2(original_scenario_decoded.output)
    final_scenario_records = scan_tim2(final_scenario_decoded.output)
    record_index = int(scenario_target.get("record_index", -1))
    if (
        not 0 <= record_index < len(original_scenario_records)
        or len(original_scenario_records) != len(final_scenario_records)
    ):
        raise SystemExit("final ISO Scenario Chart TIM2 record is missing")
    original_record = original_scenario_records[record_index]
    final_record = final_scenario_records[record_index]
    if (
        original_record.offset != scenario_target.get("record_offset")
        or original_record.size != scenario_target.get("record_size")
        or original_record != final_record
        or sha256_bytes(
            original_scenario_decoded.output[
                original_record.offset:original_record.end
            ]
        )
        != scenario_target.get("record_sha256")
        or len(original_record.pictures) != 1
    ):
        raise SystemExit("final ISO Scenario Chart TIM2 metadata drift")
    picture = original_record.pictures[0]
    image_start = picture.offset + picture.header_size
    image_end = image_start + picture.image_size
    palette_end = image_end + picture.clut_size
    original_indexes = original_scenario_decoded.output[image_start:image_end]
    final_indexes = final_scenario_decoded.output[image_start:image_end]
    original_palette = original_scenario_decoded.output[image_end:palette_end]
    final_palette = final_scenario_decoded.output[image_end:palette_end]
    if (
        picture.width != scenario_target.get("width")
        or picture.height != scenario_target.get("height")
        or picture.image_type != scenario_target.get("image_type")
        or picture.image_size != picture.width * picture.height
        or picture.clut_size != 256 * 4
        or sha256_bytes(original_indexes)
        != scenario_target.get("logical_indexes_sha256")
        or sha256_bytes(final_indexes)
        != scenario_chart_component.get("output_logical_indexes_sha256")
        or sha256_bytes(
            final_scenario_decoded.output[final_record.offset:final_record.end]
        )
        != scenario_chart_component.get("output_record_sha256")
        or original_palette != final_palette
        or (
            original_scenario_decoded.output[:image_start]
            + original_scenario_decoded.output[image_end:]
        )
        != (
            final_scenario_decoded.output[:image_start]
            + final_scenario_decoded.output[image_end:]
        )
    ):
        raise SystemExit("final ISO Scenario Chart indexed texture drift")

    original_alpha = indexed_alpha_plane(original_indexes, original_palette)
    final_alpha = indexed_alpha_plane(final_indexes, final_palette)
    if (
        sha256_bytes(original_alpha)
        != scenario_target.get("source_alpha_plane_sha256")
        or original_alpha != final_alpha
        or sha256_bytes(original_alpha)
        != scenario_chart_component.get("source_alpha_plane_sha256")
        or sha256_bytes(final_alpha)
        != scenario_chart_component.get("output_alpha_plane_sha256")
        or original_alpha.count(0)
        != scenario_chart_component.get("source_transparent_pixel_count")
        or final_alpha.count(0)
        != scenario_chart_component.get("output_transparent_pixel_count")
    ):
        raise SystemExit("final ISO Scenario Chart alpha mask drift")

    masks = scenario_writeback.get("masks")
    labels = scenario_chart_component.get("labels")
    if (
        not isinstance(masks, list)
        or len(masks) != 1
        or not isinstance(labels, list)
        or len(labels) != 1
    ):
        raise SystemExit("final ISO Scenario Chart title selection drift")
    mask = masks[0]
    label = labels[0]
    restore = mask.get("background_restore")
    if not isinstance(restore, dict):
        raise SystemExit("final ISO Scenario Chart background restore is missing")
    restore_x = int(restore.get("x", -1))
    restore_y = int(restore.get("y", -1))
    restore_width = int(restore.get("width", -1))
    restore_rows = restore.get("row_indexes")
    if (
        not isinstance(restore_rows, list)
        or not restore_rows
        or restore_x < 0
        or restore_y < 0
        or restore_width <= 0
        or restore_x + restore_width > picture.width
        or restore_y + len(restore_rows) > picture.height
    ):
        raise SystemExit("final ISO Scenario Chart background geometry drift")
    restore_offsets = {
        row * picture.width + column
        for row in range(restore_y, restore_y + len(restore_rows))
        for column in range(restore_x, restore_x + restore_width)
    }
    if any(
        source_index != final_index
        for offset, (source_index, final_index) in enumerate(
            zip(original_indexes, final_indexes)
        )
        if offset not in restore_offsets
    ):
        raise SystemExit("final ISO Scenario Chart changed outside title interior")
    source_restore_crop = b"".join(
        original_indexes[
            (restore_y + row) * picture.width + restore_x:
            (restore_y + row) * picture.width + restore_x + restore_width
        ]
        for row in range(len(restore_rows))
    )
    if (
        sha256_bytes(source_restore_crop) != mask.get("source_indexes_sha256")
        or indexed_alpha_plane(source_restore_crop, original_palette).count(0)
        != 0
    ):
        raise SystemExit(
            "final ISO Scenario Chart restore rectangle crosses transparency"
        )
    label_x = int(label.get("x", -1))
    label_y = int(label.get("y", -1))
    label_width = int(label.get("width", -1))
    label_height = int(label.get("height", -1))
    if (
        label.get("id") != mask.get("id")
        or label_x != int(mask.get("x", -1))
        or label_y != int(mask.get("y", -1))
        or label_width != int(mask.get("width", -1))
        or label_height != int(mask.get("height", -1))
        or label_x < 0
        or label_y < 0
        or label_width <= 0
        or label_height <= 0
        or label_x + label_width > picture.width
        or label_y + label_height > picture.height
    ):
        raise SystemExit("final ISO Scenario Chart label geometry drift")
    label_crop = b"".join(
        final_indexes[
            (label_y + row) * picture.width + label_x:
            (label_y + row) * picture.width + label_x + label_width
        ]
        for row in range(label_height)
    )
    if (
        label.get("id") != "scenario-chart-title"
        or label.get("translation") != "剧情流程"
        or sha256_bytes(label_crop) != label.get("output_indexes_sha256")
        or not any(label_crop)
    ):
        raise SystemExit("final ISO Scenario Chart Chinese title drift")

    scenario_chart_title_readback = {
        "member": "DATA/HSFC.BIN",
        "chunk_index": 1,
        "stored_start": scenario_stored_start,
        "stored_end": scenario_stored_end,
        "stored_size": len(final_scenario_stored),
        "stored_sha256": sha256_bytes(final_scenario_stored),
        "encoded_size": final_scenario_decoded.consumed,
        "record_index": record_index,
        "record_offset": final_record.offset,
        "record_sha256": sha256_bytes(
            final_scenario_decoded.output[final_record.offset:final_record.end]
        ),
        "storage_layout": "linear_indexed8",
        "translation": "剧情流程",
        "output_logical_indexes_sha256": sha256_bytes(final_indexes),
        "source_alpha_plane_sha256": sha256_bytes(original_alpha),
        "output_alpha_plane_sha256": sha256_bytes(final_alpha),
        "transparent_pixel_count": final_alpha.count(0),
        "alpha_mask_preserved": True,
        "background_restore_crosses_no_transparent_pixels": True,
        "non_title_pixels_byte_exact": True,
        "clut_and_tim2_metadata_byte_exact": True,
        "translated_title_reread_exact": True,
        "policy": "restore_original_row_gradient_and_preserve_alpha_mask",
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
    condition_corpus_path = PROJECT_ROOT / "corpus/zh/story-conditions.json"
    condition_corpus = json.loads(
        condition_corpus_path.read_text(encoding="utf-8")
    )
    conditions = {
        entry["id"]: normalize_original_fullwidth_ascii(
            entry["translation"]
        )
        for entry in condition_corpus["entries"]
    }
    condition_actions = {
        entry["id"]: entry["translation_action"]
        for entry in condition_corpus["entries"]
    }
    condition_runtime_name_placeholders = {
        entry["id"]: entry["translation"].count(":")
        for entry in condition_corpus["entries"]
        if "姓名占位控制标记" in entry.get("notes", "")
    }
    if (
        len(condition_runtime_name_placeholders) != 12
        or any(
            count <= 0
            for count in condition_runtime_name_placeholders.values()
        )
    ):
        raise SystemExit("condition runtime-name placeholder registry drift")
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
    fixed_formation_metadata = component.get("remaining_ui", {}).get(
        "stage_fixed_formation", {}
    )
    default_formation_metadata = {
        item.get("stage_index"): item
        for item in component.get("remaining_ui", {})
        .get("stage_default_formation", {})
        .get("chunks", [])
        if isinstance(item, dict)
    }
    runtime_keyword_stage_metadata = {
        item.get("stage_index"): item
        for item in component.get("runtime_keywords", {})
        .get("stage", {})
        .get("chunks", [])
        if isinstance(item, dict)
    }

    stage_reports = []
    total_entries = 0
    total_dialogue = 0
    total_conditions = 0
    total_speakers = 0
    maximum_dialogue_line_width = 0
    maximum_dialogue_line_count = 0
    dialogue_quote_style_counts = Counter()
    runtime_token_entry_count = 0
    runtime_token_occurrence_count = 0
    story_raw_space_target_count = 0
    story_raw_visible_ascii_glyph_count = 0
    story_raw_visible_ascii_target_count = 0
    story_ascii_storage_examples = {}
    stale_stage_runtime_rendering_checked_count = 0
    stale_stage_runtime_rendering_distinct_fingerprint_count = 0
    stale_stage_runtime_rendering_match_count = 0
    translated_condition_source_payload_checked_count = 0
    dynamic_condition_variant_count = 0
    dynamic_condition_variant_stages = set()
    condition_source_payload_match_count = 0
    condition_original_offset_source_payload_match_count = 0
    condition_runtime_name_placeholder_entry_count = 0
    condition_runtime_name_placeholder_occurrence_count = 0
    condition_runtime_name_placeholder_readback = None
    reported_dynamic_condition_entry_id = "story/002/condition/00/03"
    reported_dynamic_condition_readback = None
    player_choice_entry_ids = {
        "story/002/dialogue/01.18/0008",
        "story/007/dialogue/01.05/0013",
        "story/016/dialogue/01.03/0005",
        "story/035/dialogue/02.02/0035",
        "story/035/dialogue/02.02/0155",
        "story/110/dialogue/02.02/0087",
        "story/111/dialogue/02.02/0104",
        "story/140/dialogue/01.30/0095",
        "story/140/dialogue/01.39/0043",
        "story/142/dialogue/01.10/0008",
        "story/142/dialogue/01.14/0008",
        "story/147/dialogue/01.10/0010",
        "story/147/dialogue/01.14/0010",
        "story/154/dialogue/00.01/0152",
        "story/154/dialogue/00.01/0185",
        "story/157/dialogue/00.01/0023",
        "story/160/dialogue/00.01/0058",
    }
    player_choice_readbacks = {}
    reported_land_entry_id = "story/016/dialogue/02.03/0027"
    reported_land_translation = None
    for stage in stages:
        dialogue = load_translations(
            PROJECT_ROOT
            / f"corpus/zh/story-dialogue/stage-{stage:03d}.json"
        )
        dialogue = {
            entry_id: fit_chinese_dialogue_layout(
                translation,
                stage_keyword_links=("《" in translation),
            ).text
            for entry_id, translation in dialogue.items()
        }
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
        expected_encoded_size = expected_stage["output_encoded_size"]
        expected_encoded_sha256 = expected_stage["output_encoded_sha256"]
        if stage == fixed_formation_metadata.get("chunk_index"):
            expected_encoded_size = fixed_formation_metadata.get(
                "output_encoded_size"
            )
            expected_encoded_sha256 = fixed_formation_metadata.get(
                "output_encoded_sha256"
            )
        if stage in default_formation_metadata:
            expected_encoded_size = default_formation_metadata[stage].get(
                "output_encoded_size"
            )
            expected_encoded_sha256 = default_formation_metadata[stage].get(
                "output_encoded_sha256"
            )
        if stage in runtime_keyword_stage_metadata:
            expected_encoded_size = runtime_keyword_stage_metadata[stage].get(
                "output_encoded_size"
            )
            expected_encoded_sha256 = runtime_keyword_stage_metadata[stage].get(
                "output_encoded_sha256"
            )
        encoded = chunk[:decoded.consumed]
        padding = chunk[decoded.consumed:]
        if any(padding):
            raise SystemExit(f"stage {stage:03d} has non-zero archive padding")
        if (
            decoded.consumed != expected_encoded_size
            or sha256_bytes(encoded)
            != expected_encoded_sha256
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
        stage_raw_space_target_count = 0
        stage_raw_visible_ascii_glyph_count = 0
        stage_raw_visible_ascii_target_count = 0
        seen_text_offsets = set()
        for entry in parsed.entries:
            if (
                entry.text_offset is None
                or entry.text_offset in seen_text_offsets
            ):
                continue
            seen_text_offsets.add(entry.text_offset)
            stored_text = decode_text(
                decoded.output,
                entry.text_offset,
                stage_table,
            )
            stored_payload = decoded.output[
                entry.text_offset : entry.text_offset + stored_text.consumed
            ]
            stage_raw_space_target_count += b"\x20" in stored_payload
            raw_ascii = raw_visible_ascii_glyphs(stored_payload)
            if entry.entry_id in condition_runtime_name_placeholders:
                raw_ascii = tuple(
                    item for item in raw_ascii if item[1] != ":"
                )
            stage_raw_visible_ascii_glyph_count += len(raw_ascii)
            stage_raw_visible_ascii_target_count += bool(raw_ascii)
        if stage_raw_space_target_count:
            raise SystemExit(
                f"stage {stage:03d} contains raw visible spaces"
            )
        if stage_raw_visible_ascii_glyph_count:
            raise SystemExit(
                f"stage {stage:03d} contains "
                f"{stage_raw_visible_ascii_glyph_count} unsafe raw visible "
                "ASCII glyphs"
            )
        story_raw_space_target_count += stage_raw_space_target_count
        story_raw_visible_ascii_glyph_count += (
            stage_raw_visible_ascii_glyph_count
        )
        story_raw_visible_ascii_target_count += (
            stage_raw_visible_ascii_target_count
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
        source_condition_entries = {
            entry.entry_id: entry
            for entry in source_parsed.entries
            if entry.kind == "condition"
        }
        output_condition_entries = {
            entry.entry_id: entry
            for entry in parsed.entries
            if entry.kind == "condition"
        }
        if (
            set(source_condition_entries) != set(stage_conditions)
            or set(output_condition_entries) != set(stage_conditions)
        ):
            raise SystemExit(
                f"stage {stage:03d} condition structure changed"
            )
        for entry_id, source_condition in source_condition_entries.items():
            if condition_actions[entry_id] != "translate":
                continue
            output_condition = output_condition_entries[entry_id]
            assert source_condition.pointer_offset is not None
            assert source_condition.text_offset is not None
            assert output_condition.pointer_offset is not None
            assert output_condition.text_offset is not None
            if output_condition.pointer_offset != source_condition.pointer_offset:
                raise SystemExit(
                    f"{entry_id} condition table pointer offset changed"
                )
            source_payload = encode_text(
                source_condition.text,
                source_table,
                terminate=True,
            )
            source_payload_match = source_payload in decoded.output
            original_offset_match = (
                decoded.output[
                    source_condition.text_offset :
                    source_condition.text_offset + len(source_payload)
                ]
                == source_payload
            )
            translated_condition_source_payload_checked_count += 1
            condition_source_payload_match_count += source_payload_match
            condition_original_offset_source_payload_match_count += (
                original_offset_match
            )
            if source_condition.ordinal > 0:
                dynamic_condition_variant_count += 1
                dynamic_condition_variant_stages.add(stage)
            if source_payload_match or original_offset_match:
                raise SystemExit(
                    f"{entry_id} retains its original condition payload"
                )
            expected_placeholder_count = (
                condition_runtime_name_placeholders.get(entry_id, 0)
            )
            if expected_placeholder_count:
                final_condition = decode_text(
                    decoded.output,
                    output_condition.text_offset,
                    stage_table,
                )
                final_payload = decoded.output[
                    output_condition.text_offset :
                    output_condition.text_offset + final_condition.consumed
                ]
                raw_placeholder_count = final_payload.count(b"\x3A")
                if (
                    source_condition.text.count(":")
                    != expected_placeholder_count
                    or stage_conditions[entry_id].count(":")
                    != expected_placeholder_count
                    or raw_placeholder_count != expected_placeholder_count
                ):
                    raise SystemExit(
                        f"{entry_id} runtime-name placeholder storage drift"
                    )
                condition_runtime_name_placeholder_entry_count += 1
                condition_runtime_name_placeholder_occurrence_count += (
                    raw_placeholder_count
                )
                if entry_id == "story/041/condition/01/02":
                    condition_runtime_name_placeholder_readback = {
                        "entry_id": entry_id,
                        "stage_index": stage,
                        "translation": stage_conditions[entry_id],
                        "stored_hex": final_payload.hex(),
                        "raw_0x3a_count": raw_placeholder_count,
                        "raw_placeholder_exact": True,
                    }
            if entry_id == reported_dynamic_condition_entry_id:
                reported_dynamic_condition_readback = {
                    "entry_id": entry_id,
                    "stage_index": stage,
                    "condition_table_pointer_offset": (
                        source_condition.pointer_offset
                    ),
                    "original_text_offset": source_condition.text_offset,
                    "final_text_offset": output_condition.text_offset,
                    "translation": stage_conditions[entry_id],
                    "final_table_readback_exact": (
                        output_condition.text == stage_conditions[entry_id]
                    ),
                    "exact_source_payload_absent_from_final_stage": True,
                    "original_offset_source_payload_absent": True,
                }
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
        source_speakers = {
            entry.speaker_id: entry.text
            for entry in source_parsed.entries
            if entry.kind == "speaker"
        }
        if set(output_entries) != set(source_entries):
            raise SystemExit(
                f"stage {stage:03d} dialogue structure changed"
            )
        stale_source_texts = {}
        stale_source_speakers = {}
        for source_entry in source_parsed.entries:
            if source_entry.kind == "condition":
                assert source_entry.text_offset is not None
                stale_source_texts[source_entry.entry_id] = decode_text(
                    source_decoded.output,
                    source_entry.text_offset,
                    stage_table,
                ).text
            elif source_entry.kind == "dialogue":
                assert source_entry.text_offset is not None
                source_prefix = decode_text(
                    source_decoded.output,
                    source_entry.text_offset,
                    source_table,
                    stop_at_newline=True,
                )
                translation_start = (
                    source_prefix.end
                    if source_prefix.terminator == "newline"
                    else source_entry.text_offset
                )
                stale_source_texts[source_entry.entry_id] = decode_text(
                    source_decoded.output,
                    translation_start,
                    stage_table,
                ).text
                if source_prefix.terminator == "newline":
                    stale_speaker = decode_text(
                        source_decoded.output,
                        source_entry.text_offset,
                        stage_table,
                        stop_at_newline=True,
                    ).text
                    previous = stale_source_speakers.setdefault(
                        source_entry.speaker_id,
                        stale_speaker,
                    )
                    if previous != stale_speaker:
                        raise SystemExit(
                            f"stage {stage:03d} stale-source speaker "
                            f"fingerprint conflict: {source_entry.speaker_id}"
                        )
        for source_speaker_entry in source_parsed.entries:
            if (
                source_speaker_entry.kind != "speaker"
                or source_speaker_entry.speaker_id in stale_source_speakers
            ):
                continue
            canonical_source_payload = encode_text(
                source_speaker_entry.text,
                source_table,
                terminate=True,
            )
            stale_source_speakers[source_speaker_entry.speaker_id] = (
                decode_text(
                    canonical_source_payload,
                    0,
                    stage_table,
                ).text
            )
        if set(stale_source_texts) != set(expected_texts):
            raise SystemExit(
                f"stage {stage:03d} stale-source text inventory drift"
            )
        output_speakers = {}
        for source_dialogue in source_entries.values():
            assert source_dialogue.text_offset is not None
            source_prefix = decode_text(
                source_decoded.output,
                source_dialogue.text_offset,
                source_table,
                stop_at_newline=True,
            )
            if source_prefix.terminator != "newline":
                continue
            output_dialogue = output_entries[source_dialogue.entry_id]
            assert output_dialogue.text_offset is not None
            output_speaker = decode_text(
                decoded.output,
                output_dialogue.text_offset,
                stage_table,
                stop_at_newline=True,
            ).text
            previous = output_speakers.setdefault(
                source_dialogue.speaker_id,
                output_speaker,
            )
            if previous != output_speaker:
                raise SystemExit(
                    f"stage {stage:03d} output speaker fingerprint "
                    f"conflict: {source_dialogue.speaker_id}"
                )
        for speaker_id, expected_speaker in stage_speakers.items():
            output_speakers.setdefault(speaker_id, expected_speaker)
        if (
            set(output_speakers) != set(stage_speakers)
            or set(stale_source_speakers) != set(stage_speakers)
        ):
            raise SystemExit(
                f"stage {stage:03d} stale-source speaker inventory drift"
            )
        for entry_id, expected_translation in expected_texts.items():
            stale_rendering = stale_source_texts[entry_id]
            actual_translation = actual_texts[entry_id]
            stale_stage_runtime_rendering_checked_count += 1
            if stale_rendering != expected_translation:
                stale_stage_runtime_rendering_distinct_fingerprint_count += 1
                if actual_translation == stale_rendering:
                    stale_stage_runtime_rendering_match_count += 1
        for speaker_id, expected_speaker in stage_speakers.items():
            stale_rendering = stale_source_speakers[speaker_id]
            actual_speaker = output_speakers[speaker_id]
            if actual_speaker != expected_speaker:
                raise SystemExit(
                    f"stage {stage:03d} speaker-table mismatch: "
                    f"{speaker_id}"
                )
            stale_stage_runtime_rendering_checked_count += 1
            if stale_rendering != expected_speaker:
                stale_stage_runtime_rendering_distinct_fingerprint_count += 1
                if actual_speaker == stale_rendering:
                    stale_stage_runtime_rendering_match_count += 1
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
            quote_verdict = evaluate_story_quote(
                source_entry.text,
                expected_translation,
                source_speakers[source_entry.speaker_id],
                has_keyword_links=("《" in source_entry.text),
            )
            dialogue_quote_style_counts[quote_verdict.expected] += 1
            if not quote_verdict.exact:
                raise SystemExit(
                    f"{entry_id} final-ISO outer punctuation mismatch: "
                    f"expected={quote_verdict.expected} "
                    f"actual={quote_verdict.actual}"
                )
            expected_payload = encode_stage_message(
                source_table,
                stage_overrides,
                entry_id=entry_id,
                source_text=source_entry.text,
                replacement=expected_translation,
                terminate=True,
            )
            actual_payload = decoded.output[
                translation_start : translation_start + len(expected_payload)
            ]
            if actual_payload != expected_payload:
                raise SystemExit(
                    f"{entry_id} encoded dialogue payload mismatch"
                )

            if entry_id in player_choice_entry_ids:
                rows = expected_translation.splitlines()
                if (
                    len(rows) != 3
                    or any(
                        not row.startswith("“") or not row.endswith("”")
                        for row in rows
                    )
                    or not rows[1].startswith("“1．")
                    or not rows[2].startswith("“2．")
                ):
                    raise SystemExit(
                        f"{entry_id} player-choice row structure drift"
                    )
                player_choice_readbacks[entry_id] = expected_translation
            if entry_id == reported_land_entry_id:
                reported_land_translation = expected_translation

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

            widths = dialogue_line_widths(
                expected_translation,
                stage_keyword_links=("《" in source_entry.text),
            )
            if (
                len(widths) > DEFAULT_MAX_LINES
                or max(widths, default=0) > DEFAULT_LINE_WIDTH
            ):
                raise SystemExit(
                    f"{entry_id} exceeds {DEFAULT_LINE_WIDTH}x"
                    f"{DEFAULT_MAX_LINES} dialogue layout: {widths!r}"
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
                "raw_space_target_count": stage_raw_space_target_count,
                "raw_space_count_zero": True,
                "raw_visible_ascii_glyph_count": (
                    stage_raw_visible_ascii_glyph_count
                ),
                "raw_visible_ascii_target_count": (
                    stage_raw_visible_ascii_target_count
                ),
                "raw_visible_ascii_count_zero": True,
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
    expected_quote_styles = source_config["translations"].get(
        "expected_dialogue_quote_styles"
    )
    if dict(sorted(dialogue_quote_style_counts.items())) != expected_quote_styles:
        raise SystemExit(
            "final ISO dialogue outer-punctuation coverage drift: "
            f"expected={expected_quote_styles} "
            f"actual={dict(sorted(dialogue_quote_style_counts.items()))}"
        )
    if set(story_ascii_storage_examples) != {"ZAFT", "PLANT"}:
        raise SystemExit(
            "final ISO story ASCII examples are incomplete: "
            f"{sorted(story_ascii_storage_examples)!r}"
        )
    if (
        stale_stage_runtime_rendering_checked_count != total_entries
        or stale_stage_runtime_rendering_match_count
    ):
        raise SystemExit(
            "final ISO stale STAGE/runtime-font audit failed: "
            f"checked={stale_stage_runtime_rendering_checked_count} "
            f"expected={total_entries} "
            f"matches={stale_stage_runtime_rendering_match_count}"
        )
    translated_condition_count = sum(
        action == "translate" for action in condition_actions.values()
    )
    if (
        translated_condition_source_payload_checked_count
        != translated_condition_count
        or condition_source_payload_match_count
        or condition_original_offset_source_payload_match_count
        or reported_dynamic_condition_readback is None
        or not reported_dynamic_condition_readback["final_table_readback_exact"]
        or condition_runtime_name_placeholder_entry_count
        != len(condition_runtime_name_placeholders)
        or condition_runtime_name_placeholder_occurrence_count
        != sum(condition_runtime_name_placeholders.values())
        or condition_runtime_name_placeholder_readback is None
    ):
        raise SystemExit(
            "final ISO dynamic-condition source-payload audit failed"
        )
    if set(player_choice_readbacks) != player_choice_entry_ids:
        raise SystemExit(
            "final ISO player-choice inventory mismatch: "
            f"{sorted(set(player_choice_readbacks) ^ player_choice_entry_ids)!r}"
        )
    expected_land_translation = (
        "“哦！把自己机器弄坏的那家伙，\n　罚你帮忙修理。”"
    )
    if reported_land_translation != expected_land_translation:
        raise SystemExit(
            "reported Land dialogue mismatch: "
            f"expected={expected_land_translation!r} "
            f"actual={reported_land_translation!r}"
        )

    compdata_report = verify_final_compdata(
        members["DATA/COMPDATA.BN"],
        members["SLPS_258.87"],
        source_table,
        compdata_table,
        surface_aliases,
    )
    fixed_formation_report = verify_stage_fixed_formation(
        stage_archive,
        hb,
        source_table,
        overview_table,
    )
    default_formation_report = verify_stage_default_formation(
        stage_archive,
        hb,
        source_table,
        overview_table,
    )
    compdata_report["remaining_ui"]["stage_fixed_formation"] = (
        fixed_formation_report
    )
    compdata_report["remaining_ui"]["stage_default_formation"] = (
        default_formation_report
    )
    compdata_report["remaining_ui"]["readback_exact"] = (
        compdata_report["remaining_ui"]["readback_exact"]
        and fixed_formation_report["readback_exact"]
        and default_formation_report["readback_exact"]
    )
    compdata_ascii_audit = compdata_report["ability_visible_ascii_audit"]
    ability_visible_ascii_audit = {
        "pilot_special_skills": compdata_ascii_audit[
            "pilot_special_skills"
        ],
        "mech_special_abilities": compdata_report["special_abilities"],
        "unit_mech_pilot_weapon_ui": compdata_ascii_audit[
            "unit_mech_pilot_weapon_ui"
        ],
        "weapon_special_effect_1": compdata_ascii_audit[
            "weapon_special_effect_1"
        ],
        "weapon_special_effect_labels": compdata_ascii_audit[
            "weapon_special_effect_labels"
        ],
        "weapon_special_effect_help": compdata_ascii_audit[
            "weapon_special_effect_help"
        ],
        "weapon_special_effect_2": nisv_effect_names,
        "runtime_control_tokens_excluded": True,
        "all_checked_fields_use_two_byte_visible_ascii": True,
    }
    for label, category in ability_visible_ascii_audit.items():
        if not isinstance(category, dict):
            continue
        if (
            category.get("raw_visible_ascii_glyph_count") != 0
            or category.get("raw_visible_ascii_target_count") != 0
            or category.get("raw_space_target_count") != 0
        ):
            raise SystemExit(
                f"{label} final-ISO single-byte storage audit failed"
            )

    srvc_data = members["BTL/SRVC.BIN"]
    srvc_offsets = parse_seg_offsets(
        members["BTL/SRVC.SEG"], len(srvc_data)
    )
    srvc_chunks = parse_srvc_archive(
        srvc_data, srvc_offsets, compdata_table
    )
    srvc_raw_space_record_count = 0
    srvc_raw_visible_ascii_glyph_count = 0
    srvc_raw_visible_ascii_record_count = 0
    srvc_pollution_record_count = 0
    for chunk in srvc_chunks:
        for record in chunk.records:
            payload = srvc_data[
                record.archive_text_start : record.archive_text_end
            ]
            srvc_raw_space_record_count += b"\x20" in payload
            raw_ascii = raw_visible_ascii_glyphs(payload)
            srvc_raw_visible_ascii_glyph_count += len(raw_ascii)
            srvc_raw_visible_ascii_record_count += bool(raw_ascii)
            srvc_pollution_record_count += "}]}  {" in record.text
    if (
        srvc_raw_space_record_count
        or srvc_raw_visible_ascii_glyph_count
        or srvc_pollution_record_count
    ):
        raise SystemExit(
            "final ISO SRVC contains unsafe raw visible ASCII, raw spaces, "
            "or JSON-fragment pollution"
        )
    visible_space_storage = {
        **compdata_report["visible_space_storage"],
        "keyword_field_count": runtime_keyword_space_report["field_count"],
        "keyword_raw_visible_space_count": runtime_keyword_space_report[
            "raw_visible_space_count"
        ],
        "keyword_two_byte_visible_space_count": runtime_keyword_space_report[
            "two_byte_visible_space_count"
        ],
        "story_raw_space_target_count": story_raw_space_target_count,
        "stage_overview_raw_space_entry_count": (
            overview_raw_space_entry_count
        ),
        "world_history_raw_space_entry_count": world_history_report[
            "raw_space_entry_count"
        ],
        "hsfc_raw_space_cell_count": hsfc_raw_space_cell_count,
        "srvc_raw_space_record_count": srvc_raw_space_record_count,
        "srvc_pollution_record_count": srvc_pollution_record_count,
        "raw_space_count_zero": True,
        "srvc_pollution_absent": True,
    }
    raw_visible_ascii_storage = {
        "story_glyph_count": story_raw_visible_ascii_glyph_count,
        "story_target_count": story_raw_visible_ascii_target_count,
        "world_history_glyph_count": world_history_report[
            "raw_visible_ascii_glyph_count"
        ],
        "world_history_entry_count": world_history_report[
            "raw_visible_ascii_entry_count"
        ],
        "srvc_glyph_count": srvc_raw_visible_ascii_glyph_count,
        "srvc_record_count": srvc_raw_visible_ascii_record_count,
        "special_ability_glyph_count": compdata_report[
            "special_abilities"
        ]["raw_visible_ascii_glyph_count"],
        "special_ability_target_count": compdata_report[
            "special_abilities"
        ]["raw_visible_ascii_target_count"],
        "pilot_skill_glyph_count": ability_visible_ascii_audit[
            "pilot_special_skills"
        ]["raw_visible_ascii_glyph_count"],
        "pilot_skill_target_count": ability_visible_ascii_audit[
            "pilot_special_skills"
        ]["raw_visible_ascii_target_count"],
        "unit_mech_pilot_weapon_ui_glyph_count": (
            ability_visible_ascii_audit["unit_mech_pilot_weapon_ui"][
                "raw_visible_ascii_glyph_count"
            ]
        ),
        "unit_mech_pilot_weapon_ui_target_count": (
            ability_visible_ascii_audit["unit_mech_pilot_weapon_ui"][
                "raw_visible_ascii_target_count"
            ]
        ),
        "weapon_effect_1_glyph_count": ability_visible_ascii_audit[
            "weapon_special_effect_1"
        ]["raw_visible_ascii_glyph_count"],
        "weapon_effect_1_target_count": ability_visible_ascii_audit[
            "weapon_special_effect_1"
        ]["raw_visible_ascii_target_count"],
        "weapon_effect_help_glyph_count": ability_visible_ascii_audit[
            "weapon_special_effect_help"
        ]["raw_visible_ascii_glyph_count"],
        "weapon_effect_help_target_count": ability_visible_ascii_audit[
            "weapon_special_effect_help"
        ]["raw_visible_ascii_target_count"],
        "weapon_effect_2_glyph_count": ability_visible_ascii_audit[
            "weapon_special_effect_2"
        ]["raw_visible_ascii_glyph_count"],
        "weapon_effect_2_target_count": ability_visible_ascii_audit[
            "weapon_special_effect_2"
        ]["raw_visible_ascii_target_count"],
        "runtime_substitution_tokens_excluded": True,
        "all_stored_visible_ascii_uses_two_byte_glyphs": True,
    }

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
            f"Independent final-ISO readback of all {len(stages)} selected "
            f"story chunks and {total_entries:,} dialogue, condition, and "
            "speaker entries, "
            "plus reviewed save/load overviews, pilot-name, button-prompt, "
            "title-idle work-title and speaker-name overlays, "
            f"{DEFAULT_LINE_WIDTH}x{DEFAULT_MAX_LINES} layout, runtime-token, "
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
        "post_release_runtime_surfaces": post_release_runtime_surfaces,
        "issue_036_tutorial": issue_036_tutorial,
        "weapon_special_effect_2": weapon_effect_2_readback,
        "runtime_full_name_order": full_name_order_readback,
        "postgame_mode_unlock": postgame_mode_unlock_readback,
        "runtime_movement_type_labels": movement_type_readback,
        "runtime_weapon_category_labels": weapon_category_readback,
        "search_tab_alignment": search_tab_alignment_readback,
        "intermission_library_alignment": (
            intermission_library_alignment_readback
        ),
        "remaining_squad_count_alignment": (
            remaining_squad_count_alignment_readback
        ),
        "dialogue_layout": {
            "line_width_limit": DEFAULT_LINE_WIDTH,
            "line_count_limit": DEFAULT_MAX_LINES,
            "maximum_line_width": maximum_dialogue_line_width,
            "maximum_line_count": maximum_dialogue_line_count,
            "all_dialogue_within_limit": True,
        },
        "dialogue_outer_punctuation": {
            "policy": "source-driven; runtime keyword records are exempt",
            "style_counts": dict(sorted(dialogue_quote_style_counts.items())),
            "all_dialogue_outer_punctuation_exact": True,
        },
        "library": {
            "robot_entry_count": 321,
            "character_entry_count": 411,
            "glossary_entry_count": 52,
            "total_entry_count": 784,
            **library_translation,
            "component_acceptance": library_acceptance,
            "main_menu": library_menu_readback,
            "sound_select": sound_select_readback,
            "default_unlock": library_unlock_readback,
            "scenario_chart_title_readback": (
                scenario_chart_title_readback
            ),
            "iso_member_bytes_exact": True,
            "semantic_reread_transitive_through_exact_component_bytes": True,
        },
        "runtime_substitution_tokens": {
            "entry_count": runtime_token_entry_count,
            "occurrence_count": runtime_token_occurrence_count,
            "raw_ascii_exact": True,
        },
        "stale_stage_runtime_rendering_audit": {
            "method": (
                "decode original STAGE text through the final release table "
                "and reject any matching final-ISO rendering"
            ),
            "checked_entry_count": (
                stale_stage_runtime_rendering_checked_count
            ),
            "distinct_stale_fingerprint_count": (
                stale_stage_runtime_rendering_distinct_fingerprint_count
            ),
            "stale_fingerprint_match_count": (
                stale_stage_runtime_rendering_match_count
            ),
            "all_distinct_stale_source_renderings_absent": True,
        },
        "dynamic_condition_update_audit": {
            "method": (
                "check every translated condition variant against the final "
                "decoded STAGE, including its original direct text offset"
            ),
            "translated_condition_count": (
                translated_condition_source_payload_checked_count
            ),
            "dynamic_variant_count": dynamic_condition_variant_count,
            "dynamic_variant_stage_count": len(
                dynamic_condition_variant_stages
            ),
            "exact_source_payload_match_count": (
                condition_source_payload_match_count
            ),
            "original_offset_source_payload_match_count": (
                condition_original_offset_source_payload_match_count
            ),
            "reported_impulse_entry_update": (
                reported_dynamic_condition_readback
            ),
            "runtime_name_placeholder_entry_count": (
                condition_runtime_name_placeholder_entry_count
            ),
            "runtime_name_placeholder_occurrence_count": (
                condition_runtime_name_placeholder_occurrence_count
            ),
            "reported_episode_21_placeholder": (
                condition_runtime_name_placeholder_readback
            ),
            "all_runtime_name_placeholders_raw_0x3a": True,
            "all_translated_condition_source_payloads_absent": True,
        },
        "visible_ascii_policy": {
            **visible_ascii_policy,
            "story_storage_examples": story_ascii_storage_examples,
            "story_storage_examples_exact": True,
        },
        "visible_space_storage": visible_space_storage,
        "raw_visible_ascii_storage": raw_visible_ascii_storage,
        "ability_visible_ascii_audit": ability_visible_ascii_audit,
        "player_choice_records": {
            "entry_count": len(player_choice_readbacks),
            "entry_ids": sorted(player_choice_readbacks),
            "three_runtime_rows_exact": True,
            "title_option_1_option_2_structure_exact": True,
            "readback_exact": True,
        },
        "reported_land_dialogue": {
            "entry_id": reported_land_entry_id,
            "translation": reported_land_translation,
            "encoded_payload_readback_exact": True,
        },
        "stage_system_dialogue": stage_system_dialogue_report,
        "stage_scenario_chart_prompts": stage_scenario_chart_prompt_report,
        "compdata": compdata_report,
        "scenario_select_effect": scenario_select_effect,
        "mode_select_effect": mode_select_effect,
        "nisv_strategy_qa": nisv_strategy_qa,
        "nisv_effect_names": nisv_effect_names,
        "auto_demo_overlays": auto_demo_overlays,
        "world_history": world_history_report,
        "runtime_keywords": runtime_keyword_report,
        "stage_overviews": overview_report,
        "hsfc_overviews": hsfc_report,
        "scenario_chart_title_readback": scenario_chart_title_readback,
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
            "runtime_full_name_order_route_specific": (
                full_name_order_readback[
                    "all_instruction_replacements_exact"
                ]
                and full_name_order_readback["changed_byte_count"] == 0
                and full_name_order_readback["component_receipt_exact"]
                and full_name_order_readback["route_values"]
                == {"rand": 0, "setsuko": 1}
                and full_name_order_readback["output_orders"]
                == {
                    "rand": "given_middle_dot_family",
                    "setsuko": "family_given",
                }
            ),
            "runtime_movement_type_labels_simplified": (
                movement_type_readback["site_count"] == 2
                and movement_type_readback["changed_byte_count"] == 0
                and movement_type_readback["component_receipt_exact"]
                and movement_type_readback["all_materialization_sequences_exact"]
                and movement_type_readback["all_replacements_exact"]
                and [
                    site["translation"]
                    for site in movement_type_readback["sites"]
                ]
                == ["空专用", "陆专用"]
                and movement_type_readback["preserved_parallel_type"][
                    "preserved_byte_exact"
                ]
            ),
            "runtime_weapon_category_labels_simplified": (
                weapon_category_readback["site_count"] == 2
                and weapon_category_readback["changed_byte_count"] == 0
                and weapon_category_readback["component_receipt_exact"]
                and weapon_category_readback[
                    "all_matching_weapon_instances_covered_by_shared_branches"
                ]
                and weapon_category_readback[
                    "all_materialization_sequences_exact"
                ]
                and weapon_category_readback["all_replacements_exact"]
                and [
                    site["translation"]
                    for site in weapon_category_readback["sites"]
                ]
                == ["格斗武器（　　）", "射击武器（　　）"]
            ),
            "search_tab_five_label_alignment_exact": (
                search_tab_alignment_readback["surface_count"] == 5
                and search_tab_alignment_readback["center_byte_hex"] == "0F"
                and search_tab_alignment_readback["changed_byte_count"] == 0
                and search_tab_alignment_readback["all_replacements_exact"]
                and search_tab_alignment_readback["component_receipt_exact"]
            ),
            "intermission_library_robot_encyclopedia_centered": (
                intermission_library_alignment_readback["entry_count"] == 6
                and intermission_library_alignment_readback["replacement_x"]
                == -100
                and intermission_library_alignment_readback["shift_pixels"] == -10
                and intermission_library_alignment_readback["changed_byte_count"]
                == 0
                and intermission_library_alignment_readback[
                    "changed_bytes_confined_to_target_coordinate"
                ]
                and intermission_library_alignment_readback[
                    "pointer_table_preserved"
                ]
                and intermission_library_alignment_readback[
                    "sibling_rows_preserved"
                ]
                and intermission_library_alignment_readback[
                    "target_tail_preserved"
                ]
                and intermission_library_alignment_readback[
                    "component_receipt_exact"
                ]
            ),
            "remaining_squad_count_spacing_exact": (
                remaining_squad_count_alignment_readback["shift_pixels"] == 8
                and remaining_squad_count_alignment_readback[
                    "changed_byte_count"
                ]
                == 0
                and remaining_squad_count_alignment_readback[
                    "adjacent_coordinates_preserved"
                ]
                and remaining_squad_count_alignment_readback[
                    "format_token_untouched"
                ]
                and remaining_squad_count_alignment_readback[
                    "instruction_replacement_exact"
                ]
                and remaining_squad_count_alignment_readback[
                    "component_receipt_exact"
                ]
            ),
            "reviewed_library_components_exact": (
                library_translation.get("unique_text_count") == 2709
                and library_translation.get("field_reference_count") == 4921
                and library_menu_readback[
                    "fixed_index_rectangles_reread_exact"
                ]
                and sound_select_readback[
                    "fixed_title_rectangle_reread_exact"
                ]
                and sound_select_readback["alpha_mask_preserved"]
                and sound_select_readback[
                    "background_restore_crosses_no_transparent_pixels"
                ]
                and sound_select_readback["non_title_pixels_byte_exact"]
                and sound_select_readback[
                    "clut_and_tim2_metadata_byte_exact"
                ]
                and scenario_chart_title_readback[
                    "alpha_mask_preserved"
                ]
                and scenario_chart_title_readback[
                    "translated_title_reread_exact"
                ]
                and sound_select_readback["track_titles_byte_exact"]
                and sound_select_readback["track_title_count"] == 101
                and sound_select_readback["default_unlock"][
                    "instruction_replacement_exact"
                ]
                and sound_select_readback["default_unlock"]["metadata"][
                    "default_unlocked_track_count"
                ]
                == 101
                and sound_select_readback["default_unlock"]["metadata"][
                    "empty_sentinel_excluded"
                ]
                and library_unlock_readback[
                    "all_instruction_replacements_exact"
                ]
                and library_unlock_readback[
                    "save_writeback_functions_unchanged"
                ]
                and library_unlock_readback["surface_count"] == 4
                and all(library_acceptance.values())
            ),
            "runtime_keyword_surfaces_exact": (
                runtime_keyword_report["all_three_runtime_surfaces_exact"]
                and runtime_keyword_report["authority_keyword_count"] == 52
                and runtime_keyword_compdata_report["list_label_count"] == 52
                and runtime_keyword_compdata_report["relocation_count"] == 2
                and runtime_keyword_compdata_report["changed_byte_count"] == 0
                and runtime_keyword_stage_report["record_count"] == 77
                and runtime_keyword_stage_report["stage_chunk_count"] == 44
                and runtime_keyword_stage_report["field_reference_count"] == 308
                and runtime_keyword_stage_report["allocation_count"] == 233
                and runtime_keyword_stage_report["relocation_count"] == 3
                and runtime_keyword_stage_report[
                    "all_four_fields_match_library"
                ]
            ),
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
            "mode_select_title_texture_exact": (
                mode_select_effect["source_title_texture_replaced"]
                and mode_select_effect["all_label_segments_nonblank"]
                and mode_select_effect[
                    "all_label_segments_native_4bpp_antialiased"
                ]
                and mode_select_effect["archive_offsets_preserved"]
            ),
            "nisv_effect_names_exact": (
                nisv_effect_names["translated_reread_exact"]
                and nisv_effect_names["archive_offsets_preserved"]
                and nisv_effect_names["all_source_occurrences_absent"]
            ),
            "nisv_strategy_qa_exact": (
                nisv_strategy_qa["metadata_string_count"] == 264
                and nisv_strategy_qa["page_count"] == 102
                and nisv_strategy_qa["text_record_count"] == 2609
                and nisv_strategy_qa["allocation_table_preserved"]
                and nisv_strategy_qa["metadata_indexes_preserved"]
                and nisv_strategy_qa["page_allocations_preserved"]
                and nisv_strategy_qa["record_styles_preserved"]
                and nisv_strategy_qa["record_z_coordinates_preserved"]
                and nisv_strategy_qa["mixed_style_line_flow"]
                and nisv_strategy_qa["empty_continuation_rows_collapsed"]
                and nisv_strategy_qa["fixed_column_anchors_aligned"]
                and not nisv_strategy_qa["empty_records_extend_scroll_height"]
                and nisv_strategy_qa["sprite_sections_preserved"]
                and nisv_strategy_qa["archive_offsets_preserved"]
                and nisv_strategy_qa["codec_padding_zero"]
                and nisv_strategy_qa["translated_reread_exact"]
            ),
            "issue_036_tutorial_exact": (
                issue_036_tutorial["page_title_count"] == 10
                and issue_036_tutorial["body_page_count"] == 10
                and issue_036_tutorial["body_record_count"] == 114
                and issue_036_tutorial["title_effect_count"] == 4
                and issue_036_tutorial["title_picture_count"] == 16
                and issue_036_tutorial["event_binding"][
                    "all_four_effects_referenced"
                ]
                and issue_036_tutorial["translated_reread_exact"]
            ),
            "auto_demo_overlays_exact": (
                auto_demo_overlays["title_entry_count"] == 22
                and auto_demo_overlays["name_slot_count"] == 63
                and auto_demo_overlays["unique_name_source_count"] == 59
                and auto_demo_overlays["fixed_field_padding_all_zero"]
                and auto_demo_overlays["unknown_code_count"] == 0
                and auto_demo_overlays["translated_reread_exact"]
                and auto_demo_overlays["kamille_name"]["translation"]
                == "卡缪"
            ),
            "hb_stage_offsets_valid": True,
            "default_formation_names_exact": (
                default_formation_report["group_count"]
                == full_component_config["remaining_ui"]["expected"][
                    "stage_default_formation_group_count"
                ]
                and default_formation_report["stage_count"]
                == full_component_config["remaining_ui"]["expected"][
                    "stage_default_formation_stage_count"
                ]
                and default_formation_report["entry_count"]
                == full_component_config["remaining_ui"]["expected"][
                    "stage_default_formation_entry_count"
                ]
                and default_formation_report["unique_source_count"]
                == full_component_config["remaining_ui"]["expected"][
                    "stage_default_formation_unique_source_count"
                ]
                and default_formation_report["record_metadata_count"]
                == full_component_config["remaining_ui"]["expected"][
                    "stage_default_formation_record_metadata_count"
                ]
                and default_formation_report["inventory_sha256"]
                == full_component_config["remaining_ui"]["expected"][
                    "stage_default_formation_inventory_sha256"
                ]
                and default_formation_report[
                    "record_metadata_preserved_byte_exact"
                ]
                and default_formation_report["readback_exact"]
            ),
            "encoded_streams_exact": True,
            "decoded_sizes_exact": True,
            "archive_padding_zero": True,
            "entry_id_sets_exact": True,
            "dialogue_conditions_speakers_exact": True,
            "stale_stage_runtime_rendering_count_zero": (
                stale_stage_runtime_rendering_checked_count == total_entries
                and stale_stage_runtime_rendering_match_count == 0
            ),
            "dynamic_condition_updates_exact": (
                translated_condition_source_payload_checked_count
                == translated_condition_count
                and condition_source_payload_match_count == 0
                and condition_original_offset_source_payload_match_count == 0
                and reported_dynamic_condition_readback is not None
                and reported_dynamic_condition_readback[
                    "final_table_readback_exact"
                ]
            ),
            "stage_system_dialogue_stale_rendering_count_zero": (
                stage_system_dialogue_report["record_count"] == 379
                and stage_system_dialogue_report[
                    "stale_fingerprint_match_count"
                ]
                == 0
                and stage_system_dialogue_report[
                    "translated_readback_exact"
                ]
            ),
            "stage_scenario_chart_prompts_exact": (
                stage_scenario_chart_prompt_report["entry_count"] == 3
                and stage_scenario_chart_prompt_report[
                    "fixed_spans_preserved"
                ]
                and stage_scenario_chart_prompt_report[
                    "zero_padding_preserved"
                ]
                and stage_scenario_chart_prompt_report[
                    "translated_readback_exact"
                ]
            ),
            "player_choice_records_exact": (
                len(player_choice_readbacks) == len(player_choice_entry_ids)
            ),
            "reported_land_dialogue_exact": (
                reported_land_translation == expected_land_translation
            ),
            "unknown_code_count_zero": True,
            "translation_entry_count_exact": total_entries
            == expected_entry_count,
            "dialogue_layout_21x3_exact": (
                maximum_dialogue_line_width <= DEFAULT_LINE_WIDTH
                and maximum_dialogue_line_count <= DEFAULT_MAX_LINES
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
            "raw_visible_space_count_zero": visible_space_storage[
                "raw_space_count_zero"
            ],
            "raw_visible_ascii_glyph_count_zero": (
                raw_visible_ascii_storage["story_glyph_count"] == 0
                and raw_visible_ascii_storage["story_target_count"] == 0
                and raw_visible_ascii_storage["world_history_glyph_count"]
                == 0
                and raw_visible_ascii_storage["world_history_entry_count"]
                == 0
                and raw_visible_ascii_storage["srvc_glyph_count"] == 0
                and raw_visible_ascii_storage["srvc_record_count"] == 0
                and raw_visible_ascii_storage[
                    "special_ability_glyph_count"
                ]
                == 0
                and raw_visible_ascii_storage[
                    "special_ability_target_count"
                ]
                == 0
                and raw_visible_ascii_storage["pilot_skill_glyph_count"] == 0
                and raw_visible_ascii_storage["pilot_skill_target_count"] == 0
                and raw_visible_ascii_storage[
                    "unit_mech_pilot_weapon_ui_glyph_count"
                ]
                == 0
                and raw_visible_ascii_storage[
                    "unit_mech_pilot_weapon_ui_target_count"
                ]
                == 0
                and raw_visible_ascii_storage[
                    "weapon_effect_1_glyph_count"
                ]
                == 0
                and raw_visible_ascii_storage[
                    "weapon_effect_1_target_count"
                ]
                == 0
                and raw_visible_ascii_storage[
                    "weapon_effect_help_glyph_count"
                ]
                == 0
                and raw_visible_ascii_storage[
                    "weapon_effect_help_target_count"
                ]
                == 0
                and raw_visible_ascii_storage[
                    "weapon_effect_2_glyph_count"
                ]
                == 0
                and raw_visible_ascii_storage[
                    "weapon_effect_2_target_count"
                ]
                == 0
            ),
            "ability_visible_ascii_storage_exact": (
                ability_visible_ascii_audit[
                    "all_checked_fields_use_two_byte_visible_ascii"
                ]
            ),
            "srvc_json_fragment_pollution_absent": visible_space_storage[
                "srvc_pollution_absent"
            ],
            "story_ascii_storage_examples_exact": True,
            "pilot_names_exact": compdata_report["readback_exact"],
            "unit_names_exact": compdata_report["unit_names"][
                "readback_exact"
            ],
            "unit_name_spaces_two_byte_exact": compdata_report[
                "unit_names"
            ]["two_byte_spaces_exact"],
            "unit_name_pointer_relocations_exact": compdata_report[
                "unit_names"
            ]["pointer_relocations_exact"],
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
            "weapon_special_effect_2_exact": (
                weapon_effect_2_readback["entry_count"] == 2
                and weapon_effect_2_readback["all_translated_reread_exact"]
                and weapon_effect_2_readback["control_flow_preserved"]
                and weapon_effect_2_readback["executable_size_preserved"]
                and weapon_effect_2_readback["changed_byte_count"] == 0
            ),
            "library_runtime_text_exact": compdata_report[
                "library_regressions"
            ]["runtime_text_readback_exact"],
            "all_confirm_prompts_use_localized_glyphs": (
                compdata_report["library_regressions"][
                    "confirm_prompts_readback_exact"
                ]
                and compdata_report["library_regressions"][
                    "raw_decision_glyph_absent"
                ]
            ),
            "compdata_battle_lines_exact": (
                compdata_report["battle_lines"]["corpus_entry_count"] == 297
                and compdata_report["battle_lines"][
                    "target_occurrence_count"
                ]
                == 511
                and compdata_report["battle_lines"]["unique_target_count"]
                == 297
                and compdata_report["battle_lines"][
                    "target_offset_readback_exact"
                ]
            ),
            "stage_overviews_exact": overview_report[
                "translated_readback_exact"
            ]
            and overview_report["fixed_pointer_entries_exact"]
            and overview_report["layout_policy_exact"]
            and overview_report["line_width_limit"] == 29
            and overview_report["maximum_output_line_width"] <= 29,
            "world_history_exact": (
                world_history_report["translated_readback_exact"]
                and world_history_report[
                    "logical_ascii_and_digits_preserved"
                ]
                and world_history_report["two_byte_visible_spaces_exact"]
                and world_history_report["archive_offsets_exact"]
            ),
            "hsfc_overviews_exact": hsfc_report[
                "translated_readback_exact"
            ]
            and hsfc_report["fixed_record_cells_exact"],
            "scenario_chart_title_alpha_preserving_writeback_exact": (
                scenario_chart_title_readback[
                    "alpha_mask_preserved"
                ]
                and scenario_chart_title_readback[
                    "background_restore_crosses_no_transparent_pixels"
                ]
                and scenario_chart_title_readback[
                    "non_title_pixels_byte_exact"
                ]
                and scenario_chart_title_readback[
                    "clut_and_tim2_metadata_byte_exact"
                ]
                and scenario_chart_title_readback[
                    "translated_title_reread_exact"
                ]
            ),
            "sound_select_title_alpha_preserving_writeback_exact": (
                sound_select_readback["alpha_mask_preserved"]
                and sound_select_readback[
                    "background_restore_crosses_no_transparent_pixels"
                ]
                and sound_select_readback["non_title_pixels_byte_exact"]
                and sound_select_readback[
                    "clut_and_tim2_metadata_byte_exact"
                ]
                and sound_select_readback[
                    "fixed_title_rectangle_reread_exact"
                ]
            ),
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
