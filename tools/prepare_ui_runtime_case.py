#!/usr/bin/env python3
"""Prepare ignored workspaces for SRWZ UI runtime matrix cases."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.ui_runtime_evidence import (
    UiRuntimeEvidenceError,
    prepare_case_workspace,
    route_ready_case_ids,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create exact-ISO plans, evidence drafts and capture directories "
            "for one UI runtime case or every route-ready case. This does not "
            "launch PCSX2."
        )
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case-id")
    selection.add_argument(
        "--all-route-ready",
        action="store_true",
        help="Prepare every not-tested case whose fixture is ready.",
    )
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        matrix_path = args.matrix.resolve()
        case_ids = (
            route_ready_case_ids(PROJECT_ROOT, matrix_path)
            if args.all_route_ready
            else (args.case_id,)
        )
        outputs = [
            (
                case_id,
                *prepare_case_workspace(
                    PROJECT_ROOT,
                    matrix_path,
                    case_id,
                    force=args.force,
                ),
            )
            for case_id in case_ids
        ]
    except UiRuntimeEvidenceError as error:
        raise SystemExit(str(error)) from error
    for case_id, plan_path, draft_path in outputs:
        print(f"case: {case_id}")
        print(f"case plan: {plan_path}")
        print(f"evidence draft: {draft_path}")
    print(f"prepared cases: {len(outputs)}")
    print("PCSX2 was not launched; runtime status remains not_tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
