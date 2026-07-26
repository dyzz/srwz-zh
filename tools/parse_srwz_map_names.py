#!/usr/bin/env python3
"""Extract the fixed-width MAPNAME text records from the original ISO."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from srwz.mapname import MapNameError, parse_map_names
except ModuleNotFoundError:
    from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from tools.srwz.mapname import MapNameError, parse_map_names


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = PROJECT_ROOT / "rom" / "srwz.iso"
DEFAULT_OUTPUT = PROJECT_ROOT / "work" / "parsed" / "map-names.json"
MEMBER_PATH = "MAP/MAPNAME.BIN"


def read_member(iso_path: Path) -> bytes:
    image = scan_iso9660(iso_path)
    members = member_map(image)
    if MEMBER_PATH not in members:
        raise MapNameError(f"ISO member is missing: {MEMBER_PATH}")
    member = members[MEMBER_PATH]
    with iso_path.open("rb") as source:
        source.seek(member.extent_lba * SECTOR_SIZE)
        data = source.read(member.size)
    if len(data) != member.size:
        raise MapNameError(
            f"short read for {MEMBER_PATH}: {len(data)} of {member.size}"
        )
    return data


def record_signature(records) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record.stable_id.encode("ascii"))
        digest.update(b"\0")
        digest.update(record.text.encode("shift_jis"))
        digest.update(b"\0")
    return digest.hexdigest()


def build_report(data: bytes) -> dict:
    records = parse_map_names(data)
    return {
        "schema_version": 1,
        "source": {
            "member": MEMBER_PATH,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "record_size": records[0].allocated_size,
        "record_count": len(records),
        "stable_id_count": len({record.stable_id for record in records}),
        "unique_text_count": len({record.text for record in records}),
        "max_encoded_size": max(record.encoded_size for record in records),
        "record_signature_sha256": record_signature(records),
        "records": [
            {
                "id": record.stable_id,
                "index": record.index,
                "offset": record.offset,
                "allocated_size": record.allocated_size,
                "encoded_size": record.encoded_size,
                "text": record.text,
            }
            for record in records
        ],
    }


def compact_manifest(report: dict) -> dict:
    return {
        "schema_version": report["schema_version"],
        "recorded_on": "2026-07-25",
        "scope": (
            "Read-only fixed-record parsing; Japanese text remains in ignored "
            "work output."
        ),
        "source": report["source"],
        "record_size": report["record_size"],
        "record_count": report["record_count"],
        "stable_id_count": report["stable_id_count"],
        "unique_text_count": report["unique_text_count"],
        "max_encoded_size": report["max_encoded_size"],
        "record_signature_sha256": report["record_signature_sha256"],
    }


def write_json(path: Path, value: dict, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"refusing to replace existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse the fixed-width Shift-JIS records in MAPNAME.BIN."
    )
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    if not iso_path.is_file():
        print(f"error: ISO not found: {iso_path}", file=sys.stderr)
        return 2
    try:
        report = build_report(read_member(iso_path))
        write_json(args.output.resolve(), report, args.force)
        if args.manifest_output is not None:
            write_json(
                args.manifest_output.resolve(),
                compact_manifest(report),
                args.force,
            )
    except (FileExistsError, MapNameError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"MAPNAME: {report['record_count']} records, "
        f"{report['unique_text_count']} unique texts"
    )
    print(args.output.resolve())
    if args.manifest_output is not None:
        print(args.manifest_output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
