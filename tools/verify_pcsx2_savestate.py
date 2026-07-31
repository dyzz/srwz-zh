#!/usr/bin/env python3
"""Verify a PCSX2 savestate receipt and every locked input."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.pcsx2_session import (
    Pcsx2SessionError,
    verify_savestate_receipt,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the savestate, memory-card snapshot, exact ISO, source "
            "session and PCSX2 binary bound by a receipt."
        )
    )
    parser.add_argument("--receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = verify_savestate_receipt(
            PROJECT_ROOT,
            args.receipt.resolve(),
        )
    except (OSError, Pcsx2SessionError) as error:
        raise SystemExit(str(error)) from error
    print("PCSX2 savestate: valid acceleration bundle")
    print(f"state: {receipt['state_id']}")
    print(f"case: {receipt['case_id']}")
    print(f"ISO: {receipt['artifact']['iso_sha256']}")
    print("primary runtime acceptance: not allowed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
