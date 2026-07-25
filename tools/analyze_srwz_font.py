#!/usr/bin/env python3
"""Analyze the original VT1 font and a candidate compressed replacement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.font import (
    EXTENDED_CODE_START,
    GLYPH_SIZE,
    analyze_glyph_code_mapping,
    analyze_font_patch,
    decode_font_stream,
    decode_vt1_font_segment,
    extended_glyph_mapping,
    glyph_index_for_code,
    inventory_codebook,
    read_extended_glyph_table,
)
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the original decoded VT1 font segment with a candidate "
            "compressed segment without writing decoded game data."
        )
    )
    parser.add_argument(
        "--slps",
        type=Path,
        default=WORK_ROOT / "disc" / "SLPS_258.87",
    )
    parser.add_argument(
        "--vt1",
        type=Path,
        default=WORK_ROOT / "disc" / "DATA" / "VT1.BIN",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=PROJECT_ROOT.parent / "2_translated" / "font" / "2.bin",
    )
    parser.add_argument(
        "--text-table",
        type=Path,
        default=(
            PROJECT_ROOT
            / "vendor"
            / "upstream-python"
            / "project"
            / "tbl_all.json"
        ),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=WORK_ROOT / "font" / "font-analysis.json",
    )
    parser.add_argument(
        "--glyph-map-output",
        type=Path,
        default=WORK_ROOT / "font" / "glyph-code-map.json",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = require_work_output(args.json_output, WORK_ROOT)
    glyph_map_output = require_work_output(args.glyph_map_output, WORK_ROOT)
    existing = [
        path for path in (output, glyph_map_output) if path.exists()
    ]
    if existing and not args.force:
        raise SystemExit(f"output exists; use --force: {existing[0]}")

    executable = args.slps.read_bytes()
    original = decode_vt1_font_segment(
        executable,
        args.vt1.read_bytes(),
    )
    candidate = decode_font_stream(args.candidate.read_bytes())
    analysis = analyze_font_patch(original.decoded, candidate.decoded)
    text_table = load_text_table(args.text_table)
    codebook = inventory_codebook(text_table)
    extended_entries = read_extended_glyph_table(executable)
    glyph_mapping = analyze_glyph_code_mapping(
        text_table,
        extended_entries,
    )

    report = {
        "schema_version": 1,
        "content_policy": (
            "Hashes, counts and offsets only; decoded font bytes are not saved."
        ),
        "sources": {
            "slps": str(args.slps.resolve()),
            "vt1": str(args.vt1.resolve()),
            "candidate": str(args.candidate.resolve()),
            "text_table": str(args.text_table.resolve()),
        },
        "original_font_stream": original.to_metadata(),
        "candidate_font_stream": candidate.to_metadata(),
        "patch_analysis": analysis.to_mapping(),
        "codebook": codebook.to_mapping(),
        "glyph_mapping": glyph_mapping.to_mapping(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    supported_records = []
    unsupported_records = []
    for code, character in sorted(text_table.characters.items()):
        try:
            index = glyph_index_for_code(code, extended_entries)
        except ValueError:
            unsupported_records.append(
                {
                    "code": f"{code:04X}",
                    "character": character,
                }
            )
            continue
        supported_records.append(
            {
                "code": f"{code:04X}",
                "character": character,
                "glyph_index": index,
                "glyph_offset": index * GLYPH_SIZE,
                "source": (
                    "standard_formula"
                    if code < EXTENDED_CODE_START
                    else "extended_table_first_match"
                ),
            }
        )

    executable_only_records = []
    for code, index in sorted(
        extended_glyph_mapping(extended_entries).items()
    ):
        if code in text_table.characters:
            continue
        try:
            cp932_character = code.to_bytes(2, "big").decode("cp932")
        except UnicodeDecodeError:
            cp932_character = None
        executable_only_records.append(
            {
                "code": f"{code:04X}",
                "cp932_character": cp932_character,
                "glyph_index": index,
                "glyph_offset": index * GLYPH_SIZE,
            }
        )

    glyph_map_output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "content_policy": (
                    "Code, Unicode character and decoded glyph offsets only; "
                    "no font bitmap bytes."
                ),
                "supported_text_mappings": supported_records,
                "unsupported_text_codes": unsupported_records,
                "executable_only_extended_mappings": (
                    executable_only_records
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "font:",
        f"decoded={analysis.decoded_size}",
        f"changed={analysis.changed_byte_count}",
        f"blocks={len(analysis.changed_block_indices)}/{analysis.block_count}",
        f"outside={analysis.changed_bytes_outside_region}",
    )
    print(
        "codebook:",
        f"mapped={codebook.mapped_code_count}",
        f"capacity={codebook.candidate_capacity}",
        f"candidate_unmapped={len(codebook.candidate_unmapped_codes)}",
    )
    print(
        "glyph mapping:",
        f"supported={glyph_mapping.supported_text_code_count}",
        f"unsupported={len(glyph_mapping.unsupported_text_codes)}",
        f"referenced_glyphs={glyph_mapping.referenced_glyph_count}",
        (
            "extended="
            f"{glyph_mapping.supported_extended_text_code_count}"
        ),
    )
    print(f"json: {output}")
    print(f"glyph map: {glyph_map_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
