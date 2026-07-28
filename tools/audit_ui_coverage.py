#!/usr/bin/env python3
"""Audit the selected SRWZ UI scenes against current source and font data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_inventory import (
    UiInventoryError,
    audit_ui_inventory,
    build_inventory_manifest,
    write_scene_tsv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-scenes.json"
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests/ui-surface-inventory.json"
DEFAULT_REPORT = WORK_ROOT / "review/ui-surface-inventory.json"
DEFAULT_TSV = WORK_ROOT / "review/ui-surface-inventory.tsv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate UI scene selectors, current translations, first-five "
            "font demand and hash-only dynamic display-name probes."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--tsv", type=Path, default=DEFAULT_TSV)
    parser.add_argument(
        "--refresh-manifest",
        action="store_true",
        help="Replace the committed bounded manifest after review.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_path = require_work_output(args.report, WORK_ROOT)
    tsv_path = require_work_output(args.tsv, WORK_ROOT)
    for output in (report_path, tsv_path):
        if output.exists() and not args.force:
            raise SystemExit(f"output exists; use --force: {output}")

    try:
        report = audit_ui_inventory(PROJECT_ROOT, args.config.resolve())
    except UiInventoryError as error:
        raise SystemExit(str(error)) from error

    manifest_path = args.manifest.resolve()
    expected_manifest = build_inventory_manifest(report)
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
                f"manifest not found; review and run --refresh-manifest: "
                f"{manifest_path}"
            )
        try:
            committed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(
                f"cannot load UI inventory manifest {manifest_path}: {error}"
            ) from error
        if committed_manifest != expected_manifest:
            raise SystemExit(
                "UI inventory manifest drift; review the local report, then "
                "run --refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with tsv_path.open("w", encoding="utf-8", newline="") as stream:
        write_scene_tsv(report, stream)

    summary = report["summary"]
    print(
        f"UI scenes: {summary['scene_count']}; "
        f"P0 entries: {summary['p0_unique_entry_count']}; "
        f"P0 missing glyphs: "
        f"{summary['p0_missing_renderer_character_count']}; "
        f"slot margin: {summary['p0_candidate_slot_margin']}"
    )
    print(f"dynamic display-name probes: {summary['dynamic_probe_count']} exact")
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    print(f"tsv: {tsv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
