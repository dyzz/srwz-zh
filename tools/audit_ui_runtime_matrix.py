#!/usr/bin/env python3
"""Validate the selected SRWZ UI runtime routes and evidence gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_runtime_matrix import (
    UiRuntimeMatrixError,
    audit_ui_runtime_matrix,
    build_runtime_matrix_manifest,
    write_runtime_matrix_tsv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests/ui-runtime-test-matrix.json"
DEFAULT_REPORT = WORK_ROOT / "review/ui-runtime-test-matrix.json"
DEFAULT_TSV = WORK_ROOT / "review/ui-runtime-test-matrix.tsv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate UI runtime scene selection, exact ISO locks, fixture "
            "readiness, capture points and evidence requirements."
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
        report = audit_ui_runtime_matrix(
            PROJECT_ROOT,
            args.config.resolve(),
        )
    except UiRuntimeMatrixError as error:
        raise SystemExit(str(error)) from error

    manifest_path = args.manifest.resolve()
    expected_manifest = build_runtime_matrix_manifest(report)
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
            committed_manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(
                f"cannot load UI runtime manifest {manifest_path}: {error}"
            ) from error
        if committed_manifest != expected_manifest:
            raise SystemExit(
                "UI runtime matrix manifest drift; review the local report, "
                "then run --refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with tsv_path.open("w", encoding="utf-8", newline="") as stream:
        write_runtime_matrix_tsv(report, stream)

    summary = report["summary"]
    print(
        f"UI runtime cases: {summary['case_count']}; "
        f"selected scenes: {summary['selected_scene_count']}; "
        f"deferred scenes: {summary['deferred_scene_count']}"
    )
    print(
        f"route-ready cases: {summary['route_ready_case_count']}; "
        f"missing-fixture cases: {summary['missing_fixture_case_count']}; "
        f"runtime passed: {summary['runtime_passed_case_count']}"
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    print(f"tsv: {tsv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
