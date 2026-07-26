#!/usr/bin/env python3
"""Export all strictly validated SRWZ TIM2 pictures, organized by source BIN."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from srwz.assets import (
        AssetInventoryConfig,
        AssetInventoryError,
        classify_stream_tail,
        raw_magic_count,
        sha256_bytes,
    )
    from srwz.codec import decode
    from srwz.codec_contract import SrwzCodecError
    from srwz.image_export import (
        ImageExportError,
        parse_seg_offsets,
        safe_member_parts,
        standalone_picture_tim2,
    )
    from srwz.imagemagick import (
        ImageMagickError,
        imagemagick_version,
        require_imagemagick,
    )
    from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from srwz.iso_layout import (
        ExecutableOffsetSpec,
        IsoLayoutError,
        read_executable_archive_offsets,
    )
    from srwz.tim2 import scan_tim2
except ModuleNotFoundError:
    from tools.srwz.assets import (
        AssetInventoryConfig,
        AssetInventoryError,
        classify_stream_tail,
        raw_magic_count,
        sha256_bytes,
    )
    from tools.srwz.codec import decode
    from tools.srwz.codec_contract import SrwzCodecError
    from tools.srwz.image_export import (
        ImageExportError,
        parse_seg_offsets,
        safe_member_parts,
        standalone_picture_tim2,
    )
    from tools.srwz.imagemagick import (
        ImageMagickError,
        imagemagick_version,
        require_imagemagick,
    )
    from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from tools.srwz.iso_layout import (
        ExecutableOffsetSpec,
        IsoLayoutError,
        read_executable_archive_offsets,
    )
    from tools.srwz.tim2 import scan_tim2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ASSET_ROOT = PROJECT_ROOT / "work" / "assets"
DEFAULT_ISO = PROJECT_ROOT / "rom" / "srwz.iso"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "assets" / "archive-inventory.json"
DEFAULT_ORIGINAL_MANIFEST = PROJECT_ROOT / "manifests" / "original-disc.json"
DEFAULT_OUTPUT = WORK_ASSET_ROOT / "images-by-bin"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SCAN_BLOCK_SIZE = 4 * 1024 * 1024


class ImageExportCliError(ValueError):
    """The requested bulk export is unsafe or internally inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(SCAN_BLOCK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def require_output_root(path: Path) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(WORK_ASSET_ROOT.resolve())
    except ValueError as error:
        raise ImageExportCliError(
            f"image export must stay under {WORK_ASSET_ROOT}"
        ) from error
    if not relative.parts:
        raise ImageExportCliError(
            "image export must use a child directory under work/assets"
        )
    return resolved


def read_member_range(source, member, start: int = 0, size: int | None = None):
    if start < 0 or start > member.size:
        raise ImageExportCliError(
            f"read start {start} is outside {member.path}"
        )
    wanted = member.size - start if size is None else size
    if wanted < 0 or start + wanted > member.size:
        raise ImageExportCliError(
            f"read range {start}+{wanted} is outside {member.path}"
        )
    source.seek(member.extent_lba * SECTOR_SIZE + start)
    data = source.read(wanted)
    if len(data) != wanted:
        raise ImageExportCliError(
            f"short read for {member.path}: {len(data)} of {wanted}"
        )
    return data


def count_member_magic(source, member) -> int:
    source.seek(member.extent_lba * SECTOR_SIZE)
    remaining = member.size
    overlap = b""
    count = 0
    while remaining:
        block = source.read(min(remaining, SCAN_BLOCK_SIZE))
        if not block:
            raise ImageExportCliError(f"short magic scan for {member.path}")
        remaining -= len(block)
        combined = overlap + block
        count += combined.count(b"TIM2")
        overlap = combined[-3:]
    return count


def validate_original_baseline(
    iso_path: Path,
    executable: bytes,
    original_manifest_path: Path,
) -> dict:
    manifest = json.loads(original_manifest_path.read_text(encoding="utf-8"))
    expected_disc = manifest["disc"]
    actual_size = iso_path.stat().st_size
    if actual_size != expected_disc["file_size"]:
        raise ImageExportCliError(
            f"ISO size {actual_size} != baseline {expected_disc['file_size']}"
        )
    expected_slps = next(
        item for item in manifest["key_files"] if item["path"] == "SLPS_258.87"
    )
    actual_slps = sha256_bytes(executable)
    if actual_slps != expected_slps["sha256"]:
        raise ImageExportCliError(
            f"SLPS SHA-256 {actual_slps} != baseline "
            f"{expected_slps['sha256']}"
        )
    return {
        "iso_file_name": iso_path.name,
        "iso_size": actual_size,
        "expected_iso_sha256": expected_disc["sha256"],
        "full_iso_hash_checked": False,
        "slps_size": len(executable),
        "slps_sha256": actual_slps,
    }


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as source:
        header = source.read(24)
    if len(header) != 24 or header[:8] != PNG_SIGNATURE:
        raise ImageExportCliError(f"renderer did not create a valid PNG: {path}")
    if header[12:16] != b"IHDR":
        raise ImageExportCliError(f"PNG has no leading IHDR chunk: {path}")
    return (
        int.from_bytes(header[16:20], "big"),
        int.from_bytes(header[20:24], "big"),
    )


def render_picture(
    magick: str,
    standalone: bytes,
    output: Path,
    width: int,
    height: int,
    force: bool,
) -> dict:
    if output.exists() and not force:
        raise FileExistsError(f"refusing to replace existing file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="srwz-render-",
        dir=output.parent,
    ) as temporary_name:
        temporary = Path(temporary_name)
        source_tim2 = temporary / "picture.tm2"
        rendered_png = temporary / "picture.png"
        source_tim2.write_bytes(standalone)
        process = subprocess.run(
            [
                magick,
                str(source_tim2),
                "-alpha",
                "on",
                f"PNG32:{rendered_png}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            message = process.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise ImageExportCliError(
                f"ImageMagick failed with exit {process.returncode}: {message}"
            )
        actual_dimensions = _png_dimensions(rendered_png)
        if actual_dimensions != (width, height):
            raise ImageExportCliError(
                f"rendered PNG is {actual_dimensions[0]}x"
                f"{actual_dimensions[1]}, expected {width}x{height}"
            )
        png_size = rendered_png.stat().st_size
        png_sha256 = sha256_file(rendered_png)
        os.replace(rendered_png, output)
    return {
        "png_size": png_size,
        "png_sha256": png_sha256,
    }


def _write_bytes(path: Path, data: bytes, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"refusing to replace existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def export_payload(
    *,
    payload: bytes,
    member: str,
    chunk_index: int | None,
    view: str,
    stored_start: int,
    output_root: Path,
    magick: str,
    executor: ThreadPoolExecutor,
    force: bool,
    picture_rows: list[dict],
) -> dict | None:
    magic_count = raw_magic_count(payload)
    if magic_count == 0:
        return None
    records = scan_tim2(payload)
    if not records:
        return None

    member_root = output_root / "by-member"
    for part in safe_member_parts(member):
        member_root /= part
    chunk_label = (
        "direct" if chunk_index is None else f"chunk-{chunk_index:04d}"
    )
    payload_root = member_root / chunk_label / view
    payload_entry = {
        "chunk_index": chunk_index,
        "stored_start": stored_start,
        "view": view,
        "payload_size": len(payload),
        "payload_sha256": sha256_bytes(payload),
        "raw_tim2_magic_count": magic_count,
        "record_count": len(records),
        "picture_count": sum(len(record.pictures) for record in records),
        "records": [],
    }

    for record_index, record in enumerate(records):
        record_name = (
            f"record-{record_index:03d}_o{record.offset:08x}"
        )
        record_root = payload_root / record_name
        exact_record = payload[record.offset : record.end]
        record_path = record_root / "record.tm2"
        _write_bytes(record_path, exact_record, force)
        record_entry = {
            "record_index": record_index,
            "record_offset": record.offset,
            "record_size": record.size,
            "record_sha256": sha256_bytes(exact_record),
            "tim2_path": _relative(record_path, output_root),
            "picture_count": len(record.pictures),
            "pictures": [],
        }
        pending = []
        for picture_index, picture in enumerate(record.pictures):
            png_path = record_root / f"picture-{picture_index:03d}.png"
            picture_entry = {
                "picture_index": picture_index,
                "width": picture.width,
                "height": picture.height,
                "bits_per_pixel": picture.bits_per_pixel,
                "image_size": picture.image_size,
                "clut_color_count": picture.clut_color_count,
                "clut_bits_per_color": picture.clut_bits_per_color,
                "uses_shared_clut": picture.uses_shared_clut,
                "mipmap_count": picture.mipmap_count,
                "png_path": _relative(png_path, output_root),
                "render_status": "pending",
            }
            try:
                standalone = standalone_picture_tim2(
                    payload,
                    record,
                    picture_index,
                )
                palette_source_index = (
                    standalone.palette_source_picture_index
                )
                picture_entry.update(
                    {
                        "standalone_shared_palette_from": (
                            palette_source_index
                            if palette_source_index != picture_index
                            else None
                        ),
                        "palette_source_picture_index": (
                            palette_source_index
                        ),
                        "palette_bank_index": (
                            standalone.palette_bank_index
                        ),
                        "palette_bank_count": (
                            standalone.palette_bank_count
                        ),
                        "palette_colors_per_bank": (
                            standalone.palette_colors_per_bank
                        ),
                    }
                )
                future = executor.submit(
                    render_picture,
                    magick,
                    standalone.data,
                    png_path,
                    picture.width,
                    picture.height,
                    force,
                )
                pending.append((future, picture_entry))
            except (ImageExportError, ValueError) as error:
                picture_entry["render_status"] = "failed"
                picture_entry["render_error"] = str(error)
            record_entry["pictures"].append(picture_entry)

        for future, picture_entry in pending:
            try:
                render_metadata = future.result()
                picture_entry.update(render_metadata)
                picture_entry["render_status"] = "rendered"
            except (
                FileExistsError,
                ImageExportCliError,
                OSError,
            ) as error:
                picture_entry["render_status"] = "failed"
                picture_entry["render_error"] = str(error)

        for picture_entry in record_entry["pictures"]:
            picture_rows.append(
                {
                    "member": member,
                    "chunk_index": (
                        "" if chunk_index is None else chunk_index
                    ),
                    "view": view,
                    "stored_start": stored_start,
                    "record_index": record_index,
                    "record_offset": record.offset,
                    "record_size": record.size,
                    "record_sha256": record_entry["record_sha256"],
                    "picture_index": picture_entry["picture_index"],
                    "width": picture_entry["width"],
                    "height": picture_entry["height"],
                    "bits_per_pixel": picture_entry["bits_per_pixel"],
                    "clut_color_count": (
                        picture_entry["clut_color_count"]
                    ),
                    "uses_shared_clut": (
                        picture_entry["uses_shared_clut"]
                    ),
                    "tim2_path": record_entry["tim2_path"],
                    "png_path": picture_entry["png_path"],
                    "render_status": picture_entry["render_status"],
                    "palette_source_picture_index": picture_entry.get(
                        "palette_source_picture_index",
                        "",
                    ),
                    "palette_bank_index": picture_entry.get(
                        "palette_bank_index",
                        "",
                    ),
                    "palette_bank_count": picture_entry.get(
                        "palette_bank_count",
                        "",
                    ),
                    "png_sha256": picture_entry.get("png_sha256", ""),
                    "render_error": picture_entry.get("render_error", ""),
                }
            )
        payload_entry["records"].append(record_entry)
    return payload_entry


def _member_totals(entry: dict) -> dict:
    payloads = entry["payloads"]
    pictures = [
        picture
        for payload in payloads
        for record in payload["records"]
        for picture in record["pictures"]
    ]
    return {
        "payload_count": len(payloads),
        "record_count": sum(item["record_count"] for item in payloads),
        "picture_count": len(pictures),
        "available_palette_bank_view_count": sum(
            max(1, item.get("palette_bank_count", 0))
            for item in pictures
        ),
        "rendered_png_count": sum(
            item["render_status"] == "rendered" for item in pictures
        ),
        "render_failure_count": sum(
            item["render_status"] == "failed" for item in pictures
        ),
    }


def _report_totals(report: dict) -> dict:
    members = report["members"]
    return {
        "iso_member_count": len(report["raw_iso_scan"]),
        "members_with_valid_tim2": sum(
            bool(item["payloads"]) for item in members
        ),
        "payload_count": sum(
            item["totals"]["payload_count"] for item in members
        ),
        "tim2_record_count": sum(
            item["totals"]["record_count"] for item in members
        ),
        "picture_count": sum(
            item["totals"]["picture_count"] for item in members
        ),
        "available_palette_bank_view_count": sum(
            item["totals"]["available_palette_bank_view_count"]
            for item in members
        ),
        "source_tm2_file_count": sum(
            item["totals"]["record_count"] for item in members
        ),
        "rendered_png_count": sum(
            item["totals"]["rendered_png_count"] for item in members
        ),
        "render_failure_count": sum(
            item["totals"]["render_failure_count"] for item in members
        ),
    }


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def checkpoint(report: dict, output_root: Path) -> None:
    report["totals"] = _report_totals(report)
    _write_json_atomic(output_root / "manifest.partial.json", report)


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "member",
        "chunk_index",
        "view",
        "stored_start",
        "record_index",
        "record_offset",
        "record_size",
        "record_sha256",
        "picture_index",
        "width",
        "height",
        "bits_per_pixel",
        "clut_color_count",
        "uses_shared_clut",
        "tim2_path",
        "png_path",
        "render_status",
        "palette_source_picture_index",
        "palette_bank_index",
        "palette_bank_count",
        "png_sha256",
        "render_error",
    ]
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _write_readme(output_root: Path, report: dict) -> None:
    totals = report["totals"]
    text = f"""# SRWZ original TIM2 image export

This directory is a read-only export from the verified original ISO.

- `by-member/`: source hierarchy organized as ISO member/BIN, chunk, storage
  view, TIM2 record, and picture.
- Every `record.tm2` is the exact validated TIM2 record from the stored or
  decompressed payload.
- Every `picture-NNN.png` is a 32-bit PNG preview. Multi-picture/shared-CLUT
  records are rendered through temporary single-picture views; those temporary
  TIM2 files are not retained.
- Indexed previews isolate one logical CLUT bank (16 colors for 4-bpp or 256
  colors for 8-bpp) before ImageMagick rendering. This prevents unrelated
  multi-CLUT banks from being mixed by the reader's CSM1 page shuffle. The
  exact `record.tm2` retains every original palette bank.
- `manifest.json`: full provenance, offsets, hashes, metadata, and failures.
- `images.csv`: one filterable row per picture.
- Run `python3 tools/build_image_dashboard.py` from the repository root to
  create a self-contained local browser at `index.html`.

Exported {totals['tim2_record_count']} strict TIM2 records containing
{totals['picture_count']} pictures from
{totals['members_with_valid_tim2']} ISO members. Rendered
{totals['rendered_png_count']} PNG files with
{totals['render_failure_count']} failures.

The retained indexed pictures expose
{totals['available_palette_bank_view_count']} possible picture/palette-bank
views. This first browseable export renders bank 0 for each picture; use the
per-picture `palette_bank_count` metadata to select additional variants later
without rescanning the ISO.

Scope boundary: all 66 ISO members were scanned for raw `TIM2` magic; configured
SLPS offset archives and every paired BTL `.SEG`/`.BIN` archive were also split
and decoded. PSS movies, the raw VT1 glyph store, and visual data in unknown
non-TIM2 formats are inventoried as coverage gaps, not represented as PNGs.
"""
    (output_root / "README.md").write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export strict TIM2 records and every contained picture from the "
            "original SRWZ ISO, grouped by source BIN/member."
        )
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
        "--jobs",
        type=int,
        default=4,
        help="Concurrent ImageMagick render processes (default: 4).",
    )
    parser.add_argument(
        "--member",
        action="append",
        default=[],
        help=(
            "Optional exact ISO member to export; repeat for a bounded run. "
            "By default every supported member is exported."
        ),
    )
    parser.add_argument(
        "--direct-read-limit-mib",
        type=int,
        default=512,
        help="Maximum raw non-archive member size to load after a magic hit.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    config_path = args.config.resolve()
    original_manifest_path = args.original_manifest.resolve()
    for path, label in (
        (iso_path, "ISO"),
        (config_path, "asset config"),
        (original_manifest_path, "original manifest"),
    ):
        if not path.is_file():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2
    if not 1 <= args.jobs <= 16:
        print("error: --jobs must be between 1 and 16", file=sys.stderr)
        return 2
    if args.direct_read_limit_mib <= 0:
        print(
            "error: --direct-read-limit-mib must be positive",
            file=sys.stderr,
        )
        return 2

    try:
        output_root = require_output_root(args.output)
        if output_root.exists() and any(output_root.iterdir()) and not args.force:
            raise FileExistsError(
                f"refusing to overlay non-empty export: {output_root}"
            )
        output_root.mkdir(parents=True, exist_ok=True)
        magick = require_imagemagick()
        config = AssetInventoryConfig.from_mapping(
            json.loads(config_path.read_text(encoding="utf-8"))
        )
        image = scan_iso9660(iso_path)
        members = member_map(image)
        missing = sorted(config.required_members - members.keys())
        if missing:
            raise ImageExportCliError(f"ISO members are missing: {missing}")
        selected_members = set(args.member)
        unknown_selected = sorted(selected_members - members.keys())
        if unknown_selected:
            raise ImageExportCliError(
                f"selected ISO members are missing: {unknown_selected}"
            )

        def member_selected(member_path: str) -> bool:
            return not selected_members or member_path in selected_members

        with iso_path.open("rb") as source:
            executable = read_member_range(
                source,
                members[config.executable_member],
            )
            baseline = validate_original_baseline(
                iso_path,
                executable,
                original_manifest_path,
            )
            raw_iso_scan = []
            print(
                f"raw TIM2 magic scan: {len(image.members)} ISO members",
                flush=True,
            )
            for member in sorted(image.members, key=lambda item: item.path):
                raw_iso_scan.append(
                    {
                        "member": member.path,
                        "size": member.size,
                        "raw_tim2_magic_count": count_member_magic(
                            source,
                            member,
                        ),
                    }
                )

            report = {
                "schema_version": 1,
                "completed": False,
                "scope": (
                    "Read-only export of every structurally valid TIM2 picture "
                    "found in raw ISO members, configured SLPS-offset archives, "
                    "and paired BTL SEG archives. No game data is modified."
                ),
                "organization": (
                    "by-member/<ISO member>/<chunk|direct>/<stored|decoded>/"
                    "record-<index>_o<offset>/record.tm2 + picture-<index>.png"
                ),
                "source": baseline,
                "toolchain": {
                    "imagemagick": imagemagick_version(magick),
                    "render_output": "PNG32 RGBA",
                    "indexed_preview_palette": (
                        "bank 0 isolated to 16 colors for 4-bpp or 256 "
                        "colors for 8-bpp; all banks retained in record.tm2"
                    ),
                    "render_jobs": args.jobs,
                },
                "config": {
                    "path": config_path.relative_to(PROJECT_ROOT).as_posix(),
                    "sha256": sha256_file(config_path),
                },
                "selection": (
                    sorted(selected_members) if selected_members else "all"
                ),
                "raw_iso_scan": raw_iso_scan,
                "members": [],
                "coverage_gaps": {
                    "pss_movies_not_exported": sorted(
                        item.path
                        for item in image.members
                        if item.path.upper().endswith(".PSS")
                    ),
                    "known_non_tim2_visual_data": [
                        "DATA/VT1.BIN segment 2 raw 4480-glyph font store",
                        "model geometry or textures not wrapped in valid TIM2",
                        "any visual format with no validated parser",
                    ],
                    "palette_variants": (
                        "PNG previews use palette bank 0. Every additional "
                        "bank is retained in the exact record.tm2 and counted "
                        "per picture, but is not expanded into another PNG."
                    ),
                },
                "totals": {},
            }
            picture_rows = []
            covered_members = set()
            raw_magic_by_member = {
                item["member"]: item["raw_tim2_magic_count"]
                for item in raw_iso_scan
            }

            with ThreadPoolExecutor(max_workers=args.jobs) as executor:
                for spec in config.archives:
                    if not member_selected(spec.member):
                        continue
                    member = members[spec.member]
                    covered_members.add(spec.member)
                    layout_spec = ExecutableOffsetSpec(
                        name=spec.name,
                        member=spec.member,
                        table_start=spec.table_start,
                        table_end=spec.table_end,
                    )
                    offsets = read_executable_archive_offsets(
                        executable,
                        layout_spec,
                        member.size,
                    )
                    entry = {
                        "member": spec.member,
                        "container_kind": "slps_offset_archive",
                        "declared_storage": spec.storage,
                        "chunk_count": len(offsets) - 1,
                        "raw_member_tim2_magic_count": (
                            raw_magic_by_member[spec.member]
                        ),
                        "decode_status_counts": {},
                        "payloads": [],
                    }
                    decode_counts = Counter()
                    print(
                        f"[SLPS] {spec.member}: {len(offsets) - 1} chunks",
                        flush=True,
                    )
                    for chunk_index, (start, end) in enumerate(
                        zip(offsets, offsets[1:])
                    ):
                        stored = read_member_range(
                            source,
                            member,
                            start,
                            end - start,
                        )
                        if spec.storage == "raw":
                            decode_counts["not_compressed"] += 1
                            payload_entry = export_payload(
                                payload=stored,
                                member=spec.member,
                                chunk_index=chunk_index,
                                view="stored",
                                stored_start=start,
                                output_root=output_root,
                                magick=magick,
                                executor=executor,
                                force=args.force,
                                picture_rows=picture_rows,
                            )
                        else:
                            try:
                                decoded = decode(stored)
                            except SrwzCodecError:
                                decode_counts["decode_error"] += 1
                                payload_entry = export_payload(
                                    payload=stored,
                                    member=spec.member,
                                    chunk_index=chunk_index,
                                    view="stored-decode-error",
                                    stored_start=start,
                                    output_root=output_root,
                                    magick=magick,
                                    executor=executor,
                                    force=args.force,
                                    picture_rows=picture_rows,
                                )
                            else:
                                tail = classify_stream_tail(
                                    stored,
                                    decoded.consumed,
                                )
                                decode_counts[tail] += 1
                                payload_entry = export_payload(
                                    payload=decoded.output,
                                    member=spec.member,
                                    chunk_index=chunk_index,
                                    view="decoded",
                                    stored_start=start,
                                    output_root=output_root,
                                    magick=magick,
                                    executor=executor,
                                    force=args.force,
                                    picture_rows=picture_rows,
                                )
                                if (
                                    payload_entry is None
                                    and raw_magic_count(stored)
                                ):
                                    payload_entry = export_payload(
                                        payload=stored,
                                        member=spec.member,
                                        chunk_index=chunk_index,
                                        view="stored-fallback",
                                        stored_start=start,
                                        output_root=output_root,
                                        magick=magick,
                                        executor=executor,
                                        force=args.force,
                                        picture_rows=picture_rows,
                                    )
                        if payload_entry is not None:
                            entry["payloads"].append(payload_entry)
                    entry["decode_status_counts"] = dict(
                        sorted(decode_counts.items())
                    )
                    entry["totals"] = _member_totals(entry)
                    report["members"].append(entry)
                    checkpoint(report, output_root)
                    print(
                        f"  -> {entry['totals']['record_count']} records, "
                        f"{entry['totals']['picture_count']} pictures",
                        flush=True,
                    )

                seg_paths = sorted(
                    path
                    for path in members
                    if path.upper().endswith(".SEG")
                    and f"{path[:-4]}.BIN" in members
                )
                for seg_path in seg_paths:
                    bin_path = f"{seg_path[:-4]}.BIN"
                    if not member_selected(bin_path):
                        continue
                    if bin_path in covered_members:
                        continue
                    covered_members.add(bin_path)
                    bin_member = members[bin_path]
                    seg_member = members[seg_path]
                    seg_data = read_member_range(source, seg_member)
                    offsets = parse_seg_offsets(seg_data, bin_member.size)
                    entry = {
                        "member": bin_path,
                        "container_kind": "seg_archive",
                        "index_member": seg_path,
                        "declared_storage": "auto_decode_then_raw_fallback",
                        "chunk_count": len(offsets) - 1,
                        "raw_member_tim2_magic_count": (
                            raw_magic_by_member[bin_path]
                        ),
                        "decode_status_counts": {},
                        "payloads": [],
                    }
                    decode_counts = Counter()
                    print(
                        f"[SEG] {bin_path}: {len(offsets) - 1} chunks",
                        flush=True,
                    )
                    for chunk_index, (start, end) in enumerate(
                        zip(offsets, offsets[1:])
                    ):
                        if chunk_index and chunk_index % 100 == 0:
                            print(
                                f"  {bin_path}: {chunk_index}/"
                                f"{len(offsets) - 1}",
                                flush=True,
                            )
                        stored = read_member_range(
                            source,
                            bin_member,
                            start,
                            end - start,
                        )
                        try:
                            decoded = decode(stored)
                        except SrwzCodecError:
                            decode_counts["decode_error"] += 1
                            payload_entry = export_payload(
                                payload=stored,
                                member=bin_path,
                                chunk_index=chunk_index,
                                view="stored",
                                stored_start=start,
                                output_root=output_root,
                                magick=magick,
                                executor=executor,
                                force=args.force,
                                picture_rows=picture_rows,
                            )
                        else:
                            tail = classify_stream_tail(
                                stored,
                                decoded.consumed,
                            )
                            decode_counts[tail] += 1
                            payload_entry = export_payload(
                                payload=decoded.output,
                                member=bin_path,
                                chunk_index=chunk_index,
                                view="decoded",
                                stored_start=start,
                                output_root=output_root,
                                magick=magick,
                                executor=executor,
                                force=args.force,
                                picture_rows=picture_rows,
                            )
                            if (
                                payload_entry is None
                                and raw_magic_count(stored)
                            ):
                                payload_entry = export_payload(
                                    payload=stored,
                                    member=bin_path,
                                    chunk_index=chunk_index,
                                    view="stored-fallback",
                                    stored_start=start,
                                    output_root=output_root,
                                    magick=magick,
                                    executor=executor,
                                    force=args.force,
                                    picture_rows=picture_rows,
                                )
                        if payload_entry is not None:
                            entry["payloads"].append(payload_entry)
                    entry["decode_status_counts"] = dict(
                        sorted(decode_counts.items())
                    )
                    entry["totals"] = _member_totals(entry)
                    report["members"].append(entry)
                    checkpoint(report, output_root)
                    print(
                        f"  -> {entry['totals']['record_count']} records, "
                        f"{entry['totals']['picture_count']} pictures",
                        flush=True,
                    )

                direct_limit = args.direct_read_limit_mib * 1024 * 1024
                for member in sorted(
                    image.members,
                    key=lambda item: item.path,
                ):
                    if (
                        not member_selected(member.path)
                        or
                        member.path in covered_members
                        or raw_magic_by_member[member.path] == 0
                    ):
                        continue
                    entry = {
                        "member": member.path,
                        "container_kind": "direct_iso_member",
                        "declared_storage": "stored",
                        "chunk_count": 1,
                        "raw_member_tim2_magic_count": (
                            raw_magic_by_member[member.path]
                        ),
                        "decode_status_counts": {"not_compressed": 1},
                        "payloads": [],
                    }
                    print(
                        f"[RAW] {member.path}: "
                        f"{raw_magic_by_member[member.path]} magic",
                        flush=True,
                    )
                    if member.size > direct_limit:
                        entry["strict_scan_status"] = (
                            "skipped_over_direct_read_limit"
                        )
                        entry["strict_scan_limit"] = direct_limit
                    else:
                        stored = read_member_range(source, member)
                        payload_entry = export_payload(
                            payload=stored,
                            member=member.path,
                            chunk_index=None,
                            view="stored",
                            stored_start=0,
                            output_root=output_root,
                            magick=magick,
                            executor=executor,
                            force=args.force,
                            picture_rows=picture_rows,
                        )
                        if payload_entry is not None:
                            entry["payloads"].append(payload_entry)
                        entry["strict_scan_status"] = "complete"
                    entry["totals"] = _member_totals(entry)
                    report["members"].append(entry)
                    checkpoint(report, output_root)
                    print(
                        f"  -> {entry['totals']['record_count']} records, "
                        f"{entry['totals']['picture_count']} pictures",
                        flush=True,
                    )

            report["members"].sort(key=lambda item: item["member"])
            report["totals"] = _report_totals(report)
            report["completed"] = True
            report["completion_status"] = (
                "complete"
                if report["totals"]["render_failure_count"] == 0
                else "complete_with_render_failures"
            )
            partial_path = output_root / "manifest.partial.json"
            _write_json_atomic(partial_path, report)
            os.replace(partial_path, output_root / "manifest.json")
            _write_csv(output_root / "images.csv", picture_rows)
            _write_readme(output_root, report)
    except (
        AssetInventoryError,
        FileExistsError,
        ImageExportCliError,
        ImageExportError,
        ImageMagickError,
        IsoLayoutError,
        OSError,
        json.JSONDecodeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    totals = report["totals"]
    print(
        f"TIM2 export complete: {totals['tim2_record_count']} records, "
        f"{totals['picture_count']} pictures, "
        f"{totals['rendered_png_count']} PNGs, "
        f"{totals['render_failure_count']} failures",
        flush=True,
    )
    print(output_root, flush=True)
    return 0 if totals["render_failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
