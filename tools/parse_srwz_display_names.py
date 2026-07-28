#!/usr/bin/env python3
"""Parse and verify COMPDATA pilot and unit display-name structures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.display_names import DisplayNameError, build_display_name_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/display-names/compdata.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse all configured pilot and unit display-name records. "
            "Original text is written only below ignored work/."
        )
    )
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
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["report"],
        WORK_ROOT,
    )
    manifest_path = (args.manifest or PROJECT_ROOT / outputs["manifest"]).resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        report, manifest = build_display_name_report(
            PROJECT_ROOT,
            config_path,
        )
    except DisplayNameError as error:
        raise SystemExit(str(error)) from error

    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_status = "refreshed"
    else:
        if not manifest_path.is_file():
            raise SystemExit(
                "display-name manifest missing; review and use --refresh-manifest"
            )
        committed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if committed != manifest:
            raise SystemExit(
                "display-name manifest drift; review and use --refresh-manifest"
            )
        manifest_status = "verified"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "display names:",
        f"pilots={manifest['pilot_table']['record_count']}",
        f"pilot_fields={manifest['pilot_table']['entry_count']}",
        f"unit_records={manifest['unit_table']['record_count']}",
        f"unit_names={manifest['unit_table']['unique_name_count']}",
        f"probes={len(manifest['probes'])}",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
