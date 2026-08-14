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
    formation_inventory_sha256,
    load_locked_stage_default_formations,
)
from srwz.summary import parse_summary
from srwz.tim2 import scan_tim2
from srwz.tim2_writeback import unswizzle_psmt8
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
        "female_default_name": "节子·小原",
        "male_profile": (
            "与搭档在荒野经营修理店的男人"
            "自称烈焰豪爽而热血但有时会热情过头"
        ),
        "male_default_unit_name": "钢狮子",
        "female_default_unit_name": "巴尔戈拉",
        "formation_action_labels": "攻击反击参与攻击",
        "formation_names": "三角中央广域",
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
    for item in terms:
        source_encoded = encode_text(
            item["source"], source_table, terminate=False
        )
        translation = normalize_original_fullwidth_ascii(item["translation"])
        decoded_offsets = [int(value, 0) for value in item["decoded_offsets"]]
        for offset in decoded_offsets:
            actual = decode_text(decoded.output, offset, output_table)
            if not actual.text.startswith(translation + "\u3000") or (
                decoded.output[offset : offset + len(source_encoded)]
                == source_encoded
            ):
                raise SystemExit(
                    "final ISO NisVData effect-name mismatch at "
                    f"0x{offset:X}"
                )
        term_reports.append(
            {
                "source": item["source"],
                "translation": translation,
                "decoded_offsets": decoded_offsets,
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
        "translated_reread_exact": True,
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
    ):
        raise SystemExit("default formation-name inventory drift")

    offsets = read_executable_archive_offsets(
        hb, STAGE_OFFSET_SPEC, len(stage)
    )
    decoded_by_stage = {}
    original_by_stage = {}
    minimum_headroom = None
    translations = set()
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
    return {
        "group_count": len(groups),
        "stage_count": len(decoded_by_stage),
        "stage_indices": sorted(decoded_by_stage),
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
        "0x33E318": "节子·小原",
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
        "0x345DC8": "三角",
        "0x345DD0": "中央",
        "0x345DE0": "广域",
    }
    if {
        offset: remaining_document["slps_by_offset"].get(offset)
        for offset in map_formation_name_expectations
    } != map_formation_name_expectations:
        raise SystemExit("map formation-name offset contract drift")
    squad_formation_name_expectations = {
        "0x7F580": "三角队形",
        "0x7F5A0": "中央队形",
        "0x7F5C0": "广域队形",
        "0x7F5E0": "三角",
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
    if (
        not isinstance(sound_select_component, dict)
        or sound_select_component.get("sound_select_title_written") is not True
    ):
        raise SystemExit("final ISO sound-select component proof is incomplete")
    sound_stored = nisvdata[
        int(sound_target["stored_start"]):int(sound_target["stored_end"])
    ]
    decoded_sound = decode(sound_stored)
    if any(sound_stored[decoded_sound.consumed:]):
        raise SystemExit("final ISO sound-select padding is nonzero")
    sound_records = scan_tim2(decoded_sound.output)
    sound_record_index = int(sound_target["record_index"])
    if not 0 <= sound_record_index < len(sound_records):
        raise SystemExit("final ISO sound-select TIM2 record is missing")
    sound_record = sound_records[sound_record_index]
    sound_picture = sound_record.pictures[0]
    sound_image_start = sound_picture.offset + sound_picture.header_size
    sound_image_end = sound_image_start + sound_picture.image_size
    logical_sound = unswizzle_psmt8(
        decoded_sound.output[sound_image_start:sound_image_end],
        sound_picture.width,
        sound_picture.height,
    )
    sound_labels = sound_select_component.get("labels")
    if (
        sound_record.offset != sound_select_component.get("record_offset")
        or sha256_bytes(
            decoded_sound.output[sound_record.offset:sound_record.end]
        )
        != sound_select_component.get("output_record_sha256")
        or sha256_bytes(logical_sound)
        != sound_select_component.get("output_logical_indexes_sha256")
        or not isinstance(sound_labels, list)
        or len(sound_labels) != 1
    ):
        raise SystemExit("final ISO sound-select texture readback drift")
    sound_label = sound_labels[0]
    sound_crop = b"".join(
        logical_sound[
            (int(sound_label["y"]) + row) * sound_picture.width
            + int(sound_label["x"]):
            (int(sound_label["y"]) + row) * sound_picture.width
            + int(sound_label["x"])
            + int(sound_label["width"])
        ]
        for row in range(int(sound_label["height"]))
    )
    if (
        sha256_bytes(sound_crop) != sound_label.get("output_indexes_sha256")
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
    sound_select_readback = {
        "member": "DATA/NISVDATA.BIN",
        "chunk_index": int(sound_target["chunk_index"]),
        "record_index": sound_record_index,
        "record_offset": sound_record.offset,
        "record_size": sound_record.size,
        "record_sha256": sound_select_component["output_record_sha256"],
        "title": sound_label["translation"],
        "title_output_indexes_sha256": sound_label[
            "output_indexes_sha256"
        ],
        "track_title_count": len(sound_titles),
        "track_title_span_sha256": sound_span.expected_span_sha256,
        "track_titles_byte_exact": True,
        "fixed_title_rectangle_reread_exact": True,
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
    nisv_effect_names = verify_nisv_effect_names(
        slps,
        members["DATA/NISVDATA.BIN"],
        source_table,
        compdata_table,
        component_manifest,
    )
    stage_overrides = dict(overrides)
    stage_overrides.update(surface_aliases)
    stage_overrides.update(ascii_overrides)
    stage_table = project_runtime_text_table(
        source_table,
        stage_overrides,
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
    reported_dynamic_condition_entry_id = "story/002/condition/00/01"
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
            "all_translated_condition_source_payloads_absent": True,
        },
        "visible_ascii_policy": {
            **visible_ascii_policy,
            "story_storage_examples": story_ascii_storage_examples,
            "story_storage_examples_exact": True,
        },
        "visible_space_storage": visible_space_storage,
        "raw_visible_ascii_storage": raw_visible_ascii_storage,
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
        "compdata": compdata_report,
        "scenario_select_effect": scenario_select_effect,
        "mode_select_effect": mode_select_effect,
        "nisv_effect_names": nisv_effect_names,
        "auto_demo_overlays": auto_demo_overlays,
        "world_history": world_history_report,
        "runtime_keywords": runtime_keyword_report,
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
            "reviewed_library_components_exact": (
                library_translation.get("unique_text_count") == 2709
                and library_translation.get("field_reference_count") == 4921
                and library_menu_readback[
                    "fixed_index_rectangles_reread_exact"
                ]
                and sound_select_readback[
                    "fixed_title_rectangle_reread_exact"
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
            and overview_report["fixed_pointer_entries_exact"],
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
