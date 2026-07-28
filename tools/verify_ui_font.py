#!/usr/bin/env python3
"""Verify a profile-scoped incremental UI font component and manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_font import UiFontError, audit_ui_font_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reparse a generated UI SLPS/VT1 component, audit the selected "
            "glyphs and verify its byte-free committed manifest."
        )
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    outputs = config.get("outputs", {})
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["validation"],
        WORK_ROOT,
    )
    manifest_path = (args.manifest or PROJECT_ROOT / outputs["manifest"]).resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        report = audit_ui_font_candidate(
            PROJECT_ROOT,
            WORK_ROOT,
            config_path,
        )
    except UiFontError as error:
        raise SystemExit(str(error)) from error

    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file():
            raise SystemExit(
                f"manifest not found; review and run --refresh-manifest: "
                f"{manifest_path}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest != report:
            raise SystemExit(
                "UI font manifest drift; review the local report, then run "
                "--refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    coverage_key = config.get("manifest_contract", {}).get(
        "coverage_key",
        "p0_renderer_coverage",
    )
    coverage = report[coverage_key]
    print(
        "UI font:",
        f"profile={report['font_profile_id']}",
        f"entries={coverage['unique_entry_count']}",
        f"missing={coverage['missing_renderer_character_count']}",
        f"slots={report['capacity']['remaining_candidate_slot_count']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
