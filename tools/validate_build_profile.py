#!/usr/bin/env python3
"""Validate one production build profile and its referenced inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.project import (
    ProjectConfigError,
    load_build_profile,
    validate_profile_encoding,
)
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = (
    PROJECT_ROOT / "config" / "build-profiles" / "canary-menu.json"
)
DEFAULT_TEXT_TABLE = (
    PROJECT_ROOT
    / "vendor"
    / "upstream-python"
    / "project"
    / "tbl_all.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile SurfaceSpec, zh corpus and codebook inputs, then "
            "prove every selected translation is encodable."
        )
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--text-table",
        type=Path,
        default=DEFAULT_TEXT_TABLE,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        selection = load_build_profile(PROJECT_ROOT, args.profile)
        table = load_text_table(args.text_table)
        validation = validate_profile_encoding(selection, table)
    except (OSError, ValueError, ProjectConfigError) as error:
        raise SystemExit(f"build profile validation failed: {error}") from error
    report = {
        "schema_version": 1,
        "status": "passed",
        "production_inputs": selection.to_metadata(),
        "profile_validation": validation,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
