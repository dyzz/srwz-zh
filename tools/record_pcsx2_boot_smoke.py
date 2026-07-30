#!/usr/bin/env python3
"""Launch one exact SRWZ ISO in PCSX2 and record bounded boot evidence."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.pcsx2_boot_smoke import build_boot_smoke_report
from verify_pcsx2_font_runtime import (
    PINE_ID,
    PINE_TITLE,
    PINE_VERSION,
    PineClient,
    default_socket_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_PCSX2 = (
    WORK_ROOT
    / "runtime/first-five/PCSX2.app/Contents/MacOS/PCSX2"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an exact ISO in a fresh portable PCSX2 v2.6.3 process, "
            "probe PINE, stop it after a bounded interval, and record "
            "DVD/ELF/TLB evidence."
        )
    )
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--pcsx2", type=Path, default=DEFAULT_PCSX2)
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def wait_for_socket(path: Path, process: subprocess.Popen, deadline: float) -> None:
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise RuntimeError(
                f"PCSX2 exited before PINE became ready: {process.returncode}"
            )
        time.sleep(0.05)
    raise RuntimeError(f"PINE socket did not appear: {path}")


def stop_process(process: subprocess.Popen) -> int:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                return process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                return process.wait(timeout=5)
    return int(process.returncode)


def main() -> int:
    args = parse_args()
    if args.duration < 5.0 or args.duration > 30.0:
        raise SystemExit("--duration must be between 5 and 30 seconds")
    if not args.run_id or Path(args.run_id).name != args.run_id:
        raise SystemExit("--run-id must be one safe path segment")

    iso_path = args.iso.resolve()
    pcsx2_path = args.pcsx2.resolve()
    if not iso_path.is_file():
        raise SystemExit(f"ISO not found: {iso_path}")
    if not pcsx2_path.is_file() or not os.access(pcsx2_path, os.X_OK):
        raise SystemExit(f"PCSX2 is not executable: {pcsx2_path}")

    run_root = WORK_ROOT / "runtime/iso-incremental" / args.run_id
    report_path = require_work_output(
        (run_root / "boot-smoke.json").resolve(),
        WORK_ROOT,
    )
    log_path = require_work_output(
        (run_root / "emulog.txt").resolve(),
        WORK_ROOT,
    )
    host_output_path = require_work_output(
        (run_root / "host-output.txt").resolve(),
        WORK_ROOT,
    )
    existing = [
        path
        for path in (report_path, log_path, host_output_path)
        if path.exists()
    ]
    if existing and not args.force:
        raise SystemExit(
            "outputs exist; use --force: "
            + ", ".join(str(path) for path in existing)
        )

    socket_path = default_socket_path()
    if socket_path.exists():
        raise SystemExit(
            f"PINE socket already exists; stop the other session: {socket_path}"
        )
    run_root.mkdir(parents=True, exist_ok=True)
    argv = [
        str(pcsx2_path),
        "-portable",
        "-nogui",
        "-fastboot",
        "-nofullscreen",
        "-logfile",
        str(log_path),
        str(iso_path),
    ]

    started = time.monotonic()
    with host_output_path.open("wb") as host_output:
        process = subprocess.Popen(
            argv,
            cwd=PROJECT_ROOT,
            stdout=host_output,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_socket(
                socket_path,
                process,
                started + min(args.duration, 5.0),
            )
            remaining = started + args.duration - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            client = PineClient(socket_path, timeout=5)
            pine_version = client.read_text(PINE_VERSION)
            game_title = client.read_text(PINE_TITLE)
            game_id = client.read_text(PINE_ID)
            pine_status = client.status()
        except Exception:
            stop_process(process)
            raise
        exit_code = stop_process(process)

    report = build_boot_smoke_report(
        project_root=PROJECT_ROOT,
        iso_path=iso_path,
        pcsx2_path=pcsx2_path,
        log_path=log_path,
        host_output_path=host_output_path,
        argv=[
            (
                str(Path(value).resolve().relative_to(PROJECT_ROOT))
                if value.startswith(str(PROJECT_ROOT))
                else value
            )
            for value in argv
        ],
        pine_version=pine_version,
        game_title=game_title,
        game_id=game_id,
        pine_status=pine_status,
        duration_seconds=args.duration,
        process_exit_code=exit_code,
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"boot smoke: {report['status']}")
    print(f"ISO: {report['iso']['sha256']}")
    print(f"PINE status: {report['emulator']['pine_status']}")
    print(f"TLB misses: {report['log']['tlb_miss_count']}")
    print(f"report: {report_path}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
