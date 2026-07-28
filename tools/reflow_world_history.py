#!/usr/bin/env python3
"""Reflow and audit all Chinese MTV_PROS world-history records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.summary_layout import (
    SummaryLayoutError,
    build_world_history_layout,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/summary/world-history-layout.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write canonical Chinese layout to corpus/zh/summary.json",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    outputs = config["outputs"]
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["report"],
        WORK_ROOT,
    )
    manifest_path = (args.manifest or PROJECT_ROOT / outputs["manifest"]).resolve()
    if report_path.exists() and not args.force:
        raise SummaryLayoutError(f"report exists; use --force: {report_path}")

    projected, report, manifest = build_world_history_layout(
        PROJECT_ROOT,
        config_path,
    )
    changed = report["layout"]["noncanonical_entry_count"]
    if args.apply and changed:
        translation_path = (
            PROJECT_ROOT / config["translation_source"]["path"]
        ).resolve()
        _write_json(translation_path, projected)
        projected, report, manifest = build_world_history_layout(
            PROJECT_ROOT,
            config_path,
        )
        changed = report["layout"]["noncanonical_entry_count"]
        if changed:
            raise SummaryLayoutError(
                "world-history corpus is still noncanonical after apply"
            )

    _write_json(report_path, report)
    if args.refresh_manifest:
        if changed:
            raise SummaryLayoutError(
                "cannot refresh world-history manifest before applying layout"
            )
        _write_json(manifest_path, manifest)
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file():
            manifest_status = "missing"
        else:
            committed = json.loads(manifest_path.read_text(encoding="utf-8"))
            if committed != manifest:
                raise SummaryLayoutError(
                    "world-history manifest drift; review and use --refresh-manifest"
                )
            manifest_status = "verified"

    print(
        "world-history layout:",
        f"entries={report['selection']['entry_count']}",
        f"lines={report['layout']['output_line_count']}",
        f"changed={changed}",
        f"width={report['layout']['maximum_line_width']}",
        f"font_missing={report['font_capacity']['missing_character_count']}",
        f"font_shortfall={report['font_capacity']['candidate_shortfall']}",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    if changed:
        print(
            "world-history layout is not canonical; rerun with --apply",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, SummaryLayoutError) as error:
        print(f"world-history layout failed: {error}", file=sys.stderr)
        raise SystemExit(1)
