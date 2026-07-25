#!/usr/bin/env python3
"""Split selected compressed entries from DATA/STAGE.BIN."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from srwz.archive import (
    ArchiveLayoutError,
    load_offset_layout,
    split_archive_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "work" / "disc" / "DATA" / "STAGE.BIN"
DEFAULT_LAYOUT = PROJECT_ROOT / "config" / "stage-offsets.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "work" / "stage" / "compressed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split selected compressed stage entries without decoding them."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--index",
        type=int,
        action="append",
        default=[],
        help="stage archive index to extract; repeat for more than one",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="extract all entries instead of requiring explicit indices",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.all and args.index:
        print("error: --all and --index cannot be combined", file=sys.stderr)
        return 2

    try:
        layout = load_offset_layout(args.layout.resolve())
        indices = range(layout.chunk_count) if args.all else args.index
        written = split_archive_file(
            args.input.resolve(),
            args.output.resolve(),
            layout,
            indices,
            force=args.force,
        )
    except (ArchiveLayoutError, FileExistsError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
