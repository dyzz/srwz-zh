#!/usr/bin/env python3
"""Re-read every input in one prepared PCSX2 session lock."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.pcsx2_session import (
    Pcsx2SessionError,
    validate_pcsx2_session,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the exact ISO, portable PCSX2 binary, settings, memory "
            "card and optional savestate referenced by a session lock."
        )
    )
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument(
        "--allow-memory-card-drift",
        action="store_true",
        help=(
            "Allow an in-game write after launch; all other inputs remain "
            "locked. State registration/collection snapshots the current card."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = validate_pcsx2_session(
            PROJECT_ROOT,
            args.lock.resolve(),
            allow_memory_card_drift=args.allow_memory_card_drift,
        )
    except (OSError, Pcsx2SessionError) as error:
        raise SystemExit(str(error)) from error
    print("PCSX2 session: ready")
    print(f"session: {report['session_id']}")
    print(f"case: {report['case']['case_id']}")
    print(f"boot source: {report['launch']['boot_source']}")
    print(f"ISO: {report['artifact']['iso_sha256']}")
    print(
        "primary receipt allowed: "
        f"{report['evidence']['primary_runtime_receipt_allowed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
