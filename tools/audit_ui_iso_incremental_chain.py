#!/usr/bin/env python3
"""Validate and lock the first-five-based incremental UI ISO chain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.ui_iso_incremental import (
    UiIsoIncrementalError,
    audit_ui_iso_incremental_chain,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/iso/ui-incremental-chain.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "manifests/ui-iso-incremental-validation.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    manifests_root = (PROJECT_ROOT / "manifests").resolve()
    try:
        output.relative_to(manifests_root)
    except ValueError as error:
        raise SystemExit("output must stay under manifests/") from error
    if output.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output}")
    try:
        report = audit_ui_iso_incremental_chain(
            PROJECT_ROOT,
            args.config.resolve(),
        )
    except (OSError, UiIsoIncrementalError) as error:
        raise SystemExit(str(error)) from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"incremental ISO chain: {report['status']}")
    print(f"promoted: {report['promoted_candidate']['step_id']}")
    print(f"blocked: {report['blocked_candidate']['step_id']}")
    print(f"report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
