#!/usr/bin/env python3
"""Inventory structurally valid TIM2 textures in the original SRWZ ISO."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from srwz.assets import (
        AssetInventoryConfig,
        AssetInventoryError,
        compact_asset_manifest,
        compare_kvm_reference,
        inventory_archive,
        raw_magic_count,
        sha256_bytes,
        summarize_records,
    )
    from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from srwz.iso_layout import IsoLayoutError
    from srwz.tim2 import scan_tim2
except ModuleNotFoundError:
    from tools.srwz.assets import (
        AssetInventoryConfig,
        AssetInventoryError,
        compact_asset_manifest,
        compare_kvm_reference,
        inventory_archive,
        raw_magic_count,
        sha256_bytes,
        summarize_records,
    )
    from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from tools.srwz.iso_layout import IsoLayoutError
    from tools.srwz.tim2 import scan_tim2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = PROJECT_ROOT / "rom" / "srwz.iso"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "assets" / "archive-inventory.json"
DEFAULT_ORIGINAL_MANIFEST = PROJECT_ROOT / "manifests" / "original-disc.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "work" / "assets" / "asset-inventory.json"


def read_iso_member(source, member) -> bytes:
    source.seek(member.extent_lba * SECTOR_SIZE)
    data = source.read(member.size)
    if len(data) != member.size:
        raise AssetInventoryError(
            f"short read for {member.path}: {len(data)} of {member.size}"
        )
    return data


def validate_original_baseline(
    iso_path: Path,
    iso_size: int,
    executable: bytes,
    original_manifest_path: Path,
) -> dict:
    manifest = json.loads(original_manifest_path.read_text(encoding="utf-8"))
    expected_disc = manifest["disc"]
    if iso_size != expected_disc["file_size"]:
        raise AssetInventoryError(
            f"ISO size {iso_size} != baseline {expected_disc['file_size']}"
        )
    expected_slps = next(
        item for item in manifest["key_files"] if item["path"] == "SLPS_258.87"
    )
    actual_slps = sha256_bytes(executable)
    if actual_slps != expected_slps["sha256"]:
        raise AssetInventoryError(
            f"SLPS SHA-256 {actual_slps} != baseline {expected_slps['sha256']}"
        )
    return {
        "iso_file_name": iso_path.name,
        "iso_size": iso_size,
        "expected_iso_sha256": expected_disc["sha256"],
        "full_iso_hash_checked": False,
        "slps_size": len(executable),
        "slps_sha256": actual_slps,
    }


def build_inventory(
    iso_path: Path,
    config_path: Path,
    original_manifest_path: Path,
    reference_kvm: Path | None,
) -> dict:
    config = AssetInventoryConfig.from_mapping(
        json.loads(config_path.read_text(encoding="utf-8"))
    )
    image = scan_iso9660(iso_path)
    members = member_map(image)
    missing = sorted(config.required_members - members.keys())
    if missing:
        raise AssetInventoryError(f"ISO members are missing: {missing}")

    archives = []
    direct_members = []
    kvm_original = None
    with iso_path.open("rb") as source:
        executable = read_iso_member(source, members[config.executable_member])
        baseline = validate_original_baseline(
            iso_path,
            iso_path.stat().st_size,
            executable,
            original_manifest_path,
        )

        for spec in config.archives:
            archive = read_iso_member(source, members[spec.member])
            entry = inventory_archive(executable, archive, spec)
            archives.append(entry)
            if spec.member == "KURODATA/KVMDATA.BIN":
                kvm_original = archive

        for member_path in config.direct_members:
            data = read_iso_member(source, members[member_path])
            direct_members.append(
                {
                    "member": member_path,
                    "size": len(data),
                    "sha256": sha256_bytes(data),
                    "raw_tim2_magic_count": raw_magic_count(data),
                    **summarize_records(scan_tim2(data)),
                }
            )

    reference_comparison = None
    if reference_kvm is not None:
        if kvm_original is None:
            raise AssetInventoryError("KVMDATA is not present in archive config")
        kvm_entry = next(
            entry
            for entry in archives
            if entry["member"] == "KURODATA/KVMDATA.BIN"
        )
        reference_comparison = compare_kvm_reference(
            kvm_original,
            kvm_entry,
            reference_kvm.read_bytes(),
        )

    total_records = sum(item["tim2_record_count"] for item in archives)
    total_records += sum(item["tim2_record_count"] for item in direct_members)
    total_pictures = sum(item["picture_count"] for item in archives)
    total_pictures += sum(item["picture_count"] for item in direct_members)

    return {
        "schema_version": 1,
        "scope": (
            "Read-only strict TIM2 metadata inventory. No pixel decode, "
            "translation, texture writer, or ISO modification."
        ),
        "source": baseline,
        "config_sha256": sha256_bytes(config_path.read_bytes()),
        "archive_count": len(archives),
        "direct_member_count": len(direct_members),
        "totals": {
            "tim2_record_count": total_records,
            "picture_count": total_pictures,
            "raw_tim2_magic_count": (
                sum(item["raw_tim2_magic_count"] for item in archives)
                + sum(
                    item["raw_tim2_magic_count"] for item in direct_members
                )
            ),
        },
        "archives": archives,
        "direct_members": direct_members,
        "reference_kvm_comparison": reference_comparison,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory valid TIM2 textures in the original SRWZ ISO."
    )
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--original-manifest",
        type=Path,
        default=DEFAULT_ORIGINAL_MANIFEST,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="Optional compact metadata-only manifest path.",
    )
    parser.add_argument(
        "--reference-kvm",
        type=Path,
        help="Optional same-size translated KVMDATA for chunk-level comparison.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def write_json(path: Path, value: dict, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"refusing to replace existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    config_path = args.config.resolve()
    original_manifest_path = args.original_manifest.resolve()
    reference_kvm = (
        args.reference_kvm.resolve() if args.reference_kvm is not None else None
    )
    for path, label in (
        (iso_path, "ISO"),
        (config_path, "asset config"),
        (original_manifest_path, "original manifest"),
    ):
        if not path.is_file():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2
    if reference_kvm is not None and not reference_kvm.is_file():
        print(f"error: reference KVMDATA not found: {reference_kvm}", file=sys.stderr)
        return 2

    try:
        report = build_inventory(
            iso_path,
            config_path,
            original_manifest_path,
            reference_kvm,
        )
        write_json(args.output.resolve(), report, args.force)
        if args.manifest_output is not None:
            write_json(
                args.manifest_output.resolve(),
                compact_asset_manifest(report, "2026-07-25"),
                args.force,
            )
    except (
        AssetInventoryError,
        FileExistsError,
        IsoLayoutError,
        json.JSONDecodeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"TIM2 inventory: {report['totals']['tim2_record_count']} records, "
        f"{report['totals']['picture_count']} pictures"
    )
    print(args.output.resolve())
    if args.manifest_output is not None:
        print(args.manifest_output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
