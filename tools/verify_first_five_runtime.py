#!/usr/bin/env python3
"""Verify the first-five-stage ISO and decoded font through PCSX2/PINE."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from verify_pcsx2_font_runtime import (
    DECOMPRESSOR_CORE_ADDRESS,
    EXPECTED_CORE_WORD,
    EXPECTED_LITERAL_COPY_WORD,
    FONT_POINTER_ADDRESS,
    FONT_SIZE_ADDRESS,
    LITERAL_COPY_LOOP_ADDRESS,
    PINE_ID,
    PINE_RUNNING,
    PINE_TITLE,
    PINE_VERSION,
    PineClient,
    default_socket_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_FONT_REPORT = (
    WORK_ROOT / "build/first-five/components/font-validation.json"
)
DEFAULT_ISO_REPORT = (
    PROJECT_ROOT / "build/iso/first-five/iso-validation.json"
)
DEFAULT_ISO = (
    PROJECT_ROOT / "build/iso/first-five/srwz-first-five.iso"
)
DEFAULT_LOG = WORK_ROOT / "runtime/first-five/logs/emulog.txt"
DEFAULT_OUTPUT = (
    WORK_ROOT / "runtime/first-five/pine/font-runtime.json"
)


def project_relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_emulator_log(path: Path) -> dict[str, bool]:
    """Scan bounded markers without loading a potentially large log."""

    markers = {
        "dvd_recognized": False,
        "elf_executing": False,
        "tlb_miss": False,
    }
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            lowered = line.lower()
            if "image type  = dvd" in lowered:
                markers["dvd_recognized"] = True
            if "elf cdrom0:\\slps_258.87;1 with entry point" in lowered:
                markers["elf_executing"] = True
            if "tlb miss" in lowered:
                markers["tlb_miss"] = True
    return markers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the running game accepted the first-five-stage "
            "ISO and decoded the complete candidate font exactly."
        )
    )
    parser.add_argument("--font-report", type=Path, default=DEFAULT_FONT_REPORT)
    parser.add_argument("--iso-report", type=Path, default=DEFAULT_ISO_REPORT)
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--socket", type=Path, default=default_socket_path())
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = require_work_output(args.json_output, WORK_ROOT)
    if output.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output}")

    font_report = json.loads(args.font_report.read_text(encoding="utf-8"))
    iso_report = json.loads(args.iso_report.read_text(encoding="utf-8"))
    expected_font_size = int(font_report["font"]["decoded_size"])
    expected_font_sha256 = font_report["font"]["output_decoded_sha256"]
    expected_iso_size = int(iso_report["output_iso"]["size"])
    expected_iso_sha256 = iso_report["output_iso"]["sha256"]
    actual_iso_size = args.iso.stat().st_size
    actual_iso_sha256 = sha256_file(args.iso)
    log_markers = scan_emulator_log(args.log)

    client = PineClient(args.socket)
    version = client.read_text(PINE_VERSION)
    title = client.read_text(PINE_TITLE)
    game_id = client.read_text(PINE_ID)
    status_before = client.status()
    runtime_size = client.read32(FONT_SIZE_ADDRESS)
    runtime_pointer = client.read32(FONT_POINTER_ADDRESS)
    core_word = client.read32(DECOMPRESSOR_CORE_ADDRESS)
    literal_copy_word = client.read32(LITERAL_COPY_LOOP_ADDRESS)
    runtime_font_sha256 = client.sha256_range(
        runtime_pointer,
        runtime_size,
    )
    status_after = client.status()

    checks = {
        "iso_size": actual_iso_size == expected_iso_size,
        "iso_sha256": actual_iso_sha256 == expected_iso_sha256,
        "game_id": game_id == "SLPS-25887",
        "running_before": status_before == PINE_RUNNING,
        "running_after": status_after == PINE_RUNNING,
        "decoded_font_size": runtime_size == expected_font_size,
        "decoded_font_sha256": (
            runtime_font_sha256 == expected_font_sha256
        ),
        "decompressor_core_word": core_word == EXPECTED_CORE_WORD,
        "literal_copy_loop_word": (
            literal_copy_word == EXPECTED_LITERAL_COPY_WORD
        ),
        "dvd_recognized": log_markers["dvd_recognized"],
        "elf_executing": log_markers["elf_executing"],
        "no_tlb_miss": not log_markers["tlb_miss"],
    }
    report = {
        "schema_version": 1,
        "status": "passed" if all(checks.values()) else "failed",
        "scope": (
            "First-five candidate ISO boot and complete runtime font "
            "decompression; stage dialogue visibility is separate evidence."
        ),
        "content_policy": (
            "Runtime addresses, instruction words, sizes and hashes only; "
            "no game bytes are saved."
        ),
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
        "iso": {
            "path": project_relative(args.iso),
            "actual_size": actual_iso_size,
            "expected_size": expected_iso_size,
            "actual_sha256": actual_iso_sha256,
            "expected_sha256": expected_iso_sha256,
        },
        "game_decompressor": {
            "core_address": f"0x{DECOMPRESSOR_CORE_ADDRESS:08X}",
            "core_word": f"0x{core_word:08X}",
            "literal_copy_loop_address": (
                f"0x{LITERAL_COPY_LOOP_ADDRESS:08X}"
            ),
            "literal_copy_loop_word": f"0x{literal_copy_word:08X}",
        },
        "decoded_font": {
            "pointer_address": f"0x{FONT_POINTER_ADDRESS:08X}",
            "runtime_pointer": f"0x{runtime_pointer:08X}",
            "size_address": f"0x{FONT_SIZE_ADDRESS:08X}",
            "runtime_size": runtime_size,
            "expected_size": expected_font_size,
            "runtime_sha256": runtime_font_sha256,
            "expected_sha256": expected_font_sha256,
        },
        "log": {
            "path": project_relative(args.log),
            "sha256": sha256_file(args.log),
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
        f"{runtime_size} bytes, SHA-256 {runtime_font_sha256}"
    )
    print(f"status: {report['status']}")
    print(f"json: {output}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
