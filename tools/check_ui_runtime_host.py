#!/usr/bin/env python3
"""Inspect the local PCSX2 host without launching the emulator."""

from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_runtime_host import (
    UiRuntimeHostError,
    build_runtime_host_preflight,
    pcsx2_architectures,
    rosetta_available,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_MATRIX = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"
DEFAULT_PCSX2 = Path("/Applications/PCSX2.app/Contents/MacOS/PCSX2")
DEFAULT_OUTPUT = WORK_ROOT / "review/ui-runtime-host-preflight.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify PCSX2 architecture, Rosetta availability, the current "
            "integrated ISO lock and route-ready case set without launching "
            "the emulator."
        )
    )
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--pcsx2", type=Path, default=DEFAULT_PCSX2)
    parser.add_argument(
        "--artifact-id",
        help="Select one artifact when route-ready cases span multiple ISOs.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = require_work_output(args.output.resolve(), WORK_ROOT)
    if output_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output_path}")
    pine_socket = Path(os.environ.get("TMPDIR", "/tmp")) / "pcsx2.sock"
    try:
        report = build_runtime_host_preflight(
            PROJECT_ROOT,
            args.matrix.resolve(),
            args.pcsx2.resolve(),
            host_architecture=platform.machine(),
            binary_architectures=pcsx2_architectures(args.pcsx2.resolve()),
            has_rosetta=rosetta_available(),
            pine_socket_path=pine_socket,
            artifact_id=args.artifact_id,
        )
    except (OSError, UiRuntimeHostError) as error:
        raise SystemExit(str(error)) from error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"runtime host: {report['status']}")
    print(f"route-ready cases: {report['ready_cases']['count']}")
    print(f"PCSX2: {report['host']['pcsx2']['path']}")
    print(f"blockers: {report['launch']['blockers']}")
    print(f"report: {output_path}")
    print("PCSX2 was not launched; runtime status remains not_tested")
    return 0 if report["launch"]["safe_to_launch"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
