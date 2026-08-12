#!/usr/bin/env python3
"""Explicitly freeze reviewed STAGE default-formation positions.

This is an audit/refreeze command, not part of the normal build.  Daily builds
load the resulting fixed-position inventory and never rescan STAGE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from srwz.stage_formations import (
        build_locked_formation_inventory,
        discover_known_stage_default_formations,
        discover_structural_stage_default_formations,
    )
    from srwz.text import load_text_table
except ModuleNotFoundError:
    from tools.srwz.stage_formations import (
        build_locked_formation_inventory,
        discover_known_stage_default_formations,
        discover_structural_stage_default_formations,
    )
    from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE = PROJECT_ROOT / "work/disc/DATA/STAGE.BIN"
DEFAULT_HB = PROJECT_ROOT / "work/build/full-story-stage/components/HEDBDY/HB.BIN"
DEFAULT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
DEFAULT_CORPUS = PROJECT_ROOT / "corpus/zh/menu/stage-default-formations.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "config/stage-default-formation-inventory.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze reviewed default-formation positions after an explicit scan."
    )
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--hb", type=Path, default=DEFAULT_HB)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def file_lock(path: Path, payload: bytes) -> dict:
    return {
        "path": str(path.resolve().relative_to(PROJECT_ROOT.resolve())),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    args = parse_args()
    if args.output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite without --force: {args.output}")
    stage = args.stage.read_bytes()
    hb = args.hb.read_bytes()
    table = load_text_table(args.table)
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    sources = frozenset(corpus["translations_by_source_text"])

    structural = discover_structural_stage_default_formations(stage, hb, table)
    structural_sources = {
        cell.source_text for group in structural for cell in group.cells
    }
    if sources != structural_sources:
        missing = sorted(structural_sources - sources)
        extra = sorted(sources - structural_sources)
        raise SystemExit(
            "reviewed corpus does not cover the explicit scan: "
            f"missing={missing!r} extra={extra!r}"
        )
    groups = discover_known_stage_default_formations(
        stage,
        hb,
        table,
        sources,
    )
    document = build_locked_formation_inventory(groups)
    document["source_stage"] = file_lock(args.stage, stage)
    document["source_hb"] = file_lock(args.hb, hb)
    document["source_corpus"] = file_lock(args.corpus, args.corpus.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    expected = document["expected"]
    print(f"output={args.output}")
    print(f"group_count={expected['group_count']}")
    print(f"stage_count={expected['stage_count']}")
    print(f"entry_count={expected['entry_count']}")
    print(f"unique_source_count={expected['unique_source_count']}")
    print(f"inventory_sha256={expected['inventory_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
