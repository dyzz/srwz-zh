#!/usr/bin/env python3
"""Audit the deferred embedded SLPS UI scene partition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_embedded_scenes import (
    UiEmbeddedSceneError,
    audit_ui_embedded_scenes,
    build_embedded_scene_manifest,
    write_embedded_scene_tsv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-embedded-scenes.json"
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests/ui-embedded-scene-map.json"
DEFAULT_REPORT = WORK_ROOT / "review/ui-embedded-scene-map.json"
DEFAULT_TSV = WORK_ROOT / "review/ui-embedded-scene-map.tsv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove that screen-oriented embedded SLPS groups are disjoint, "
            "exhaustive, source-fresh and paired with runtime test routes."
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
        report = audit_ui_embedded_scenes(
            PROJECT_ROOT,
            args.config.resolve(),
        )
    except UiEmbeddedSceneError as error:
        raise SystemExit(str(error)) from error

    expected_manifest = build_embedded_scene_manifest(report)
    manifest_path = args.manifest.resolve()
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
                "embedded UI scene manifest is absent; review the local "
                f"report, then run --refresh-manifest: {manifest_path}"
            )
        try:
            committed = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(
                f"cannot load embedded UI scene manifest {manifest_path}: {error}"
            ) from error
        if committed != expected_manifest:
            raise SystemExit(
                "embedded UI scene manifest drift; review the local report, "
                "then run --refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with tsv_path.open("w", encoding="utf-8", newline="") as stream:
        write_embedded_scene_tsv(report, stream)

    summary = report["summary"]
    print(
        f"embedded UI groups: {summary['group_count']}; "
        f"classified entries: {summary['classified_entry_count']}; "
        f"unclassified: {summary['unclassified_entry_count']}; "
        f"overlap: {summary['overlap_entry_count']}"
    )
    print(
        "classification entries: "
        f"{summary['classification_entry_counts']}; "
        f"runtime passed: {summary['runtime_passed_group_count']}"
    )
    print(
        "writeback readiness: "
        f"{summary['writeback_readiness_group_counts']}; "
        f"fixed-span entries: {summary['fixed_span_ready_entry_count']}; "
        f"user-facing fixed-span entries: "
        f"{summary['fixed_span_ready_user_facing_entry_count']}; "
        f"font gaps: {summary['font_missing_character_count']}; "
        f"overflow entries: {summary['overflow_entry_count']}"
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    print(f"tsv: {tsv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
