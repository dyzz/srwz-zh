#!/usr/bin/env python3
"""Validate and optionally launch one isolated PCSX2 session."""

from __future__ import annotations

import argparse
import json
import signal
import shutil
import subprocess
import time
from pathlib import Path

from srwz.pcsx2_session import (
    Pcsx2SessionError,
    sha256_file,
    validate_pcsx2_session,
)
from verify_pcsx2_font_runtime import (
    PINE_ID,
    PINE_VERSION,
    PineClient,
    default_socket_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Revalidate a session lock, print its exact argv and optionally "
            "start PCSX2 in the background. No GUI automation is used."
        )
    )
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Start the process after all hash and isolation checks pass.",
    )
    parser.add_argument("--pine-timeout", type=float, default=15.0)
    return parser.parse_args()


def stop_failed_launch(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    args = parse_args()
    if args.pine_timeout < 1 or args.pine_timeout > 60:
        raise SystemExit("--pine-timeout must be between 1 and 60 seconds")
    try:
        lock_path = args.lock.resolve()
        lock = validate_pcsx2_session(
            PROJECT_ROOT,
            lock_path,
            allow_memory_card_drift=True,
        )
    except (OSError, Pcsx2SessionError) as error:
        raise SystemExit(str(error)) from error

    argv = lock["launch"]["argv"]
    print("launch argv:")
    print(" ".join(repr(value) for value in argv))
    if not args.execute:
        print("dry run only; pass --execute to start PCSX2")
        return 0

    socket_path = default_socket_path()
    if socket_path.exists():
        raise SystemExit(
            f"PINE socket already exists; stop the other session: {socket_path}"
        )
    workspace = PROJECT_ROOT / lock["portable"]["root"]
    settings_baseline = (
        PROJECT_ROOT / lock["portable"]["settings"]["path"]
    )
    runtime_settings = (
        PROJECT_ROOT / lock["portable"]["runtime_settings_path"]
    )
    shutil.copy2(settings_baseline, runtime_settings)
    card_baseline = lock["portable"].get("memory_card")
    if card_baseline is not None:
        runtime_card = (
            PROJECT_ROOT
            / lock["portable"]["runtime_memory_card_path"]
        )
        shutil.copy2(PROJECT_ROOT / card_baseline["path"], runtime_card)
    process_path = workspace / "process.json"
    host_output_path = workspace / "logs/host-output.txt"
    if process_path.exists():
        raise SystemExit(
            f"process record already exists: {process_path}"
        )
    host_output_path.parent.mkdir(parents=True, exist_ok=True)
    with host_output_path.open("wb") as host_output:
        process = subprocess.Popen(
            argv,
            cwd=PROJECT_ROOT,
            stdout=host_output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    deadline = time.monotonic() + args.pine_timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(
                f"PCSX2 exited before PINE became ready: {process.returncode}"
            )
        if socket_path.exists():
            break
        time.sleep(0.05)
    else:
        stop_failed_launch(process)
        raise SystemExit(f"PINE socket did not appear: {socket_path}")

    expected_pine_version = f"PCSX2 v{lock['emulator']['version']}"
    last_pine_error = "PINE did not return an identity"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(
                f"PCSX2 exited during PINE readiness: {process.returncode}"
            )
        try:
            client = PineClient(socket_path, timeout=1)
            pine_version = client.read_text(PINE_VERSION)
            game_id = client.read_text(PINE_ID)
            pine_status = client.status()
        except Exception as error:
            last_pine_error = str(error)
            time.sleep(0.1)
            continue
        if (
            pine_version == expected_pine_version
            and game_id == "SLPS-25887"
            and pine_status == 0
        ):
            break
        last_pine_error = (
            f"{pine_version!r}, {game_id!r}, status={pine_status}"
        )
        time.sleep(0.1)
    else:
        stop_failed_launch(process)
        raise SystemExit(
            f"PINE identity did not become ready: {last_pine_error}"
        )
    record = {
        "schema_version": 1,
        "status": "running",
        "pid": process.pid,
        "session_lock": {
            "path": str(lock_path.relative_to(PROJECT_ROOT)),
            "size": lock_path.stat().st_size,
            "sha256": sha256_file(lock_path),
        },
        "boot_source": lock["launch"]["boot_source"],
        "host_output": str(host_output_path.relative_to(PROJECT_ROOT)),
        "emulator_log": lock["launch"]["log_path"],
        "pine": {
            "socket_path": str(socket_path),
            "version": pine_version,
            "game_id": game_id,
            "status": pine_status,
        },
    }
    process_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"PID: {process.pid}")
    print(f"PINE: {pine_version}; {game_id}; status={pine_status}")
    print(f"process record: {process_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
