#!/usr/bin/env python3
"""Locate one exact battle subtitle in the paired SRVC SEG/BIN archive.

This is the bounded first step toward a full SRVC extractor.  It proves the
member, chunk and byte offsets for a known runtime line without guessing text
regions or modifying either source member.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from bisect import bisect_right
from pathlib import Path

try:
    from srwz.image_export import parse_seg_offsets
    from srwz.text import decode_text, encode_text, load_text_table
except ModuleNotFoundError:
    from tools.srwz.image_export import parse_seg_offsets
    from tools.srwz.text import decode_text, encode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEG = PROJECT_ROOT / "work" / "disc" / "BTL" / "SRVC.SEG"
DEFAULT_BIN = PROJECT_ROOT / "work" / "disc" / "BTL" / "SRVC.BIN"
DEFAULT_TEXT_TABLE = (
    PROJECT_ROOT
    / "vendor"
    / "upstream-python"
    / "project"
    / "tbl_all.json"
)
DEFAULT_NEEDLE = "一気に間合いをっ！"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def find_all(data: bytes, needle: bytes) -> tuple[int, ...]:
    if not needle:
        raise ValueError("battle-text needle must not encode to an empty string")
    offsets: list[int] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return tuple(offsets)
        offsets.append(offset)
        start = offset + 1


def probe_srvc_battle_text(
    *,
    seg_path: Path,
    bin_path: Path,
    text_table_path: Path,
    needle: str,
) -> dict[str, object]:
    seg_data = seg_path.read_bytes()
    bin_data = bin_path.read_bytes()
    table = load_text_table(text_table_path)
    chunk_offsets = parse_seg_offsets(seg_data, len(bin_data))
    encoded = encode_text(needle, table)
    opening_quote = encode_text("「", table)
    occurrences = []

    for bin_offset in find_all(bin_data, encoded):
        chunk_index = bisect_right(chunk_offsets, bin_offset) - 1
        if not 0 <= chunk_index < len(chunk_offsets) - 1:
            raise ValueError(
                f"occurrence 0x{bin_offset:X} is outside the SEG chunk ranges"
            )
        chunk_start = chunk_offsets[chunk_index]
        chunk_end = chunk_offsets[chunk_index + 1]
        context_start = bin_offset
        if (
            bin_offset >= chunk_start + len(opening_quote)
            and bin_data[bin_offset - len(opening_quote) : bin_offset]
            == opening_quote
        ):
            context_start -= len(opening_quote)
        decoded = decode_text(
            bin_data,
            context_start,
            table,
            end=chunk_end,
        )
        occurrences.append(
            {
                "bin_offset": bin_offset,
                "bin_offset_hex": f"0x{bin_offset:X}",
                "chunk_index": chunk_index,
                "chunk_start": chunk_start,
                "chunk_start_hex": f"0x{chunk_start:X}",
                "chunk_end": chunk_end,
                "chunk_end_hex": f"0x{chunk_end:X}",
                "chunk_relative_offset": bin_offset - chunk_start,
                "chunk_relative_offset_hex": f"0x{bin_offset - chunk_start:X}",
                "context_start": context_start,
                "context_start_hex": f"0x{context_start:X}",
                "context_text": decoded.text,
                "context_end": decoded.end,
                "context_unknown_code_count": decoded.unknown_code_count,
            }
        )

    source_code = table.inverse_characters.get("間")
    return {
        "schema_version": 1,
        "scope": "read-only exact SRVC battle-subtitle source probe",
        "source": {
            "seg": {
                "path": display_path(seg_path),
                "size": len(seg_data),
                "sha256": sha256_bytes(seg_data),
            },
            "bin": {
                "path": display_path(bin_path),
                "size": len(bin_data),
                "sha256": sha256_bytes(bin_data),
            },
            "text_table": {
                "path": display_path(text_table_path),
                "size": text_table_path.stat().st_size,
                "sha256": sha256_bytes(text_table_path.read_bytes()),
            },
            "chunk_count": len(chunk_offsets) - 1,
        },
        "probe": {
            "needle": needle,
            "encoded_hex": encoded.hex(),
            "source_character_code": {
                "character": "間",
                "code": source_code,
                "code_hex": None if source_code is None else f"0x{source_code:04X}",
            },
            "occurrence_count": len(occurrences),
            "occurrences": occurrences,
        },
        "checks": {
            "seg_offsets_cover_bin_exactly": chunk_offsets[-1] == len(bin_data),
            "all_occurrences_in_one_chunk": len(
                {item["chunk_index"] for item in occurrences}
            )
            <= 1,
            "all_contexts_decode_without_unknown_codes": all(
                item["context_unknown_code_count"] == 0 for item in occurrences
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Locate one exact Japanese battle subtitle in SRVC.SEG/BIN."
    )
    parser.add_argument("--seg", type=Path, default=DEFAULT_SEG)
    parser.add_argument("--bin", type=Path, default=DEFAULT_BIN)
    parser.add_argument("--text-table", type=Path, default=DEFAULT_TEXT_TABLE)
    parser.add_argument("--needle", default=DEFAULT_NEEDLE)
    parser.add_argument("--expected-count", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = probe_srvc_battle_text(
            seg_path=args.seg.resolve(),
            bin_path=args.bin.resolve(),
            text_table_path=args.text_table.resolve(),
            needle=args.needle,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    actual_count = report["probe"]["occurrence_count"]
    if actual_count != args.expected_count:
        print(
            f"error: expected {args.expected_count} occurrences, found {actual_count}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
