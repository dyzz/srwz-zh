"""Build deterministic evidence from a bounded PCSX2 boot-smoke session."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


_DVD = re.compile(r"Image type\s*=\s*DVD")
_ELF = re.compile(r"ELF .*SLPS_258\.87.* is executing\.")
_TLB = re.compile(r"TLB Miss", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    """Hash a file without loading a multi-gigabyte ISO into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_boot_log(text: str) -> dict:
    """Extract only the boot checks that the emulator log can prove."""

    lines = text.splitlines()
    tlb_lines = [line for line in lines if _TLB.search(line)]
    return {
        "dvd_recognized": _DVD.search(text) is not None,
        "elf_executing": _ELF.search(text) is not None,
        "tlb_miss_count": len(tlb_lines),
        "no_tlb_miss": not tlb_lines,
        "first_tlb_miss": tlb_lines[0] if tlb_lines else None,
    }


def build_boot_smoke_report(
    *,
    project_root: Path,
    iso_path: Path,
    pcsx2_path: Path,
    log_path: Path,
    host_output_path: Path,
    argv: list[str],
    pine_version: str,
    game_title: str,
    game_id: str,
    pine_status: int,
    duration_seconds: float,
    process_exit_code: int,
) -> dict:
    """Bind the exact ISO, PINE observations and emulator log."""

    project_root = project_root.resolve()

    def relative(path: Path) -> str:
        return str(path.resolve().relative_to(project_root))

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    log_checks = analyze_boot_log(log_text)
    checks = {
        "pcsx2_version": pine_version == "PCSX2 v2.6.3",
        "game_id": game_id == "SLPS-25887",
        "pine_running": pine_status == 0,
        "dvd_recognized": log_checks["dvd_recognized"],
        "elf_executing": log_checks["elf_executing"],
        "no_tlb_miss": log_checks["no_tlb_miss"],
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": 1,
        "status": "passed" if not failed else "failed",
        "iso": {
            "path": relative(iso_path),
            "size": iso_path.stat().st_size,
            "sha256": sha256_file(iso_path),
        },
        "emulator": {
            "path": relative(pcsx2_path),
            "sha256": sha256_file(pcsx2_path),
            "argv": argv,
            "pine_version": pine_version,
            "game_title": game_title,
            "game_id": game_id,
            "pine_status": pine_status,
            "fresh_process": True,
            "bounded_duration_seconds": duration_seconds,
            "process_exit_code_after_sigint": process_exit_code,
        },
        "log": {
            "path": relative(log_path),
            "size": log_path.stat().st_size,
            "sha256": sha256_file(log_path),
            **log_checks,
        },
        "host_output": {
            "path": relative(host_output_path),
            "size": host_output_path.stat().st_size,
            "sha256": sha256_file(host_output_path),
        },
        "checks": checks,
        "failed_checks": failed,
        "boundary": (
            "This proves fresh-process DVD recognition, ELF execution, "
            "PINE state and absence or presence of logged TLB misses. "
            "It does not prove navigation or visual acceptance."
        ),
    }


__all__ = [
    "analyze_boot_log",
    "build_boot_smoke_report",
    "sha256_file",
]
