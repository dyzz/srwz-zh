#!/usr/bin/env python3
"""Render verified VT1 glyph records without invoking game binaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.font import (
    ASCII_FIRST,
    ASCII_LAST,
    EXTENDED_CODE_START,
    ascii_glyph_index,
    decode_font_stream,
    decode_vt1_font_segment,
    glyph_index_for_code,
    read_extended_glyph_table,
    render_glyph_grid,
    sha256_bytes,
)
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render the verified 24x24/4-bpp glyph records from the original "
            "VT1 font segment or the upstream candidate stream."
        )
    )
    parser.add_argument(
        "--source",
        choices=("original", "candidate"),
        default="candidate",
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
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--characters",
        default=None,
        help="printable ASCII characters to render in order",
    )
    selection.add_argument(
        "--codes",
        help="comma- or space-separated two-byte text codes in hexadecimal",
    )
    selection.add_argument(
        "--all-mapped",
        action="store_true",
        help="render every text-table code with a verified original glyph",
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
    parser.add_argument("--columns", type=int, default=16)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=WORK_ROOT / "font" / "ascii-glyphs.png",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=WORK_ROOT / "font" / "ascii-glyphs.json",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = require_work_output(args.output, WORK_ROOT)
    metadata_output = require_work_output(args.metadata_output, WORK_ROOT)
    existing = [path for path in (output, metadata_output) if path.exists()]
    if existing and not args.force:
        raise SystemExit(f"output exists; use --force: {existing[0]}")

    executable = args.slps.read_bytes()
    if args.source == "original":
        decoded = decode_vt1_font_segment(
            executable,
            args.vt1.read_bytes(),
        ).decoded
        source_path = args.vt1
    else:
        decoded = decode_font_stream(args.candidate.read_bytes()).decoded
        source_path = args.candidate

    records = []
    indices = []
    if args.codes or args.all_mapped:
        text_table = load_text_table(args.text_table)
        extended_entries = read_extended_glyph_table(executable)
        if args.codes:
            tokens = args.codes.replace(",", " ").split()
            if not tokens:
                raise SystemExit("--codes did not contain any values")
            codes = tuple(int(token, 16) for token in tokens)
        else:
            codes = tuple(sorted(text_table.characters))

        for code in codes:
            try:
                index = glyph_index_for_code(code, extended_entries)
            except ValueError:
                if args.all_mapped:
                    continue
                raise
            indices.append(index)
            records.append(
                {
                    "character": text_table.characters.get(code),
                    "code": f"{code:04X}",
                    "glyph_index": index,
                    "mapping_source": (
                        "standard_formula"
                        if code < EXTENDED_CODE_START
                        else "extended_table_first_match"
                    ),
                }
            )
    else:
        characters = args.characters
        if characters is None:
            characters = "".join(
                chr(code) for code in range(ASCII_FIRST, ASCII_LAST + 1)
            )
        for character in characters:
            code = ord(character)
            index = ascii_glyph_index(code)
            indices.append(index)
            records.append(
                {
                    "character": character,
                    "code": f"{code:02X}",
                    "glyph_index": index,
                    "mapping_source": "upstream_ascii_patch",
                }
            )

    png = render_glyph_grid(
        decoded,
        indices,
        columns=args.columns,
        scale=args.scale,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(png)
    metadata_output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_kind": args.source,
                "source_path": str(source_path.resolve()),
                "decoded_sha256": sha256_bytes(decoded),
                "columns": args.columns,
                "scale": args.scale,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"rendered {len(records)} glyphs: {output}")
    print(f"metadata: {metadata_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
