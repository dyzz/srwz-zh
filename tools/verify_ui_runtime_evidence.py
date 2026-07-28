#!/usr/bin/env python3
"""Verify one completed UI evidence draft and emit a hash-only receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_runtime_evidence import (
    UiRuntimeEvidenceError,
    build_case_plan,
    verify_runtime_evidence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_MATRIX = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a case session probe, screenshots or sequences, optional "
            "atlas texture delta and all visual assertions."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan, _ = build_case_plan(
            PROJECT_ROOT,
            args.matrix.resolve(),
            args.case_id,
        )
        draft_path = (
            args.draft.resolve()
            if args.draft is not None
            else (
                PROJECT_ROOT / plan["workspace"]["evidence_draft"]
            ).resolve()
        )
        output_path = require_work_output(
            (
                args.output.resolve()
                if args.output is not None
                else (
                    PROJECT_ROOT
                    / plan["workspace"]["root"]
                    / "evidence-receipt.json"
                ).resolve()
            ),
            WORK_ROOT,
        )
        if not draft_path.is_file():
            raise UiRuntimeEvidenceError(
                f"evidence draft was not found: {draft_path}"
            )
        if output_path.exists() and not args.force:
            raise UiRuntimeEvidenceError(
                f"evidence receipt exists; use --force: {output_path}"
            )
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        if not isinstance(draft, dict):
            raise UiRuntimeEvidenceError("evidence draft root must be an object")
        receipt = verify_runtime_evidence(
            PROJECT_ROOT,
            plan,
            draft,
        )
    except (OSError, json.JSONDecodeError, UiRuntimeEvidenceError) as error:
        raise SystemExit(str(error)) from error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"runtime evidence passed: {output_path}")
    print(
        "Review the hash-only receipt before copying it under "
        "manifests/runtime/ui-cases/ and updating the matrix lock."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
