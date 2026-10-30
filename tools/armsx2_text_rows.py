#!/usr/bin/env python3
"""Print the text rows the game drew, from an ARMSX2 runner tracedump.

Arm the tracepoints in a session (see tools/srwz/armsx2_text_probe.trace_commands):
  trace 13b5f0 name=glyph @70000060:2 s0:20      (SP; Original/Best 13ab50)
  trace 2112d0 name=SetText a1:160               (SP; Original 20c9b0, Best 20cd70)
then 'tracedump PATH' and run:
  python3 tools/armsx2_text_rows.py PATH [--max-columns 21] [--max-right X]

Each distinct row is printed once with its frame, y, x range (screen x from the
centre; the last glyph's 21 px advance included) and glyph count. Rows with more
glyphs than --max-columns, or reaching past --max-right, are flagged and the exit
status is 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from srwz.armsx2_text_probe import glyph_rows, load_codebook, read_hits, set_text_lines, unique_rows
except ModuleNotFoundError:
    from tools.srwz.armsx2_text_probe import glyph_rows, load_codebook, read_hits, set_text_lines, unique_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tracedump", type=Path)
    parser.add_argument("--max-columns", type=int, default=0, help="flag rows with more glyphs than this")
    parser.add_argument("--max-right", type=int, default=None, help="flag rows whose right edge passes this x")
    args = parser.parse_args()

    codebook = load_codebook()
    hits = read_hits(args.tracedump)
    for frame, line in set_text_lines(hits, codebook):
        print(f"SetText frame {frame}: {line!r}")

    over = 0
    for row in unique_rows(glyph_rows(hits, codebook)):
        problems = []
        if args.max_columns and len(row.glyphs) > args.max_columns:
            problems.append(f"{len(row.glyphs)} glyphs > {args.max_columns}")
        if args.max_right is not None and row.x_end > args.max_right:
            problems.append(f"right edge {row.x_end} > {args.max_right}")
        over += bool(problems)
        flag = f"  << {'; '.join(problems)}" if problems else ""
        print(f"frame {row.frame:6d} y={row.y:4d} x={row.x_start:5d}..{row.x_end:5d} "
              f"glyphs={len(row.glyphs):2d} width={row.width:3d}  {row.text}{flag}")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
