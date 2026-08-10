#!/usr/bin/env python3
"""Inventory repeated fixed-slot name arrays in decoded STAGE chunks.

This is a read-only discovery tool.  It deliberately reports structural
candidates instead of deciding that every matching string is a formation
name; the checked corpus remains the authoritative writeback selection.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

try:
    from srwz.stage_formations import (
        discover_stage_default_formations,
        formation_inventory_sha256,
    )
    from srwz.text import load_text_table
except ModuleNotFoundError:
    from tools.srwz.stage_formations import (
        discover_stage_default_formations,
        formation_inventory_sha256,
    )
    from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE = PROJECT_ROOT / "work/disc/DATA/STAGE.BIN"
DEFAULT_HB = PROJECT_ROOT / "work/build/full-story-stage/components/HEDBDY/HB.BIN"
DEFAULT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report repeated fixed-slot text arrays in original STAGE data."
    )
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--hb", type=Path, default=DEFAULT_HB)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidates = discover_stage_default_formations(
        args.stage.read_bytes(),
        args.hb.read_bytes(),
        load_text_table(args.table),
    )
    if args.json:
        print(
            json.dumps(
                [asdict(candidate) for candidate in candidates],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    for candidate in candidates:
        cells = ", ".join(
            f"0x{cell.offset:X}={cell.source_text!r}" for cell in candidate.cells
        )
        print(
            f"stage={candidate.stage_index:03d} layout={candidate.layout} "
            f"count={len(candidate.cells)} {cells}"
        )
    print(f"candidate_groups={len(candidates)}")
    print(f"inventory_sha256={formation_inventory_sha256(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
