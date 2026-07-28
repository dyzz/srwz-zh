#!/usr/bin/env python3
"""Build a configured fixed-allocation display-name COMPDATA component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.display_names import (
    DisplayNameError,
    build_p0_display_name_component,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-writeback/ui-p0-display-names.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compose a locked pilot/unit display-name selection on top of "
            "the validated P0 fixed COMPDATA component."
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
        output, report = build_p0_display_name_component(
            PROJECT_ROOT,
            config_path,
        )
    except DisplayNameError as error:
        raise SystemExit(str(error)) from error
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI display names:",
        f"translations={report['selection']['translation_entry_count']}",
        f"writes={report['write']['operation_count']}",
        f"remaining={report['remaining_work']['unselected_non_empty_entry_count']}",
        "pointers=unchanged",
    )
    print(f"component: {output_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
