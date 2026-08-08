#!/usr/bin/env python3
"""Prepare one isolated, hash-locked PCSX2 runtime session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.pcsx2_session import (
    Pcsx2SessionError,
    prepare_pcsx2_session,
    sha256_file,
    with_exploratory_iso,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO_CONFIG = (
    PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
)
DEFAULT_PCSX2_APP = Path("/Applications/PCSX2.app")
DEFAULT_SETTINGS = (
    Path.home()
    / "Library/Application Support/PCSX2/inis/PCSX2.ini"
)
DEFAULT_BIOS = (
    Path.home() / "Library/Application Support/PCSX2/bios"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clone a portable PCSX2 root under work/, bind the current exact "
            "ISO and optionally copy an isolated memory card or a verified "
            "savestate bundle. The emulator is not launched."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument(
        "--iso-config",
        type=Path,
        default=DEFAULT_ISO_CONFIG,
    )
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
            "route": ["Reach and record the requested current-release surface."],
            "assertions": [
                "The session uses the exact ISO locked by the release config.",
                "The target surface is reached with zero TLB or illegal-instruction errors.",
            ],
        },
    }


def main() -> int:
    args = parse_args()
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
    except (OSError, Pcsx2SessionError) as error:
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
