#!/usr/bin/env python3
"""Build one isolated KVMDATA UI-atlas mapping canary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_atlas_canary import build_ui_atlas_map_canary


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config/canary/tim2-kvm2-info-map.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    outputs = config["outputs"]
    target_member = config["target"]["member"]
    component_root = require_work_output(
        PROJECT_ROOT / outputs["component_root"],
        WORK_ROOT,
    )
    archive_path = require_work_output(
        component_root / target_member,
        WORK_ROOT,
    )
    reference_path = require_work_output(
        PROJECT_ROOT / outputs["reference_png"],
        WORK_ROOT,
    )
    edited_path = require_work_output(
        PROJECT_ROOT / outputs["edited_png"],
        WORK_ROOT,
    )
    report_path = component_root / "component-validation.json"
    paths = (archive_path, reference_path, edited_path, report_path)
    existing = [path for path in paths if path.exists()]
    if existing and not args.force:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    try:
        payloads, report = build_ui_atlas_map_canary(
            PROJECT_ROOT,
            config_path,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    edited_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(payloads["archive"])
    reference_path.write_bytes(payloads["reference_png"])
    edited_path.write_bytes(payloads["edited_png"])
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI atlas mapping canary:",
        f"profile={report['profile_id']}",
        f"chunk={report['target']['chunk_index']}",
        f"locator={report['target']['semantic_locator']}",
        f"pixels={report['injection']['changed_pixel_count']}",
        f"bytes={report['injection']['archive_diff']['diff_count']}",
        "runtime=mapping-pending",
    )
    print(f"archive: {archive_path}")
    print(f"reference: {reference_path}")
    print(f"edited: {edited_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
