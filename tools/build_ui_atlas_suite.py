#!/usr/bin/env python3
"""Build the configured combined localized UI atlas component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_atlas_suite import UiAtlasSuiteError, build_ui_atlas_suite


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/assets/ui-atlas-suite-zh.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--print-output-locks", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_root = require_work_output(
        args.output_root or PROJECT_ROOT / config["outputs"]["component_root"],
        WORK_ROOT,
    )
    archive_path = output_root / "KURODATA/KVMDATA.BIN"
    report_path = output_root / "component-validation.json"
    existing = [path for path in (archive_path, report_path) if path.exists()]
    if existing and not args.force and not args.print_output_locks:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    try:
        archive, report = build_ui_atlas_suite(
            PROJECT_ROOT,
            config_path,
            enforce_expected_output=not args.print_output_locks,
        )
    except (KeyError, OSError, UiAtlasSuiteError) as error:
        raise SystemExit(str(error)) from error
    if args.print_output_locks:
        print(json.dumps(report["outputs"], indent=2))
        return 0
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI atlas suite:",
        f"profile={report['profile_id']}",
        f"chunks={report['composition']['chunk_indices']}",
        f"bytes={report['composition']['changed_byte_count']}",
        f"sha256={report['outputs']['archive']['sha256']}",
        "runtime=pending",
    )
    print(f"archive: {archive_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
