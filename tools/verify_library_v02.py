#!/usr/bin/env python3
"""Verify the v0.2 LIBRARY source inventory and sound-title policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from srwz.codec import decode
from srwz.iso_layout import (
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.library import (
    LibraryScopeError,
    SoundTitleSpanLock,
    verify_jtim_library_menu_record,
    verify_sound_title_source,
    verify_sound_titles_preserved,
    validate_library_scope_mapping,
)
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/library/v0.2.0.json"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise LibraryScopeError(f"path escapes project root: {value}") from exc
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LibraryScopeError("LIBRARY config root must be an object")
    validate_library_scope_mapping(value)
    return value


def verify_file_lock(path: Path, raw_lock: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise LibraryScopeError(f"missing source member: {path}")
    expected_size = int(raw_lock["size"])
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise LibraryScopeError(
            f"{path} size mismatch: expected {expected_size}, got {actual_size}"
        )
    expected_hash = str(raw_lock["sha256"])
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise LibraryScopeError(
            f"{path} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        )
    return {"size": actual_size, "sha256": actual_hash}


def decoded_compdata(path: Path) -> bytes:
    return decode(path.read_bytes()).output


def verify_zkn_archive(
    executable: bytes,
    archive_path: Path,
    raw_lock: dict[str, Any],
    member: str,
) -> dict[str, Any]:
    archive = archive_path.read_bytes()
    spec = ExecutableOffsetSpec(
        name=member,
        member=member,
        table_start=int(str(raw_lock["slps_table_start"]), 0),
        table_end=int(str(raw_lock["slps_table_end"]), 0),
    )
    offsets = read_executable_archive_offsets(
        executable, spec, len(archive)
    )
    expected_count = int(raw_lock["expected_chunk_count"])
    actual_count = len(offsets) - 1
    if actual_count != expected_count:
        raise LibraryScopeError(
            f"{member} chunk count mismatch: "
            f"expected {expected_count}, got {actual_count}"
        )

    decoded_bytes = 0
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        chunk = archive[start:end]
        result = decode(chunk)
        if any(chunk[result.consumed :]):
            raise LibraryScopeError(
                f"{member} chunk {index} has nonzero trailing bytes"
            )
        decoded_bytes += len(result.output)
    return {
        "chunk_count": actual_count,
        "all_chunks_decoded": True,
        "decoded_byte_count": decoded_bytes,
    }


def verify(
    config_path: Path,
    *,
    candidate_compdata: Path | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    raw_member_locks = config.get("source_member_locks")
    if not isinstance(raw_member_locks, dict):
        raise LibraryScopeError("source_member_locks must be an object")

    members: dict[str, dict[str, Any]] = {}
    for member, raw_lock in raw_member_locks.items():
        if not isinstance(member, str) or not isinstance(raw_lock, dict):
            raise LibraryScopeError("source member lock is malformed")
        source_path = project_path(str(raw_lock["path"]))
        members[member] = verify_file_lock(source_path, raw_lock)

    executable_lock = raw_member_locks["SLPS_258.87"]
    executable_path = project_path(str(executable_lock["path"]))
    executable = executable_path.read_bytes()
    zkn_archives: dict[str, dict[str, Any]] = {}
    for member in (
        "DATA/MTVZKNRT.BIN",
        "DATA/MTVZKNPT.BIN",
        "DATA/MTVZKNKW.BIN",
    ):
        archive_lock = raw_member_locks[member]
        archive_path = project_path(str(archive_lock["path"]))
        zkn_archives[member] = verify_zkn_archive(
            executable, archive_path, archive_lock, member
        )

    compdata_lock = raw_member_locks["DATA/COMPDATA.BN"]
    compdata_path = project_path(str(compdata_lock["path"]))
    source_decoded = decoded_compdata(compdata_path)
    expected_decoded_size = int(compdata_lock["decoded_size"])
    expected_decoded_hash = str(compdata_lock["decoded_sha256"])
    if len(source_decoded) != expected_decoded_size:
        raise LibraryScopeError("decoded COMPDATA size mismatch")
    actual_decoded_hash = hashlib.sha256(source_decoded).hexdigest()
    if actual_decoded_hash != expected_decoded_hash:
        raise LibraryScopeError("decoded COMPDATA SHA-256 mismatch")

    sound_config = config["sound_select"]
    sound_lock = SoundTitleSpanLock.from_mapping(
        sound_config["decoded_compdata"]
    )
    table = load_text_table(TEXT_TABLE)
    titles = verify_sound_title_source(source_decoded, table, sound_lock)

    jtim_lock = raw_member_locks["DATA/JTIM.BIN"]
    jtim_path = project_path(str(jtim_lock["path"]))
    menu_record = verify_jtim_library_menu_record(
        jtim_path.read_bytes(), config["library_menu_tim2"]
    )

    candidate_result: dict[str, Any] | None = None
    if candidate_compdata is not None:
        candidate = decoded_compdata(candidate_compdata)
        verify_sound_titles_preserved(source_decoded, candidate, sound_lock)
        candidate_result = {
            "path": str(candidate_compdata),
            "decoded_size": len(candidate),
            "sound_track_titles_byte_exact": True,
        }

    return {
        "schema_version": 1,
        "status": "library_v0.2_source_locks_passed",
        "release": config["release"],
        "decision": config["decision"],
        "surface_count": len(config["surfaces"]),
        "source_members": members,
        "zkn_archives": zkn_archives,
        "library_menu_tim2": menu_record,
        "sound_select": {
            "track_title_policy": sound_config["track_title_policy"],
            "title_count": len(titles),
            "decoded_start": sound_lock.start,
            "decoded_end": sound_lock.end,
            "span_sha256": sound_lock.expected_span_sha256,
            "source_lock_passed": True,
            "candidate": candidate_result,
        },
        "runtime_status": "not_tested",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--candidate-compdata", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    report = verify(
        args.config.resolve(),
        candidate_compdata=(
            None
            if args.candidate_compdata is None
            else args.candidate_compdata.resolve()
        ),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report is None:
        print(rendered, end="")
    else:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
        print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
