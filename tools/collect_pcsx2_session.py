#!/usr/bin/env python3
"""Collect stable PCSX2 logs and screenshots into a runtime case workspace."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.pcsx2_session import (
    Pcsx2SessionError,
    collect_pcsx2_session,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "After PCSX2 stops, copy its log and F8 screenshots into the "
            "case-owned work/runtime/ui-cases directory and hash them."
        )
    )
    parser.add_argument("--lock", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report_path = collect_pcsx2_session(
            PROJECT_ROOT,
            args.lock.resolve(),
        )
    except (OSError, Pcsx2SessionError) as error:
        raise SystemExit(str(error)) from error
    print(f"collection: {report_path}")
    print("status: collected_unreviewed")
    print("No visual assertion or runtime verdict was promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
