#!/usr/bin/env python3
"""Deterministically rebuild and reparse the P1 world-history component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.world_history import (
    WorldHistoryError,
    audit_world_history_outputs,
    build_world_history_component,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/summary/world-history-component.json"


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
        "slps": component_root / "SLPS_258.87",
        "vt1": component_root / "DATA/VT1.BIN",
        "mtv_pros": component_root / "DATA/MTV_PROS.BIN",
    }
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["validation"],
        WORK_ROOT,
    )
    manifest_path = (args.manifest or PROJECT_ROOT / outputs["manifest"]).resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    missing = [path for path in paths.values() if not path.is_file()]
    if missing:
        raise SystemExit(
            "world-history component missing; run "
            f"build_ui_p1_world_history.py: {missing[0]}"
        )
    actual_outputs = {name: path.read_bytes() for name, path in paths.items()}
    try:
        expected_outputs, report = build_world_history_component(
            PROJECT_ROOT,
            config_path,
        )
        if actual_outputs != expected_outputs:
            raise WorldHistoryError(
                "world-history component differs from deterministic rebuild"
            )
        report["independent_reread"] = audit_world_history_outputs(
            PROJECT_ROOT,
            config_path,
            actual_outputs,
        )
    except WorldHistoryError as error:
        raise SystemExit(str(error)) from error

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
                "world-history manifest missing; review and use --refresh-manifest"
            )
        committed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if committed != report:
            raise SystemExit(
                "world-history manifest drift; review and use --refresh-manifest"
            )
        manifest_status = "verified"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI P1 world history verified:",
        f"entries={report['selection']['translation_entry_count']}",
        f"chunks={report['archive']['chunk_count']}",
        f"changed={report['archive']['changed_chunk_count']}",
        f"sha256={report['archive']['output']['sha256']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
