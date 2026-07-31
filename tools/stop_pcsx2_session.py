#!/usr/bin/env python3
"""Stop the exact PCSX2 process owned by one isolated session."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from srwz.pcsx2_session import Pcsx2SessionError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROOT = PROJECT_ROOT / "work/runtime/pcsx2-sessions"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send SIGINT to the PID recorded by one PCSX2 session, after "
            "checking that its command still names that session's binary."
        )
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def _load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Pcsx2SessionError(f"cannot read process record: {error}") from error
    if not isinstance(value, dict):
        raise Pcsx2SessionError("process record root is not an object")
    return value


def main() -> int:
    args = parse_args()
    if args.timeout < 1 or args.timeout > 60:
        raise SystemExit("--timeout must be between 1 and 60 seconds")
    session_root = (SESSIONS_ROOT / args.session_id).resolve()
    try:
        session_root.relative_to(SESSIONS_ROOT.resolve())
    except ValueError as error:
        raise SystemExit("session_id escapes the sessions root") from error
    process_path = session_root / "process.json"
    try:
        record = _load_object(process_path)
        pid = record.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise Pcsx2SessionError("process record PID is invalid")
        command = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        expected_binary = str(
            session_root / "PCSX2.app/Contents/MacOS/PCSX2"
        )
        if expected_binary not in command:
            raise Pcsx2SessionError(
                "recorded PID is not this session's PCSX2 process"
            )
        os.kill(pid, signal.SIGINT)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            raise Pcsx2SessionError(
                "PCSX2 did not stop after SIGINT; inspect it before escalation"
            )
    except (OSError, Pcsx2SessionError) as error:
        raise SystemExit(str(error)) from error

    stopped_path = session_root / "stopped.json"
    stopped_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "stopped",
                "pid": pid,
                "signal": "SIGINT",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"PCSX2 stopped: PID {pid}")
    print(f"record: {stopped_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
