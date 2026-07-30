#!/usr/bin/env python3
"""Audit and publish the COMPDATA-only causal boot experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.compdata_incremental import (
    CompdataIncrementalError,
    audit_compdata_incremental_chain,
    finalize_report,
)
from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/iso/compdata-incremental-chain.json"
DEFAULT_REPORT = WORK_ROOT / "review/compdata-incremental-validation.json"
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "manifests/compdata-incremental-validation.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_path = require_work_output(args.report.resolve(), WORK_ROOT)
    manifest_path = args.manifest.resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"report exists; use --force: {report_path}")
    try:
        report = finalize_report(
            audit_compdata_incremental_chain(
                PROJECT_ROOT,
                args.config.resolve(),
            )
        )
    except CompdataIncrementalError as error:
        raise SystemExit(str(error)) from error
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(serialized, encoding="utf-8")
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file():
            raise SystemExit(
                "manifest not found; review and use --refresh-manifest"
            )
        if manifest_path.read_text(encoding="utf-8") != serialized:
            raise SystemExit(
                "manifest drift; review and use --refresh-manifest"
            )
        manifest_status = "verified"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(serialized, encoding="utf-8")
    print("COMPDATA incremental audit:", report["status"])
    print(
        "allocation:",
        f"{report['causal_findings']['original_allocation_sectors']} sectors",
        f"max={report['causal_findings']['maximum_in_place_size']} bytes",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
