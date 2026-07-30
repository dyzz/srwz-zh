#!/usr/bin/env python3
"""Build the P10 fixed-span database UI component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_database_candidate import (
    UiDatabaseCandidateError,
    build_ui_database_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "config/ui-writeback/ui-p10-database-fixed-core.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_root = require_work_output(
        args.output_root
        or PROJECT_ROOT / config["outputs"]["component_root"],
        WORK_ROOT,
    )
    report_path = output_root / "component-validation.json"
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        payloads, report = build_ui_database_candidate(
            PROJECT_ROOT,
            config_path,
        )
    except (
        KeyError,
        OSError,
        UiDatabaseCandidateError,
    ) as error:
        raise SystemExit(str(error)) from error
    for member, payload in payloads.items():
        path = output_root / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI database candidate:",
        f"profile={report['profile_id']}",
        f"entries={report['selection']['entry_count']}",
        f"members={len(payloads)}",
        "runtime=pending",
    )
    print(f"components: {output_root}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
