#!/usr/bin/env python3
"""Prepare an ignored workspace for one SRWZ UI runtime matrix case."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.ui_runtime_evidence import (
    UiRuntimeEvidenceError,
    prepare_case_workspace,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create the exact-ISO plan, evidence draft and capture directories "
            "for one UI runtime case. This does not launch PCSX2."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan_path, draft_path = prepare_case_workspace(
            PROJECT_ROOT,
            args.matrix.resolve(),
            args.case_id,
            force=args.force,
        )
    except UiRuntimeEvidenceError as error:
        raise SystemExit(str(error)) from error
    print(f"case plan: {plan_path}")
    print(f"evidence draft: {draft_path}")
    print("PCSX2 was not launched; runtime status remains not_tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
