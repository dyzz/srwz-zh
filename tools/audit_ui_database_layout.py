#!/usr/bin/env python3
"""Audit P10 database line envelopes and write exact-glyph review pages."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

try:
    from srwz.diagnostics import require_work_output
    from srwz.ui_database_layout import (
        UiDatabaseLayoutError,
        audit_ui_database_layout,
        build_ui_database_layout_manifest,
        load_ui_database_layout_config,
    )
except ModuleNotFoundError:
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.ui_database_layout import (
        UiDatabaseLayoutError,
        audit_ui_database_layout,
        build_ui_database_layout_manifest,
        load_ui_database_layout_config,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-database-layout.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reread all P10 database strings, compare target line widths "
            "against observed original-family envelopes and render the exact "
            "candidate glyphs without launching PCSX2."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _write_tsv(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "runtime_scene_id",
                "family_ordinal",
                "entry_id",
                "member_id",
                "source_line_widths",
                "target_line_widths",
                "line_width_overflow",
                "line_count_overflow",
                "source_text",
                "target_text",
            ),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{
                        key: row[key]
                        for key in (
                            "runtime_scene_id",
                            "family_ordinal",
                            "entry_id",
                            "member_id",
                            "line_width_overflow",
                            "line_count_overflow",
                            "source_text",
                            "target_text",
                        )
                    },
                    "source_line_widths": ",".join(
                        str(value) for value in row["source_line_widths"]
                    ),
                    "target_line_widths": ",".join(
                        str(value) for value in row["target_line_widths"]
                    ),
                }
            )


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = load_ui_database_layout_config(config_path)
    report_path = require_work_output(
        (PROJECT_ROOT / config["outputs"]["report"]).resolve(),
        WORK_ROOT,
    )
    tsv_path = require_work_output(
        (PROJECT_ROOT / config["outputs"]["tsv"]).resolve(),
        WORK_ROOT,
    )
    preview_root = require_work_output(
        (PROJECT_ROOT / config["outputs"]["preview_root"]).resolve(),
        WORK_ROOT,
    )
    manifest_path = (
        PROJECT_ROOT / config["outputs"]["manifest"]
    ).resolve()
    outputs = (report_path, tsv_path, preview_root)
    if any(path.exists() for path in outputs) and not args.force:
        existing = next(path for path in outputs if path.exists())
        raise SystemExit(f"output exists; use --force: {existing}")
    try:
        report, previews = audit_ui_database_layout(
            PROJECT_ROOT,
            config_path,
        )
        expected_manifest = build_ui_database_layout_manifest(report)
    except UiDatabaseLayoutError as error:
        raise SystemExit(str(error)) from error

    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                expected_manifest,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file():
            raise SystemExit(
                "database layout manifest missing; review outputs and use "
                "--refresh-manifest"
            )
        if json.loads(
            manifest_path.read_text(encoding="utf-8")
        ) != expected_manifest:
            raise SystemExit(
                "database layout manifest drift; review outputs and use "
                "--refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tsv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tsv(tsv_path, report["entries"])
    preview_root.mkdir(parents=True, exist_ok=True)
    expected_preview_paths = set()
    for relative, payload in previews.items():
        output = require_work_output(
            (PROJECT_ROOT / relative).resolve(),
            WORK_ROOT,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        expected_preview_paths.add(output)
    for stale in preview_root.glob("*.png"):
        if stale.resolve() not in expected_preview_paths:
            stale.unlink()

    summary = report["summary"]
    print(
        "P10 database layout:",
        f"entries={summary['entry_count']}",
        f"width-overflow={summary['line_width_overflow_count']}",
        f"line-overflow={summary['line_count_overflow_count']}",
        f"previews={summary['preview_page_count']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    print(f"tsv: {tsv_path}")
    print(f"previews: {preview_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
