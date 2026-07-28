#!/usr/bin/env python3
"""Rebuild and verify one localized KVMDATA UI-atlas component."""

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
    paths = {
        "archive": component_root / config["target"]["member"],
        "reference_png": require_work_output(
            PROJECT_ROOT / outputs["reference_png"],
            WORK_ROOT,
        ),
        "localized_png": require_work_output(
            PROJECT_ROOT / outputs["localized_png"],
            WORK_ROOT,
        ),
    }
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["validation"],
        WORK_ROOT,
    )
    manifest_path = (
        args.manifest or PROJECT_ROOT / outputs["manifest"]
    ).resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        expected_payloads, report = build_ui_atlas_localization(
            PROJECT_ROOT,
            WORK_ROOT,
            config_path,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    for name, path in paths.items():
        if not path.is_file():
            raise SystemExit(
                "localized atlas is missing; run "
                f"build_ui_atlas_localization.py: {path}"
            )
        if path.read_bytes() != expected_payloads[name]:
            raise SystemExit(f"localized atlas rebuild differs: {name}")

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
                "localized-atlas manifest is missing; review and use "
                "--refresh-manifest"
            )
        committed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if committed != report:
            raise SystemExit(
                "localized-atlas manifest drift; review and use "
                "--refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI atlas localization verified:",
        f"profile={report['profile_id']}",
        f"chunk={report['target']['chunk_index']}",
        f"pixels={report['text_audit']['added_pixel_count']}",
        f"sha256={report['outputs']['archive']['sha256']}",
        "runtime=mapping-pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
