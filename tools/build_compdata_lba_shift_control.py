#!/usr/bin/env python3
"""Build an unchanged-stream COMPDATA control that shifts later ISO members."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.compdata_diagnostics import build_one_sector_shift_control
from srwz.diagnostics import require_work_output
from srwz.font import sha256_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
SOURCE = WORK_ROOT / "disc/DATA/COMPDATA.BN"
SOURCE_SIZE = 144990
SOURCE_SHA256 = (
    "fd2ba668e7e012de64b953e5bc404ebb"
    "85a8bdd37666f2d95980b283a64ded34"
)
DEFAULT_OUTPUT_ROOT = (
    WORK_ROOT / "build/compdata-step-00-lba-shift-control/components"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = require_work_output(args.output_root.resolve(), WORK_ROOT)
    output_path = output_root / "DATA/COMPDATA.BN"
    report_path = output_root / "component-validation.json"
    if (
        (output_path.exists() or report_path.exists())
        and not args.force
    ):
        raise SystemExit(f"outputs exist; use --force: {output_root}")
    source = SOURCE.read_bytes()
    if len(source) != SOURCE_SIZE or sha256_bytes(source) != SOURCE_SHA256:
        raise SystemExit("original COMPDATA source lock drift")
    candidate, facts = build_one_sector_shift_control(source)
    report = {
        "schema_version": 1,
        "status": "diagnostic_lba_shift_control_built_runtime_pending",
        "purpose": (
            "Keep the original compressed stream and decoded bytes exact, "
            "but cross from 71 to 72 ISO sectors using a zero tail."
        ),
        "source": {
            "path": "work/disc/DATA/COMPDATA.BN",
            "size": SOURCE_SIZE,
            "sha256": SOURCE_SHA256,
        },
        "control": facts,
        "runtime_boundary": (
            "A boot failure in this control can be attributed to the "
            "one-sector layout shift, not to changed compressed tokens or "
            "decoded COMPDATA bytes."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(candidate)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "COMPDATA LBA shift control:",
        f"{facts['source_sectors']}->{facts['candidate_sectors']} sectors",
        f"zero_tail={facts['zero_tail_size']}",
    )
    print(f"component: {output_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
