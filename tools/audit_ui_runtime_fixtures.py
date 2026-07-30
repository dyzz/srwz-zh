#!/usr/bin/env python3
"""Discover local SRWZ memory cards without copying or modifying them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_runtime_fixtures import build_runtime_fixture_preflight
from srwz.ui_runtime_matrix import UiRuntimeMatrixError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_MATRIX = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"
DEFAULT_SEARCH_ROOT = (
    Path.home() / "Library/Application Support/PCSX2/memcards"
)
DEFAULT_OUTPUT = WORK_ROOT / "review/ui-runtime-fixture-preflight.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect local .ps2 cards, rank missing UI fixtures by blocked "
            "case count and write a read-only report. No card is copied or "
            "promoted automatically."
        )
    )
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument(
        "--search-root",
        type=Path,
        action="append",
        help=(
            "Card file or directory to inspect; repeat for multiple roots. "
            f"Default: {DEFAULT_SEARCH_ROOT}"
        ),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = require_work_output(args.output.resolve(), WORK_ROOT)
    if output_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output_path}")
    search_roots = args.search_root or [DEFAULT_SEARCH_ROOT]
    try:
        report = build_runtime_fixture_preflight(
            PROJECT_ROOT,
            args.matrix.resolve(),
            search_roots,
        )
    except (OSError, UiRuntimeMatrixError, ValueError) as error:
        raise SystemExit(str(error)) from error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = report["summary"]
    print(f"runtime fixtures: {report['status']}")
    print(
        "memory-card fixtures: "
        f"{summary['ready_memory_card_fixture_count']} ready / "
        f"{summary['not_acquired_memory_card_fixture_count']} not acquired"
    )
    print(
        f"blocked cases: {summary['blocked_case_count']}; "
        f"local cards: {summary['candidate_file_count']}; "
        f"target candidates: {summary['target_save_candidate_count']}"
    )
    print(f"report: {output_path}")
    print("No memory card was copied or modified; runtime remains not_tested")
    return (
        0
        if report["status"] == "fixture_inventory_ready"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
