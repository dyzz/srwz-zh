#!/usr/bin/env python3
"""Audit the terminology-safe fixed-span subset of the large UI databases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_database_selection import (
    UiDatabaseSelectionError,
    audit_ui_database_selection,
    build_database_selection_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-database-selection.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Select and verify the largest bounded database subset that fits "
            "the current renderer allocation strategy and original text spans."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    outputs = config["outputs"]
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["report"],
        WORK_ROOT,
    )
    manifest_path = (
        args.manifest.resolve()
        if args.manifest
        else PROJECT_ROOT / outputs["manifest"]
    )
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        report = audit_ui_database_selection(PROJECT_ROOT, config_path)
        expected_manifest = build_database_selection_manifest(report)
    except UiDatabaseSelectionError as error:
        raise SystemExit(str(error)) from error

    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(expected_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file():
            raise SystemExit(
                f"manifest not found; review and use --refresh-manifest: "
                f"{manifest_path}"
            )
        if json.loads(manifest_path.read_text(encoding="utf-8")) != expected_manifest:
            raise SystemExit(
                "database selection manifest drift; review the report, then "
                "run with --refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    selection = report["selection"]
    print(
        "UI database selection:",
        f"selected={selection['selected_entry_count']}",
        f"deferred={selection['deferred_entry_count']}",
        f"missing={report['font_demand']['missing_renderer_character_count']}",
        "fixed-span=ready",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
