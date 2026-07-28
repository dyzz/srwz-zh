#!/usr/bin/env python3
"""Audit researched pilot/unit display-name coverage and font readiness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.display_names import DisplayNameError
from srwz.display_name_coverage import (
    DisplayNameCoverageError,
    audit_display_name_coverage,
    write_display_name_coverage_tsv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config/display-names/researched-coverage.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Select exact display-name matches from researched glossary terms, "
            "measure current font/capacity readiness and write an ignored "
            "source-bearing review queue."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--review-json", type=Path)
    parser.add_argument("--review-tsv", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        outputs = config["outputs"]
        review_path = require_work_output(
            args.review_json or PROJECT_ROOT / outputs["review_json"],
            WORK_ROOT,
        )
        tsv_path = require_work_output(
            args.review_tsv or PROJECT_ROOT / outputs["review_tsv"],
            WORK_ROOT,
        )
        manifest_path = (
            args.manifest or PROJECT_ROOT / outputs["manifest"]
        ).resolve()
        existing = [path for path in (review_path, tsv_path) if path.exists()]
        if existing and not args.force:
            raise DisplayNameCoverageError(
                f"review output exists; use --force: {existing[0]}"
            )
        report, manifest = audit_display_name_coverage(
            PROJECT_ROOT,
            config_path,
        )
    except (
        KeyError,
        OSError,
        json.JSONDecodeError,
        DisplayNameError,
        DisplayNameCoverageError,
    ) as error:
        raise SystemExit(str(error)) from error

    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with tsv_path.open("w", encoding="utf-8", newline="") as stream:
        write_display_name_coverage_tsv(report, stream)

    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_state = "refreshed"
    else:
        if not manifest_path.is_file():
            raise SystemExit(
                "coverage manifest is missing; review and use --refresh-manifest"
            )
        committed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if committed != manifest:
            raise SystemExit(
                "coverage manifest drift; review and use --refresh-manifest"
            )
        manifest_state = "verified"

    summary = report["summary"]
    print(
        "display-name coverage:",
        f"selected={summary['selected_entry_count']}",
        f"font-ready={summary['current_font_ready_entry_count']}",
        f"font-missing={summary['current_font_missing_entry_count']}",
        f"missing-chars={summary['current_font_missing_character_count']}",
        f"renderer-missing={summary['current_renderer_missing_entry_count']}",
        (
            "renderer-chars="
            f"{summary['current_renderer_missing_character_count']}"
        ),
        (
            "remaining-slots="
            f"{summary['projected_remaining_candidate_slot_count']}"
        ),
        f"unresolved={summary['unresolved_entry_count']}",
        f"overflow={summary['projected_overflow_entry_count']}",
    )
    print(f"manifest {manifest_state}: {manifest_path}")
    print(f"review JSON: {review_path}")
    print(f"review TSV: {tsv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
