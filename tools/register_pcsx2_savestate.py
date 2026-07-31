#!/usr/bin/env python3
"""Freeze an F1-created PCSX2 state and its card snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.pcsx2_session import (
    Pcsx2SessionError,
    newest_session_savestate,
    register_pcsx2_savestate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROOT = PROJECT_ROOT / "work/runtime/pcsx2-sessions"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Register one savestate as an acceleration-only bundle locked "
            "to its exact ISO, PCSX2 binary and current isolated card."
        )
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--state-id", required=True)
    parser.add_argument(
        "--state",
        type=Path,
        help="State created in this session; defaults to newest sstates/*.p2s.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session_root = (SESSIONS_ROOT / args.session_id).resolve()
    lock_path = session_root / "session-lock.json"
    try:
        state_path = (
            args.state.resolve()
            if args.state is not None
            else newest_session_savestate(session_root)
        )
        receipt_path = register_pcsx2_savestate(
            PROJECT_ROOT,
            lock_path,
            state_path,
            state_id=args.state_id,
        )
    except (OSError, Pcsx2SessionError) as error:
        raise SystemExit(str(error)) from error
    print(f"savestate receipt: {receipt_path}")
    print("scope: acceleration_only")
    print(
        "The state does not promote a missing memory-card fixture or "
        "replace a fresh primary runtime run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
