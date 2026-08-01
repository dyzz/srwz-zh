#!/usr/bin/env python3
"""Audit the final sequential Chinese-owned SRWZ font plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.full_font_plan import FullFontPlanError, audit_full_chinese_font_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/full-chinese-font-plan.json"
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests/full-chinese-font-plan.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    report_path = require_work_output(
        args.report or PROJECT_ROOT / config["outputs"]["report"],
        WORK_ROOT,
    )
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        report = audit_full_chinese_font_plan(PROJECT_ROOT, config_path)
    except (OSError, FullFontPlanError) as error:
        raise SystemExit(str(error)) from error

    manifest_path = args.manifest.resolve()
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        committed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if committed != report:
            raise SystemExit("full-font manifest drift; use --refresh-manifest")
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    capacity = report["capacity"]
    print(
        "full Chinese font plan:",
        f"required={capacity['current_required_slot_count']}",
        f"available={capacity['sequential_translation_slot_count']}",
        f"remaining={capacity['current_remaining_slot_count']}",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
