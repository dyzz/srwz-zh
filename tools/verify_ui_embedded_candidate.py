#!/usr/bin/env python3
"""Rebuild and verify a configured fixed-span embedded UI component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_embedded_candidate import (
    UiEmbeddedCandidateError,
    build_ui_embedded_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config/ui-writeback/ui-p3-fresh-boot-slps.json"
)


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
        payloads, report = build_ui_embedded_candidate(
            PROJECT_ROOT,
            config_path,
        )
    except (KeyError, OSError, UiEmbeddedCandidateError) as error:
        raise SystemExit(str(error)) from error
    for member, expected in payloads.items():
        path = component_root / member
        if not path.is_file():
            raise SystemExit(
                "embedded UI candidate is missing; run "
                f"build_ui_embedded_candidate.py: {path}"
            )
        if path.read_bytes() != expected:
            raise SystemExit(
                f"embedded UI candidate differs from rebuild: {member}"
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
                "embedded UI candidate manifest is missing; review and use "
                "--refresh-manifest"
            )
        committed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if committed != report:
            raise SystemExit(
                "embedded UI candidate manifest drift; review and use "
                "--refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "embedded UI candidate verified:",
        f"scenes={report['selection']['scene_count']}",
        f"entries={report['selection']['entry_count']}",
        f"changed={report['composition']['slice_changed_byte_count']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
