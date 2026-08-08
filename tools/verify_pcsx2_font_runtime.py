#!/usr/bin/env python3
"""Verify the current release font in a running PCSX2 process."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.archive import sha256_file
from srwz.diagnostics import require_work_output
from srwz.pine import (
    PINE_ID,
    PINE_RUNNING,
    PINE_TITLE,
    PINE_VERSION,
    PineClient,
    default_socket_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests/zh-release-font-validation.json"
DEFAULT_OUTPUT = (
    WORK_ROOT / "runtime/zh-release/font-runtime-validation.json"
)

FONT_SIZE_ADDRESS = 0x003F7D68
FONT_POINTER_ADDRESS = 0x0046E3A8
DECOMPRESSOR_CORE_ADDRESS = 0x001C6D70
LITERAL_COPY_LOOP_ADDRESS = 0x001C6DE8
EXPECTED_CORE_WORD = 0x00C51821
EXPECTED_LITERAL_COPY_WORD = 0x90870000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read the complete decoded font from a running PCSX2 instance "
            "and compare it with the current release manifest."
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--socket", type=Path, default=default_socket_path())
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def project_path(reference: str) -> Path:
    path = (PROJECT_ROOT / reference).resolve()
    path.relative_to(PROJECT_ROOT)
    return path


def main() -> int:
    args = parse_args()
    output = require_work_output(args.json_output, WORK_ROOT)
    if output.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output}")

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    component = manifest["font_component"]
    report_lock = component["report"]
    report_path = project_path(report_lock["path"])
    if (
        report_path.stat().st_size != report_lock["size"]
        or sha256_file(report_path) != report_lock["sha256"]
    ):
        raise SystemExit("release font component report drift")
    component_report = json.loads(report_path.read_text(encoding="utf-8"))
    expected_size = component_report["font"]["decoded_size"]
    expected_sha256 = component["decoded_font_sha256"]
    if component_report["font"]["output_decoded_sha256"] != expected_sha256:
        raise SystemExit("release font decoded hash binding drift")

    client = PineClient(args.socket)
    version = client.read_text(PINE_VERSION)
    title = client.read_text(PINE_TITLE)
    game_id = client.read_text(PINE_ID)
    status_before = client.status()
    runtime_size = client.read32(FONT_SIZE_ADDRESS)
    runtime_pointer = client.read32(FONT_POINTER_ADDRESS)
    core_word = client.read32(DECOMPRESSOR_CORE_ADDRESS)
    literal_copy_word = client.read32(LITERAL_COPY_LOOP_ADDRESS)
    runtime_sha256 = client.sha256_range(runtime_pointer, runtime_size)
    status_after = client.status()

    checks = {
        "game_id": game_id == "SLPS-25887",
        "running_before": status_before == PINE_RUNNING,
        "running_after": status_after == PINE_RUNNING,
        "decoded_size": runtime_size == expected_size,
        "decoded_sha256": runtime_sha256 == expected_sha256,
        "decompressor_core_word": core_word == EXPECTED_CORE_WORD,
        "literal_copy_loop_word": literal_copy_word == EXPECTED_LITERAL_COPY_WORD,
    }
    report = {
        "schema_version": 1,
        "status": "passed" if all(checks.values()) else "failed",
        "content_policy": (
            "Runtime addresses, instruction words, sizes and hashes only; "
            "no game bytes are saved."
        ),
        "release_manifest": {
            "path": str(manifest_path.relative_to(PROJECT_ROOT)),
            "size": manifest_path.stat().st_size,
            "sha256": sha256_file(manifest_path),
        },
        "transport": {
            "protocol": "PCSX2 PINE IPC",
            "socket": str(args.socket),
        },
        "emulator": {
            "version": version,
            "title": title,
            "game_id": game_id,
            "status_before": status_before,
            "status_after": status_after,
        },
        "game_decompressor": {
            "core_address": f"0x{DECOMPRESSOR_CORE_ADDRESS:08X}",
            "core_word": f"0x{core_word:08X}",
            "literal_copy_loop_address": f"0x{LITERAL_COPY_LOOP_ADDRESS:08X}",
            "literal_copy_loop_word": f"0x{literal_copy_word:08X}",
        },
        "decoded_font": {
            "pointer_address": f"0x{FONT_POINTER_ADDRESS:08X}",
            "runtime_pointer": f"0x{runtime_pointer:08X}",
            "size_address": f"0x{FONT_SIZE_ADDRESS:08X}",
            "runtime_size": runtime_size,
            "runtime_sha256": runtime_sha256,
            "expected_size": expected_size,
            "expected_sha256": expected_sha256,
        },
        "checks": checks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"PCSX2: {version}; {title}; {game_id}")
    print(
        f"decoded font: 0x{runtime_pointer:08X}, "
        f"{runtime_size} bytes, SHA-256 {runtime_sha256}"
    )
    print(f"status: {report['status']}")
    print(f"json: {output}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
