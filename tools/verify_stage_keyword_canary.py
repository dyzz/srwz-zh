#!/usr/bin/env python3
"""Reread all female Stage 1 glossary links and KYWD keys from an ISO.

This verifier is deliberately narrower than the full release verifier.  It
proves the byte-level contract needed by the first female-route canary without
depending on, or rebuilding, concurrent LIBRARY work:

* all 19 STAGE spans contain the native 0x8173/0x8174 link markers;
* the text between those markers is one of the three expected Chinese terms;
* each linked MTVZKNKW entry exposes the exact same text in its WORD field; and
* the visible Japanese-style outer quotes around the manual canary remain.

The remaining acceptance gate is a PCSX2 check that the marked text is styled
and that Square opens the popup.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Iterable

from srwz.codec import decode_production as decode
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.library import parse_runtime_zkn_decoded_chunk
from srwz.stage import parse_stage, read_stage_function_addresses
from srwz.text import TextTable, decode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = (
    PROJECT_ROOT
    / "build/iso/keyword-link-canary/srwz-zh-keyword-link-stage001.iso"
)
DEFAULT_ASSIGNMENTS = (
    PROJECT_ROOT / "config/encoding/zh-release-font-assignments.json"
)
DEFAULT_TEXT_TABLE = (
    PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "work/verification/keyword-link-stage001-readback.json"
)
STAGE_OFFSET_SPEC = ExecutableOffsetSpec(
    name="HEDBDY/HB.BIN STAGE offsets",
    member="HEDBDY/HB.BIN",
    table_start=30320,
    table_end=31144,
)
KEYWORD_OFFSET_SPEC = ExecutableOffsetSpec(
    name="MTVZKNKW.BIN",
    member="DATA/MTVZKNKW.BIN",
    table_start=0x32B980,
    table_end=0x32BA4F,
)
REQUIRED_MEMBERS = (
    "SLPS_258.87",
    "HEDBDY/HB.BIN",
    "DATA/STAGE.BIN",
    "DATA/MTVZKNKW.BIN",
)
KEYWORD_START = bytes.fromhex("8173")
KEYWORD_END = bytes.fromhex("8174")
VISIBLE_QUOTE_START = bytes.fromhex("8177")
VISIBLE_QUOTE_END = bytes.fromhex("8178")
STAGE001_EXPECTED_KEYWORDS = (
    (7, "ティターンズ", "提坦斯", 8),
    (8, "エゥーゴ", "奥古", 4),
    (51, "グローリー・スター", "荣耀之星", 7),
)
CANARY_ENTRY_ID = "story/001/dialogue/02.01/0006"
VISIBLE_QUOTE_ENTRY_IDS = (
    "story/001/dialogue/02.01/0006",
    "story/001/dialogue/02.01/0008",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--assignments", type=Path, default=DEFAULT_ASSIGNMENTS)
    parser.add_argument("--text-table", type=Path, default=DEFAULT_TEXT_TABLE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--stage-index", type=int, default=1)
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_members(iso_path: Path, paths: Iterable[str]) -> dict[str, bytes]:
    image = scan_iso9660(iso_path)
    members = member_map(image)
    requested = tuple(paths)
    missing = sorted(set(requested) - set(members))
    if missing:
        raise SystemExit(f"keyword canary ISO is missing members: {missing}")
    output = {}
    with iso_path.open("rb") as source:
        for path in requested:
            member = members[path]
            source.seek(member.extent_lba * SECTOR_SIZE)
            payload = source.read(member.size)
            if len(payload) != member.size:
                raise SystemExit(f"short ISO member read: {path}")
            output[path] = payload
    return output


def _code(value: object, *, label: str) -> int:
    if not isinstance(value, str):
        raise SystemExit(f"{label} code is not a hexadecimal string")
    try:
        result = int(value, 16)
    except ValueError as exc:
        raise SystemExit(f"{label} code is not hexadecimal") from exc
    if not 0 <= result <= 0xFFFF:
        raise SystemExit(f"{label} code is outside two bytes")
    return result


def _runtime_tables(
    text_table_path: Path,
    assignments_path: Path,
) -> tuple[TextTable, TextTable]:
    source_table = load_text_table(text_table_path)
    document = json.loads(assignments_path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise SystemExit("unsupported release-font assignment schema")

    characters = dict(source_table.characters)
    used_codes: dict[int, str] = {}
    for group in ("primary_assignments", "surface_alias_assignments"):
        rows = document.get(group)
        if not isinstance(rows, list):
            raise SystemExit(f"font assignment group is malformed: {group}")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise SystemExit(f"font assignment row is malformed: {group}/{index}")
            character = row.get("character")
            if not isinstance(character, str) or len(character) != 1:
                raise SystemExit(f"font assignment character is malformed: {group}/{index}")
            code = _code(row.get("code"), label=f"{group}/{index}")
            previous = used_codes.setdefault(code, character)
            if previous != character:
                raise SystemExit(f"font assignment code collision at 0x{code:04X}")
            characters[code] = character

    # These two codes are semantic delimiters in STAGE.  The runtime does not
    # draw them, but representing them as 《/》 lets the strict parser expose
    # the link span in lossless source notation.
    if source_table.characters.get(0x8173) != "《" or source_table.characters.get(0x8174) != "》":
        raise SystemExit("source text table lost native STAGE keyword delimiters")
    semantic_characters = dict(characters)
    semantic_characters[0x8173] = "《"
    semantic_characters[0x8174] = "》"
    return (
        TextTable(characters=characters, tags=source_table.tags),
        TextTable(characters=semantic_characters, tags=source_table.tags),
    )


def _decode_slot(stored: bytes, *, label: str) -> bytes:
    result = decode(stored)
    if any(stored[result.consumed :]):
        raise SystemExit(f"{label} has non-zero bytes after the compressed stream")
    return result.output


def main() -> None:
    args = parse_args()
    iso_path = args.iso.resolve()
    if not iso_path.is_file():
        raise SystemExit(f"keyword canary ISO does not exist: {iso_path}")
    members = _read_members(iso_path, REQUIRED_MEMBERS)
    slps = members["SLPS_258.87"]
    hb = members["HEDBDY/HB.BIN"]
    stage_archive = members["DATA/STAGE.BIN"]
    keyword_archive = members["DATA/MTVZKNKW.BIN"]
    runtime_table, semantic_table = _runtime_tables(
        args.text_table.resolve(),
        args.assignments.resolve(),
    )

    stage_offsets = read_executable_archive_offsets(
        hb,
        STAGE_OFFSET_SPEC,
        len(stage_archive),
    )
    if not 0 <= args.stage_index < len(stage_offsets) - 1:
        raise SystemExit("requested STAGE index is outside the archive")
    stage_start, stage_end = stage_offsets[args.stage_index : args.stage_index + 2]
    decoded_stage = _decode_slot(
        stage_archive[stage_start:stage_end],
        label=f"STAGE {args.stage_index:03d}",
    )
    functions = read_stage_function_addresses(slps)
    parsed = parse_stage(
        decoded_stage,
        semantic_table,
        stage_index=args.stage_index,
        function_address=functions[args.stage_index],
    )
    expected_counts = Counter(
        {translation: count for _, _, translation, count in STAGE001_EXPECTED_KEYWORDS}
    )
    actual_counts: Counter[str] = Counter()
    stage_keyword_bytes: dict[str, set[bytes]] = {}
    native_start_count = 0
    native_end_count = 0
    for parsed_entry in parsed.entries:
        if "《" not in (parsed_entry.text or "") and "》" not in (parsed_entry.text or ""):
            continue
        if parsed_entry.text_offset is None:
            raise SystemExit(f"linked STAGE entry has no text offset: {parsed_entry.entry_id}")
        parsed_speaker = decode_text(
            decoded_stage,
            parsed_entry.text_offset,
            semantic_table,
            stop_at_newline=True,
        )
        parsed_message = decode_text(decoded_stage, parsed_speaker.end, semantic_table)
        if parsed_message.text != parsed_entry.text:
            raise SystemExit(
                f"linked STAGE reread disagrees with parser: {parsed_entry.entry_id}"
            )
        message_payload = decoded_stage[parsed_message.start : parsed_message.end]
        native_start_count += message_payload.count(KEYWORD_START)
        native_end_count += message_payload.count(KEYWORD_END)
        payload_cursor = 0
        payload_keywords = []
        while True:
            payload_start = message_payload.find(KEYWORD_START, payload_cursor)
            if payload_start < 0:
                break
            payload_end = message_payload.find(
                KEYWORD_END,
                payload_start + len(KEYWORD_START),
            )
            if payload_end < 0:
                raise SystemExit(
                    f"unclosed native STAGE keyword span: {parsed_entry.entry_id}"
                )
            payload_word = message_payload[
                payload_start + len(KEYWORD_START) : payload_end
            ]
            decoded_payload_word = decode_text(
                payload_word,
                0,
                runtime_table,
                end=len(payload_word),
                allow_end=True,
            )
            if (
                decoded_payload_word.unknown_code_count
                or decoded_payload_word.end != len(payload_word)
            ):
                raise SystemExit(
                    f"native STAGE keyword bytes do not decode exactly: "
                    f"{parsed_entry.entry_id}"
                )
            payload_keywords.append(decoded_payload_word.text)
            stage_keyword_bytes.setdefault(decoded_payload_word.text, set()).add(
                payload_word
            )
            payload_cursor = payload_end + len(KEYWORD_END)
        cursor = 0
        semantic_keywords = []
        while True:
            span_start = parsed_message.text.find("《", cursor)
            if span_start < 0:
                break
            span_end = parsed_message.text.find("》", span_start + 1)
            if span_end < 0:
                raise SystemExit(f"unclosed STAGE keyword span: {parsed_entry.entry_id}")
            semantic_word = parsed_message.text[span_start + 1 : span_end]
            semantic_keywords.append(semantic_word)
            actual_counts[semantic_word] += 1
            cursor = span_end + 1
        if payload_keywords != semantic_keywords:
            raise SystemExit(
                f"native and semantic STAGE keyword order disagree: "
                f"{parsed_entry.entry_id}"
            )
    if actual_counts != expected_counts:
        raise SystemExit(
            f"female Stage 1 keyword occurrence drift: "
            f"actual={dict(actual_counts)!r}, expected={dict(expected_counts)!r}"
        )
    expected_span_count = sum(expected_counts.values())
    if native_start_count != expected_span_count or native_end_count != expected_span_count:
        raise SystemExit(
            "female Stage 1 does not encode every semantic span with native "
            f"0x8173/0x8174 markers: starts={native_start_count}, "
            f"ends={native_end_count}, expected={expected_span_count}"
        )

    by_entry_id = {entry.entry_id: entry for entry in parsed.entries}
    glory_star_byte_variants = stage_keyword_bytes.get("荣耀之星", set())
    if len(glory_star_byte_variants) != 1:
        raise SystemExit(
            "female Stage 1 does not use one exact byte sequence for 荣耀之星"
        )
    glory_star_bytes = next(iter(glory_star_byte_variants))
    visible_quote_entries = []
    for visible_entry_id in VISIBLE_QUOTE_ENTRY_IDS:
        visible_entry = by_entry_id.get(visible_entry_id)
        if visible_entry is None or visible_entry.text_offset is None:
            raise SystemExit(
                f"missing visible-quote canary entry: {visible_entry_id}"
            )
        visible_speaker = decode_text(
            decoded_stage,
            visible_entry.text_offset,
            semantic_table,
            stop_at_newline=True,
        )
        visible_message = decode_text(
            decoded_stage,
            visible_speaker.end,
            semantic_table,
        )
        visible_payload = decoded_stage[visible_message.start : visible_message.end]
        visible_target = (
            VISIBLE_QUOTE_START
            + KEYWORD_START
            + glory_star_bytes
            + KEYWORD_END
            + VISIBLE_QUOTE_END
        )
        target_count = visible_payload.count(visible_target)
        if target_count != 1:
            raise SystemExit(
                f"{visible_entry_id} does not contain exactly one native "
                f"『《荣耀之星》』 sequence: found={target_count}"
            )
        visible_quote_entries.append(
            {
                "entry_id": visible_entry_id,
                "decoded_text": visible_message.text,
                "target_sequence_hex": visible_target.hex(),
                "expected_visible_text": "『荣耀之星』",
                "native_visible_quotes_exact": True,
            }
        )

    matches = [entry for entry in parsed.entries if entry.entry_id == CANARY_ENTRY_ID]
    if len(matches) != 1:
        raise SystemExit(
            f"expected one STAGE entry {CANARY_ENTRY_ID!r}, found {len(matches)}"
        )
    entry = matches[0]
    if entry.text_offset is None:
        raise SystemExit("selected STAGE entry has no text offset")
    speaker = decode_text(
        decoded_stage,
        entry.text_offset,
        semantic_table,
        stop_at_newline=True,
    )
    message = decode_text(decoded_stage, speaker.end, semantic_table)
    if message.text != entry.text:
        raise SystemExit("selected STAGE message reread disagrees with parser")

    message_bytes = decoded_stage[message.start : message.end]
    marker_starts = [
        index
        for index in range(len(message_bytes))
        if message_bytes.startswith(KEYWORD_START, index)
    ]
    marker_ends = [
        index
        for index in range(len(message_bytes))
        if message_bytes.startswith(KEYWORD_END, index)
    ]
    if len(marker_starts) != 1 or len(marker_ends) != 1:
        raise SystemExit(
            "selected STAGE message does not contain exactly one native "
            "keyword-link span"
        )
    relative_start = marker_starts[0]
    relative_end = marker_ends[0]
    if relative_end <= relative_start + len(KEYWORD_START):
        raise SystemExit("selected STAGE keyword-link span is empty or reversed")
    if (
        relative_start < len(VISIBLE_QUOTE_START)
        or message_bytes[
            relative_start - len(VISIBLE_QUOTE_START) : relative_start
        ]
        != VISIBLE_QUOTE_START
        or message_bytes[
            relative_end + len(KEYWORD_END) :
            relative_end + len(KEYWORD_END) + len(VISIBLE_QUOTE_END)
        ]
        != VISIBLE_QUOTE_END
    ):
        raise SystemExit("selected STAGE keyword link lost its visible outer quotes")
    keyword_bytes = message_bytes[
        relative_start + len(KEYWORD_START) : relative_end
    ]
    decoded_stage_keyword = decode_text(
        keyword_bytes,
        0,
        runtime_table,
        end=len(keyword_bytes),
        allow_end=True,
    )
    if (
        decoded_stage_keyword.unknown_code_count
        or decoded_stage_keyword.end != len(keyword_bytes)
        or decoded_stage_keyword.text != "荣耀之星"
    ):
        raise SystemExit(
            "selected STAGE keyword bytes do not decode to the expected text"
        )
    target_sequence = message_bytes[
        relative_start - len(VISIBLE_QUOTE_START) :
        relative_end + len(KEYWORD_END) + len(VISIBLE_QUOTE_END)
    ]
    target_offset = message.start + relative_start - len(VISIBLE_QUOTE_START)
    if "《荣耀之星》" not in message.text:
        raise SystemExit("selected STAGE semantic reread lost the keyword span")

    keyword_offsets = read_executable_archive_offsets(
        slps,
        KEYWORD_OFFSET_SPEC,
        len(keyword_archive),
    )
    popup_keys = []
    for keyword_entry_index, source_word, expected_word, occurrence_count in (
        STAGE001_EXPECTED_KEYWORDS
    ):
        if not 0 <= keyword_entry_index < len(keyword_offsets) - 1:
            raise SystemExit("requested KYWD entry index is outside the archive")
        keyword_start, keyword_end = keyword_offsets[
            keyword_entry_index : keyword_entry_index + 2
        ]
        decoded_keyword = _decode_slot(
            keyword_archive[keyword_start:keyword_end],
            label=f"KYWD {keyword_entry_index:03d}",
        )
        keyword_document = parse_runtime_zkn_decoded_chunk(
            decoded_keyword,
            runtime_table,
        )
        if keyword_document.kind != "KYWD":
            raise SystemExit("selected ZKAN document is not a KYWD entry")
        keyword_word = keyword_document.field("WORD").text
        if keyword_word != expected_word:
            raise SystemExit(
                f"KYWD {keyword_entry_index:03d} WORD mismatch: "
                f"{keyword_word!r} != {expected_word!r}"
            )
        keyword_word_bytes = keyword_document.field("WORD").data
        linked_byte_variants = stage_keyword_bytes.get(expected_word, set())
        if linked_byte_variants != {keyword_word_bytes}:
            raise SystemExit(
                f"KYWD {keyword_entry_index:03d} WORD bytes do not exactly match "
                f"all linked STAGE spans: WORD={keyword_word_bytes.hex()} "
                f"STAGE={sorted(value.hex() for value in linked_byte_variants)}"
            )
        popup_keys.append(
            {
                "member": "DATA/MTVZKNKW.BIN",
                "entry_index": keyword_entry_index,
                "slot_start": keyword_start,
                "slot_end": keyword_end,
                "kind": keyword_document.kind,
                "source_word": source_word,
                "word": keyword_word,
                "word_bytes_hex": keyword_word_bytes.hex(),
                "stage_byte_variants_hex": sorted(
                    value.hex() for value in linked_byte_variants
                ),
                "stage_occurrence_count": occurrence_count,
                "stage_span_matches_word": actual_counts[keyword_word]
                == occurrence_count,
                "stage_bytes_match_word": linked_byte_variants
                == {keyword_word_bytes},
                "runtime_reread_exact": True,
            }
        )

    report = {
        "schema_version": 1,
        "status": "offline_validated_runtime_pending",
        "iso": str(iso_path.relative_to(PROJECT_ROOT)),
        "iso_size": iso_path.stat().st_size,
        "iso_sha256": _sha256_file(iso_path),
        "stage": {
            "member": "DATA/STAGE.BIN",
            "stage_index": args.stage_index,
            "slot_start": stage_start,
            "slot_end": stage_end,
            "entry_id": CANARY_ENTRY_ID,
            "decoded_text": message.text,
            "keyword": "荣耀之星",
            "keyword_bytes_hex": keyword_bytes.hex(),
            "semantic_span": "《荣耀之星》",
            "expected_visible_text": "『荣耀之星』",
            "target_offset": target_offset,
            "target_sequence_hex": target_sequence.hex(),
            "native_keyword_start_code": "8173",
            "native_keyword_end_code": "8174",
            "native_visible_quote_start_code": "8177",
            "native_visible_quote_end_code": "8178",
            "reread_exact": True,
            "all_keyword_occurrences": dict(actual_counts),
            "native_keyword_start_count": native_start_count,
            "native_keyword_end_count": native_end_count,
            "visible_quote_entries": visible_quote_entries,
        },
        "keyword_popup_keys": popup_keys,
        "acceptance": {
            "static_link_contract": True,
            "pcsx2_styled_text": "pending_user_validation",
            "pcsx2_square_opens_popup": "pending_user_validation",
        },
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
