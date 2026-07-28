#!/usr/bin/env python3
"""Rebuild and verify a configured integrated core UI component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_integration import (
    UiIntegrationError,
    build_ui_p1_core_component,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-integration/p1-core.json"


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
    outputs_config = config["outputs"]
    component_root = require_work_output(
        PROJECT_ROOT / outputs_config["component_root"],
        WORK_ROOT,
    )
    paths = {
        "slps": component_root / "SLPS_258.87",
        "vt1": component_root / "DATA/VT1.BIN",
        "mtv_pros": component_root / "DATA/MTV_PROS.BIN",
        "compdata": component_root / "DATA/COMPDATA.BN",
    }
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs_config["validation"],
        WORK_ROOT,
    )
    manifest_path = (
        args.manifest or PROJECT_ROOT / outputs_config["manifest"]
    ).resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        expected_outputs, report = build_ui_p1_core_component(
            PROJECT_ROOT,
            config_path,
        )
    except (KeyError, UiIntegrationError) as error:
        raise SystemExit(str(error)) from error
    for name, path in paths.items():
        if not path.is_file():
            raise SystemExit(
                f"integrated component missing; run build_ui_core.py: {path}"
            )
        if path.read_bytes() != expected_outputs[name]:
            raise SystemExit(
                f"integrated component differs from rebuild: {name}"
            )

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
                "integrated manifest missing; review and use "
                "--refresh-manifest"
            )
        committed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if committed != report:
            raise SystemExit(
                "integrated manifest drift; review and use "
                "--refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI core verified:",
        f"profile={report['profile_id']}",
        f"SLPS={report['outputs']['slps']['sha256']}",
        f"VT1={report['outputs']['vt1']['sha256']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
