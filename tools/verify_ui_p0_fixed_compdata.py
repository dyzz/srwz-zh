#!/usr/bin/env python3
"""Rebuild and verify the fixed-span P0 COMPDATA manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_menu import (
    UiMenuError,
    build_fixed_compdata_component,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-writeback/ui-p0-compdata-fixed.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
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
    component_path = component_root / "DATA/COMPDATA.BN"
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["validation"],
        WORK_ROOT,
    )
    manifest_path = (args.manifest or PROJECT_ROOT / outputs["manifest"]).resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        expected_component, report = build_fixed_compdata_component(
            PROJECT_ROOT,
            config_path,
        )
    except UiMenuError as error:
        raise SystemExit(str(error)) from error
    if not component_path.is_file():
        raise SystemExit(
            f"component missing; run build_ui_p0_fixed_compdata.py: {component_path}"
        )
    actual_component = component_path.read_bytes()
    if actual_component != expected_component:
        raise SystemExit("UI P0 fixed COMPDATA differs from deterministic rebuild")

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
                "manifest not found; review and run --refresh-manifest: "
                f"{manifest_path}"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(
                f"cannot load UI fixed COMPDATA manifest {manifest_path}: {error}"
            ) from error
        if manifest != report:
            raise SystemExit(
                "UI fixed COMPDATA manifest drift; review, then run --refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI P0 fixed COMPDATA verified:",
        f"covered={report['selection']['fixed_covered_entry_count']}",
        f"writes={report['write']['entry_count']}",
        f"sha256={report['compressed_component']['output_sha256']}",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
