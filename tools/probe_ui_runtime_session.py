#!/usr/bin/env python3
"""Record exact-ISO PCSX2/PINE R0 evidence for one prepared UI case."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_runtime_evidence import (
    UiRuntimeEvidenceError,
    build_case_plan,
    build_session_probe,
)
from verify_pcsx2_font_runtime import (
    PINE_ID,
    PINE_TITLE,
    PINE_VERSION,
    PineError,
    PineClient,
    default_socket_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_MATRIX = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify exact ISO bytes, PCSX2 PINE identity, Running state and "
            "the case-owned emulator log. PCSX2 must already be running."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--socket", type=Path, default=default_socket_path())
    parser.add_argument("--log", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--fresh-process",
        action="store_true",
        help="Assert this run began from a new PCSX2 process, not a savestate.",
    )
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
        log_path = (
            args.log.resolve()
            if args.log is not None
            else (PROJECT_ROOT / plan["workspace"]["emulator_log"]).resolve()
        )
        output_path = require_work_output(
            (
                args.output.resolve()
                if args.output is not None
                else (
                    PROJECT_ROOT / plan["workspace"]["session_probe"]
                ).resolve()
            ),
            WORK_ROOT,
        )
        if output_path.exists() and not args.force:
            raise UiRuntimeEvidenceError(
                f"session probe exists; use --force: {output_path}"
            )
        client = PineClient(args.socket)
        version = client.read_text(PINE_VERSION)
        title = client.read_text(PINE_TITLE)
        game_id = client.read_text(PINE_ID)
        status_before = client.status()
        status_after = client.status()
        report = build_session_probe(
            PROJECT_ROOT,
            plan,
            pine_version=version,
            game_title=title,
            game_id=game_id,
            status_before=status_before,
            status_after=status_after,
            fresh_process=args.fresh_process,
            log_path=log_path,
        )
    except (OSError, PineError, UiRuntimeEvidenceError) as error:
        raise SystemExit(str(error)) from error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"session probe passed: {output_path}")
    print(f"case: {args.case_id}")
    print(f"ISO: {report['artifact']['iso_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
