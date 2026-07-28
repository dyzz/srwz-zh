#!/usr/bin/env python3
"""Generate the incremental first-five + P0 UI font proposal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_font import UiFontError, build_ui_font_proposal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/ui-p0-font.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extend the locked first-five font proposal with selected P0 UI "
            "characters without modifying game files."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    outputs = config.get("outputs", {})
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["readiness"],
        WORK_ROOT,
    )
    proposal_path = require_work_output(
        args.proposal or PROJECT_ROOT / outputs["proposal"],
        WORK_ROOT,
    )
    for output in (report_path, proposal_path):
        if output.exists() and not args.force:
            raise SystemExit(f"output exists; use --force: {output}")
    try:
        proposal, report = build_ui_font_proposal(
            PROJECT_ROOT,
            WORK_ROOT,
            args.config.resolve(),
        )
    except UiFontError as error:
        raise SystemExit(str(error)) from error

    for path, document in (
        (proposal_path, proposal),
        (report_path, report),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        "UI P0 font proposal:",
        f"entries={report['ui_selection']['unique_entry_count']}",
        f"new={report['additional_allocations']['count']}",
        f"reraster={report['additional_reraster_existing_han']['count']}",
        f"remaining={report['capacity']['remaining_candidate_slot_count']}",
    )
    print(f"proposal: {proposal_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
