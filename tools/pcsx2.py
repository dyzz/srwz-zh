#!/usr/bin/env python3
"""Prepare, launch, stop, collect, and verify isolated PCSX2 sessions."""

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import time
from pathlib import Path

from srwz.pcsx2_session import (
    Pcsx2SessionError,
    collect_pcsx2_session,
    newest_session_savestate,
    prepare_pcsx2_session,
    register_pcsx2_savestate,
    sha256_file,
    validate_pcsx2_session,
    verify_savestate_receipt,
    with_exploratory_iso,
)
from srwz.pine import (
    PINE_ID,
    PINE_VERSION,
    PineClient,
    default_socket_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_ROOT = PROJECT_ROOT / "work/runtime/pcsx2-sessions"
DEFAULT_ISO_CONFIG = (
    PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
)
DEFAULT_PCSX2_APP = Path("/Applications/PCSX2.app")
DEFAULT_SETTINGS = (
    Path.home() / "Library/Application Support/PCSX2/inis/PCSX2.ini"
)
DEFAULT_BIOS = Path.home() / "Library/Application Support/PCSX2/bios"


def build_current_case_plan(
    iso_config_path: Path,
    case_id: str,
    *,
    has_external_fixture: bool,
) -> dict:
    """Bind one runtime case directly to the current release ISO config."""

    iso_config_path = iso_config_path.resolve()
    try:
        relative_config = iso_config_path.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise Pcsx2SessionError(
            "ISO config must stay inside the project"
        ) from error
    try:
        config = json.loads(iso_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Pcsx2SessionError(
            f"cannot load ISO config {iso_config_path}: {error}"
        ) from error
    output = config.get("output")
    if not isinstance(output, dict):
        raise Pcsx2SessionError("ISO config output lock is missing")
    iso_path = PROJECT_ROOT / str(output.get("path", ""))
    expected_size = output.get("expected_size")
    expected_sha256 = output.get("expected_sha256")
    if (
        not iso_path.is_file()
        or iso_path.stat().st_size != expected_size
        or sha256_file(iso_path) != expected_sha256
    ):
        raise Pcsx2SessionError(
            "current ISO does not match the selected build config"
        )
    fixture = (
        {
            "fixture_id": "external-memory-card",
            "kind": "memory_card",
            "status": "not_acquired",
            "sha256": None,
        }
        if has_external_fixture
        else {
            "fixture_id": "fresh-boot",
            "kind": "fresh_boot",
            "status": "ready",
            "sha256": None,
        }
    )
    return {
        "artifact": {
            "artifact_id": config.get("profile_id"),
            "manifest": str(relative_config),
            "manifest_sha256": sha256_file(iso_config_path),
            "iso_path": output["path"],
            "iso_size": expected_size,
            "iso_sha256": expected_sha256,
        },
        "fixture": fixture,
        "emulator": {
            "name": "PCSX2",
            "version": "2.6.3",
            "pine_version": "PCSX2 v2.6.3",
            "architecture": "x86_64",
        },
        "case": {
            "case_id": case_id,
            "purpose": "current_release_runtime_acceptance",
            "route": [
                "Reach and record the requested current-release surface."
            ],
            "assertions": [
                "The session uses the exact ISO locked by the release config.",
                "The target surface is reached with zero TLB or illegal-instruction errors.",
            ],
        },
    }


def _command_prepare(args: argparse.Namespace) -> int:
    try:
        case_plan = build_current_case_plan(
            args.iso_config,
            args.case_id,
            has_external_fixture=(
                args.memory_card is not None
                or args.savestate_receipt is not None
            ),
        )
        if args.iso is not None:
            if not args.exploratory:
                raise Pcsx2SessionError("--iso requires --exploratory")
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
    except (OSError, Pcsx2SessionError) as error:
        raise SystemExit(str(error)) from error
    print(f"session lock: {lock_path}")
    print(f"launch plan: {launch_path}")
    print("PCSX2 was not launched")
    print(f"verify: python3 tools/pcsx2.py verify --lock {lock_path}")
    return 0


def _command_verify(args: argparse.Namespace) -> int:
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


def _stop_failed_launch(process: subprocess.Popen) -> None:
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


def _command_launch(args: argparse.Namespace) -> int:
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
    settings_baseline = PROJECT_ROOT / lock["portable"]["settings"]["path"]
    runtime_settings = PROJECT_ROOT / lock["portable"]["runtime_settings_path"]
    shutil.copy2(settings_baseline, runtime_settings)
    card_baseline = lock["portable"].get("memory_card")
    if card_baseline is not None:
        runtime_card = (
            PROJECT_ROOT / lock["portable"]["runtime_memory_card_path"]
        )
        shutil.copy2(PROJECT_ROOT / card_baseline["path"], runtime_card)
    process_path = workspace / "process.json"
    host_output_path = workspace / "logs/host-output.txt"
    if process_path.exists():
        raise SystemExit(f"process record already exists: {process_path}")
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
        _stop_failed_launch(process)
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
        last_pine_error = f"{pine_version!r}, {game_id!r}, status={pine_status}"
        time.sleep(0.1)
    else:
        _stop_failed_launch(process)
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


def _session_root(session_id: str) -> Path:
    root = (SESSIONS_ROOT / session_id).resolve()
    try:
        root.relative_to(SESSIONS_ROOT.resolve())
    except ValueError as error:
        raise Pcsx2SessionError("session_id escapes the sessions root") from error
    return root


def _command_stop(args: argparse.Namespace) -> int:
    if args.timeout < 1 or args.timeout > 60:
        raise SystemExit("--timeout must be between 1 and 60 seconds")
    session_root = _session_root(args.session_id)
    process_path = session_root / "process.json"
    try:
        record = json.loads(process_path.read_text(encoding="utf-8"))
        pid = record.get("pid") if isinstance(record, dict) else None
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise Pcsx2SessionError("process record PID is invalid")
        command = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        expected_binary = str(session_root / "PCSX2.app/Contents/MacOS/PCSX2")
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
    except (OSError, json.JSONDecodeError, Pcsx2SessionError) as error:
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


def _command_collect(args: argparse.Namespace) -> int:
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


def _command_savestate_register(args: argparse.Namespace) -> int:
    session_root = _session_root(args.session_id)
    try:
        state_path = (
            args.state.resolve()
            if args.state is not None
            else newest_session_savestate(session_root)
        )
        receipt_path = register_pcsx2_savestate(
            PROJECT_ROOT,
            session_root / "session-lock.json",
            state_path,
            state_id=args.state_id,
        )
    except (OSError, Pcsx2SessionError) as error:
        raise SystemExit(str(error)) from error
    print(f"savestate receipt: {receipt_path}")
    print("scope: acceleration_only")
    print("The state cannot replace a fresh primary runtime run")
    return 0


def _command_savestate_verify(args: argparse.Namespace) -> int:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--case-id", required=True)
    prepare.add_argument("--session-id", required=True)
    prepare.add_argument("--iso-config", type=Path, default=DEFAULT_ISO_CONFIG)
    prepare.add_argument("--pcsx2-app", type=Path, default=DEFAULT_PCSX2_APP)
    prepare.add_argument(
        "--settings-template", type=Path, default=DEFAULT_SETTINGS
    )
    prepare.add_argument("--bios-directory", type=Path, default=DEFAULT_BIOS)
    source = prepare.add_mutually_exclusive_group()
    source.add_argument("--memory-card", type=Path)
    source.add_argument("--savestate-receipt", type=Path)
    prepare.add_argument("--iso", type=Path)
    prepare.add_argument("--exploratory", action="store_true")
    prepare.set_defaults(handler=_command_prepare)

    verify = commands.add_parser("verify")
    verify.add_argument("--lock", type=Path, required=True)
    verify.add_argument("--allow-memory-card-drift", action="store_true")
    verify.set_defaults(handler=_command_verify)

    launch = commands.add_parser("launch")
    launch.add_argument("--lock", type=Path, required=True)
    launch.add_argument("--execute", action="store_true")
    launch.add_argument("--pine-timeout", type=float, default=15.0)
    launch.set_defaults(handler=_command_launch)

    stop = commands.add_parser("stop")
    stop.add_argument("--session-id", required=True)
    stop.add_argument("--timeout", type=float, default=10.0)
    stop.set_defaults(handler=_command_stop)

    collect = commands.add_parser("collect")
    collect.add_argument("--lock", type=Path, required=True)
    collect.set_defaults(handler=_command_collect)

    register = commands.add_parser("savestate-register")
    register.add_argument("--session-id", required=True)
    register.add_argument("--state-id", required=True)
    register.add_argument("--state", type=Path)
    register.set_defaults(handler=_command_savestate_register)

    state_verify = commands.add_parser("savestate-verify")
    state_verify.add_argument("--receipt", type=Path, required=True)
    state_verify.set_defaults(handler=_command_savestate_verify)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
