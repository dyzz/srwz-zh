#!/usr/bin/env python3
"""Report the reviewed fixed-position STAGE name inventory.

The default path reads only the frozen occurrence inventory used by normal
builds.  Discovery scans are available solely through explicit audit flags.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

try:
    from srwz.stage_formations import (
        discover_stage_default_formation_tables,
        discover_structural_stage_default_formations,
        discover_stage_default_formations,
        formation_inventory_sha256,
        load_locked_stage_default_formations,
    )
    from srwz.text import load_text_table
except ModuleNotFoundError:
    from tools.srwz.stage_formations import (
        discover_stage_default_formation_tables,
        discover_structural_stage_default_formations,
        discover_stage_default_formations,
        formation_inventory_sha256,
        load_locked_stage_default_formations,
    )
    from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE = PROJECT_ROOT / "work/disc/DATA/STAGE.BIN"
DEFAULT_HB = PROJECT_ROOT / "work/build/full-story-stage/components/HEDBDY/HB.BIN"
DEFAULT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
DEFAULT_CORPUS = PROJECT_ROOT / "corpus/zh/menu/stage-default-formations.json"
DEFAULT_INVENTORY = PROJECT_ROOT / "config/stage-default-formation-inventory.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report repeated fixed-slot text arrays in original STAGE data."
    )
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--hb", type=Path, default=DEFAULT_HB)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--legacy-heuristic",
        action="store_true",
        help="report the superseded repeated-array heuristic",
    )
    parser.add_argument(
        "--all-structural",
        action="store_true",
        help="report every independently owned fixed-slot source value",
    )
    parser.add_argument(
        "--formation-tables-only",
        action="store_true",
        help="report only the actual 52-byte default-formation tables",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    modes = sum(
        bool(value)
        for value in (
            args.legacy_heuristic,
            args.all_structural,
            args.formation_tables_only,
        )
    )
    if modes > 1:
        raise SystemExit(
            "--legacy-heuristic, --all-structural and "
            "--formation-tables-only are exclusive"
        )
    if args.legacy_heuristic:
        candidates = discover_stage_default_formations(
            args.stage.read_bytes(),
            args.hb.read_bytes(),
            load_text_table(args.table),
        )
    elif args.all_structural:
        candidates = discover_structural_stage_default_formations(
            args.stage.read_bytes(),
            args.hb.read_bytes(),
            load_text_table(args.table),
        )
    elif args.formation_tables_only:
        candidates = discover_stage_default_formation_tables(
            args.stage.read_bytes(),
            args.hb.read_bytes(),
            load_text_table(args.table),
        )
    else:
        document = json.loads(args.corpus.read_text(encoding="utf-8"))
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        candidates = load_locked_stage_default_formations(
            args.stage.read_bytes(),
            args.hb.read_bytes(),
            load_text_table(args.table),
            inventory,
        )
        locked_sources = {
            cell.source_text
            for candidate in candidates
            for cell in candidate.cells
        }
        if locked_sources != set(document["translations_by_source_text"]):
            raise SystemExit("locked inventory and reviewed corpus source drift")
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
    source_counts = Counter(
        cell.source_text for candidate in candidates for cell in candidate.cells
    )
    print(f"candidate_groups={len(candidates)}")
    print(f"candidate_entries={sum(source_counts.values())}")
    print(f"unique_source_count={len(source_counts)}")
    if args.formation_tables_only:
        suffix_names = sorted(
            source
            for source in source_counts
            if source.endswith(("隊", "チーム", "部隊"))
        )
        print(f"complete_team_suffix_name_count={len(suffix_names)}")
        print("complete_team_suffix_names=" + ",".join(suffix_names))
    print(f"inventory_sha256={formation_inventory_sha256(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
