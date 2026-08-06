#!/usr/bin/env python3
"""Independently reread every selected Chinese story entry from the final ISO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.archive import sha256_file
from srwz.chinese_layout import dialogue_line_widths
from srwz.codec import decode
from srwz.display_names import load_display_name_source, parse_display_names
from srwz.font import (
    GLYPH_SIZE,
    ascii_glyph_index,
    decode_vt1_font_segment,
    sha256_bytes,
    standard_glyph_index,
)
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.menu import parse_menu_file
from srwz.stage import parse_stage, read_stage_function_addresses
from srwz.text import (
    ORIGINAL_FULLWIDTH_ASCII,
    RUNTIME_SUBSTITUTION_TOKEN,
    TextTable,
    decode_text,
    encode_text,
    load_text_table,
    normalize_original_fullwidth_ascii,
    original_fullwidth_ascii_overrides,
)
from srwz.ui_menu import project_ui_runtime_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = (
    PROJECT_ROOT
    / "build/iso/ui-p10-full-story/srwz-ui-p10-full-story.iso"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "work/verification/full-story-iso-content.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "manifests/full-story-iso-content-validation.json"
)
BUILD_CONFIG = PROJECT_ROOT / "config/iso/ui-p10-full-story-build.json"
COMPONENT_REPORT = (
    PROJECT_ROOT
    / "work/build/full-story-stage/components/component-validation.json"
)
FONT_MANIFEST = PROJECT_ROOT / "manifests/full-story-font-validation.json"
SOURCE_CONTENT_CONFIG = (
    PROJECT_ROOT / "config/canary/complete-content.json"
)
SOURCE_FONT_CONFIG = (
    PROJECT_ROOT / "config/canary/minimal-slps-font.json"
)
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
BASE_CODEBOOK = PROJECT_ROOT / "config/encoding/codebook.json"
CODEBOOK_PROPOSAL = (
    PROJECT_ROOT / "work/writeback/full-story-codebook-proposal.json"
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


def load_overrides() -> tuple[dict[str, int], dict[str, int]]:
    base = json.loads(BASE_CODEBOOK.read_text(encoding="utf-8"))
    proposal = json.loads(CODEBOOK_PROPOSAL.read_text(encoding="utf-8"))
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
    if (
        alias_report.get("all_selected_assignments") is not True
        or alias_report.get("unaliased_conditional_assignment_count") != 0
        or set(aliases) != conditional_characters
        or any(0x8140 <= code < 0x889F for code in aliases.values())
    ):
        raise SystemExit("global safe-alias proposal contract failed")
    return overrides, aliases


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
        spec = source_config["inputs"][name]
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


def verify_final_compdata(
    stored_compdata: bytes,
    output_table: TextTable,
    surface_aliases: dict[str, int],
) -> dict:
    """Reread selected pilot names and the two reported button prompts."""

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
    by_source: dict[str, str] = {}
    for entry in speaker_document["entries"]:
        translation = normalize_original_fullwidth_ascii(
            entry["translation"]
        )
        if not translation:
            continue
        source_hash = entry["source_text_sha256"]
        previous = by_source.setdefault(source_hash, translation)
        if previous != translation:
            raise SystemExit(
                f"conflicting pilot-name translation: {source_hash}"
            )

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
        len(by_source) != expected["unique_source_count"]
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
        "readback_exact": True,
        "examples": examples,
        "button_prompts": button_prompts,
        "button_prompts_exact": True,
        "unit_ascii_storage_examples": unit_ascii_storage_examples,
        "unit_ascii_storage_examples_exact": True,
        "surface_safe_alias_count": len(surface_aliases),
        "surface_safe_aliases_readback_exact": True,
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
    component = json.loads(
        project_path(args.component_report).read_text(encoding="utf-8")
    )
    font_manifest = json.loads(
        project_path(args.font_manifest).read_text(encoding="utf-8")
    )
    source_config = json.loads(
        SOURCE_CONTENT_CONFIG.read_text(encoding="utf-8")
    )
    stages = tuple(component["stage_indices"])
    if len(stages) != len(set(stages)) or tuple(sorted(stages)) != stages:
        raise SystemExit("full-story stage selection is not unique and sorted")

    expected_replacements = {
        item["member"]: item for item in config["replacements"]
    }
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
    expected_font = font_manifest["font_component"]
    if (
        decoded_font.consumed != expected_font["encoded_size"]
        or len(decoded_font.output) != expected_font["decoded_size"]
        or sha256_bytes(decoded_font.output) != expected_font["decoded_sha256"]
        or any(font_padding)
    ):
        raise SystemExit("final ISO font chunk mismatch")

    source_table = load_text_table(TEXT_TABLE)
    overrides, surface_aliases = load_overrides()
    table = project_ui_runtime_text_table(source_table, overrides)
    compdata_table = project_ui_runtime_text_table(table, surface_aliases)
    ascii_overrides = original_fullwidth_ascii_overrides(source_table)
    visible_ascii_policy = verify_stock_ascii_glyphs(
        source_table,
        ascii_overrides,
        decoded_font.output,
    )
    compdata_table = project_ui_runtime_text_table(
        compdata_table, ascii_overrides
    )
    stage_overrides = {
        character: code
        for character, code in overrides.items()
        if not 0x20 <= ord(character) <= 0x7E
        or character in "12345"
    }
    stage_overrides.update(surface_aliases)
    stage_overrides.update(ascii_overrides)
    stage_table = project_ui_runtime_text_table(
        source_table,
        stage_overrides,
    )
    functions = read_stage_function_addresses(slps)
    source_stage_spec = source_config["inputs"]["stage"]
    source_stage_archive = (
        PROJECT_ROOT / source_stage_spec["path"]
    ).read_bytes()
    if (
        len(source_stage_archive) != source_stage_spec["size"]
        or sha256_bytes(source_stage_archive) != source_stage_spec["sha256"]
        or len(source_stage_archive) != len(stage_archive)
    ):
        raise SystemExit("source STAGE baseline mismatch")
    source_slps_spec = source_config["inputs"]["slps"]
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
    component_stages = {
        item["stage_index"]: item for item in component["stages"]
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
            raise SystemExit(
                f"stage {stage:03d} translated text mismatch: "
                f"missing={missing[:3]!r}, extra={extra[:3]!r}, "
                f"wrong={wrong[:3]!r}"
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

    expected_entry_count = font_manifest["full_story_renderer_coverage"][
        "unique_entry_count"
    ]
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
        compdata_table,
        surface_aliases,
    )

    output = config["output"]
    iso_size = iso_path.stat().st_size
    iso_sha256 = sha256_file(iso_path)
    report = {
        "schema_version": 1,
        "status": "full_story_final_iso_static_content_readback_passed",
        "scope": (
            "Independent final-ISO readback of all 154 selected story "
            "chunks and 91,746 dialogue, condition, and speaker entries, "
            "plus pilot-name, button-prompt, 24x3 layout, runtime-token, "
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
            "cjk_optical_policy": font_manifest["cjk_optical_policy"],
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
                font_manifest["full_story_renderer_coverage"][
                    "missing_renderer_character_count"
                ]
                == 0
                and font_manifest["full_story_renderer_coverage"]
                ["original_font_han_count"]
                == 0
                and font_manifest["full_story_renderer_coverage"]
                ["original_font_visible_character_count"]
                == 0
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
