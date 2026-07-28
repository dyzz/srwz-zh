#!/usr/bin/env python3
"""Build the fixed-span P0 COMPDATA component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_menu import (
    UiMenuError,
    build_fixed_compdata_component,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-writeback/ui-p0-compdata-fixed.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Write P0 COMPDATA translations that fit their original "
            "terminated spans, then preserve-prefix re-encode the member."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_root = require_work_output(
        args.output_root or PROJECT_ROOT / config["outputs"]["component_root"],
        WORK_ROOT,
    )
    output_path = output_root / "DATA/COMPDATA.BN"
    report_path = output_root / "component-validation.json"
    if (output_path.exists() or report_path.exists()) and not args.force:
        raise SystemExit(f"output exists; use --force: {output_root}")
    try:
        output, report = build_fixed_compdata_component(
            PROJECT_ROOT,
            config_path,
        )
    except UiMenuError as error:
        raise SystemExit(str(error)) from error
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI P0 fixed COMPDATA:",
        f"covered={report['selection']['fixed_covered_entry_count']}",
        f"writes={report['write']['entry_count']}",
        f"overflow={report['remaining_work']['growing_compdata_entry_count']}",
        "pointers=unchanged",
    )
    print(f"component: {output_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
