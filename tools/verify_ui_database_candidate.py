#!/usr/bin/env python3
"""Rebuild and verify the P10 fixed-span database UI component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_database_candidate import (
    UiDatabaseCandidateError,
    build_ui_database_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "config/ui-writeback/ui-p10-database-fixed-core.json"
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
        payloads, report = build_ui_database_candidate(
            PROJECT_ROOT,
            config_path,
        )
    except (
        KeyError,
        OSError,
        UiDatabaseCandidateError,
    ) as error:
        raise SystemExit(str(error)) from error
    for member, payload in payloads.items():
        path = component_root / member
        if not path.is_file():
            raise SystemExit(
                "UI database candidate is missing; run "
                f"build_ui_database_candidate.py: {path}"
            )
        if path.read_bytes() != payload:
            raise SystemExit(
                "UI database candidate differs from deterministic rebuild: "
                f"{member}"
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
                "UI database manifest is missing; review and use "
                "--refresh-manifest"
            )
        if _load_json(manifest_path) != report:
            raise SystemExit(
                "UI database manifest drift; review and use "
                "--refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI database candidate verified:",
        f"entries={report['selection']['entry_count']}",
        f"members={len(payloads)}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
