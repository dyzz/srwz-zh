#!/usr/bin/env python3
"""Build one deterministic localized KVMDATA UI-atlas component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_atlas_localization import build_ui_atlas_localization


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/assets/ui-info-atlas-zh.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--print-output-locks",
        action="store_true",
        help="Print deterministic locks without writing component files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    outputs = config["outputs"]
    component_root = require_work_output(
        PROJECT_ROOT / outputs["component_root"],
        WORK_ROOT,
    )
    archive_path = component_root / config["target"]["member"]
    reference_path = require_work_output(
        PROJECT_ROOT / outputs["reference_png"],
        WORK_ROOT,
    )
    localized_path = require_work_output(
        PROJECT_ROOT / outputs["localized_png"],
        WORK_ROOT,
    )
    report_path = component_root / "component-validation.json"
    paths = (archive_path, reference_path, localized_path, report_path)
    existing = [path for path in paths if path.exists()]
    if existing and not args.force and not args.print_output_locks:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    try:
        payloads, report = build_ui_atlas_localization(
            PROJECT_ROOT,
            WORK_ROOT,
            config_path,
            enforce_expected=not args.print_output_locks,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if args.print_output_locks:
        print(json.dumps(report["expected_lock"], indent=2))
        return 0

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    localized_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(payloads["archive"])
    reference_path.write_bytes(payloads["reference_png"])
    localized_path.write_bytes(payloads["localized_png"])
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI atlas localization:",
        f"profile={report['profile_id']}",
        f"chunk={report['target']['chunk_index']}",
        f"pixels={report['text_audit']['added_pixel_count']}",
        f"bytes={report['injection']['archive_diff_from_erased_base']['diff_count']}",
        "runtime=mapping-pending",
    )
    print(f"archive: {archive_path}")
    print(f"reference: {reference_path}")
    print(f"localized: {localized_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
