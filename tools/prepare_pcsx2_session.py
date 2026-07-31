#!/usr/bin/env python3
"""Prepare one isolated, hash-locked PCSX2 runtime session."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.pcsx2_session import (
    Pcsx2SessionError,
    prepare_pcsx2_session,
    with_exploratory_iso,
)
from srwz.ui_runtime_evidence import (
    UiRuntimeEvidenceError,
    build_case_plan,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"
DEFAULT_PCSX2_APP = Path("/Applications/PCSX2.app")
DEFAULT_SETTINGS = (
    PROJECT_ROOT / "work/runtime/first-five/inis/PCSX2.ini"
)
DEFAULT_BIOS = (
    Path.home() / "Library/Application Support/PCSX2/bios"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clone a portable PCSX2 root under work/, bind one exact matrix "
            "ISO and optionally copy an isolated memory card or a verified "
            "savestate bundle. The emulator is not launched."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--pcsx2-app", type=Path, default=DEFAULT_PCSX2_APP)
    parser.add_argument(
        "--settings-template",
        type=Path,
        default=DEFAULT_SETTINGS,
    )
    parser.add_argument("--bios-directory", type=Path, default=DEFAULT_BIOS)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--memory-card", type=Path)
    source.add_argument("--savestate-receipt", type=Path)
    parser.add_argument(
        "--iso",
        type=Path,
        help=(
            "Use another exact ISO under build/iso for exploration only. "
            "This never changes the reviewed matrix artifact."
        ),
    )
    parser.add_argument(
        "--exploratory",
        action="store_true",
        help=(
            "Allow an unpromoted card candidate or a hash-locked savestate. "
            "Such a session cannot produce primary runtime acceptance."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        case_plan, _ = build_case_plan(
            PROJECT_ROOT,
            args.matrix.resolve(),
            args.case_id,
        )
        if args.iso is not None:
            if not args.exploratory:
                raise Pcsx2SessionError(
                    "--iso requires --exploratory"
                )
            case_plan = with_exploratory_iso(
                PROJECT_ROOT,
                case_plan,
                args.iso,
            )
        lock_path, launch_path = prepare_pcsx2_session(
            PROJECT_ROOT,
            case_plan,
            session_id=args.session_id,
            pcsx2_app=args.pcsx2_app,
            settings_template=args.settings_template,
            bios_directory=args.bios_directory,
            memory_card=args.memory_card,
            savestate_receipt=args.savestate_receipt,
            exploratory=args.exploratory,
        )
    except (OSError, Pcsx2SessionError, UiRuntimeEvidenceError) as error:
        raise SystemExit(str(error)) from error

    print(f"session lock: {lock_path}")
    print(f"launch plan: {launch_path}")
    print("PCSX2 was not launched")
    print(
        "verify: python3 tools/verify_pcsx2_session.py "
        f"--lock {lock_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
