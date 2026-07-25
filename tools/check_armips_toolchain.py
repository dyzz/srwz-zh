#!/usr/bin/env python3
"""Build pinned official armips source twice and audit project outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.toolchain import ToolchainError, validate_armips_toolchain


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate official armips source provenance, two clean "
            "reproducible builds, cross-version project ASM output and "
            "strict byte-level patch contracts."
        )
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=(
            PROJECT_ROOT
            / "config"
            / "toolchain"
            / "armips.lock.json"
        ),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=WORK_ROOT / "toolchain" / "armips-validation.json",
    )
    parser.add_argument(
        "--bootstrap-missing",
        action="store_true",
        help=(
            "clone only the pinned official armips source when neither "
            "configured source checkout exists"
        ),
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = require_work_output(args.json_output, WORK_ROOT)
    if output.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output}")
    try:
        report = validate_armips_toolchain(
            PROJECT_ROOT,
            args.lock,
            bootstrap_missing=args.bootstrap_missing,
        )
    except ToolchainError as error:
        raise SystemExit(f"armips validation failed: {error}") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"json: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
