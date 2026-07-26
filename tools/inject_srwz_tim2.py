#!/usr/bin/env python3
"""Inject a PNG into one exact-size SRWZ 4-bpp TIM2 archive chunk."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

try:
    from srwz.assets import AssetInventoryConfig, AssetInventoryError
    from srwz.imagemagick import (
        ImageMagickError,
        imagemagick_version,
        read_rgba8,
        render_tim2_png8,
        require_imagemagick,
    )
    from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from srwz.iso_layout import (
        ExecutableOffsetSpec,
        IsoLayoutError,
        read_executable_archive_offsets,
    )
    from srwz.tim2_writeback import (
        CANARY_HEIGHT,
        CANARY_WIDTH,
        Tim2WritebackError,
        inject_indexed4_rgba,
    )
except ModuleNotFoundError:
    from tools.srwz.assets import AssetInventoryConfig, AssetInventoryError
    from tools.srwz.imagemagick import (
        ImageMagickError,
        imagemagick_version,
        read_rgba8,
        render_tim2_png8,
        require_imagemagick,
    )
    from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from tools.srwz.iso_layout import (
        ExecutableOffsetSpec,
        IsoLayoutError,
        read_executable_archive_offsets,
    )
    from tools.srwz.tim2_writeback import (
        CANARY_HEIGHT,
        CANARY_WIDTH,
        Tim2WritebackError,
        inject_indexed4_rgba,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
MANIFEST_ROOT = PROJECT_ROOT / "manifests"
DEFAULT_ISO = PROJECT_ROOT / "rom" / "srwz.iso"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "assets" / "archive-inventory.json"


class Tim2InjectionCliError(ValueError):
    """The requested disc asset injection is outside the fixed contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_member(source, member) -> bytes:
    source.seek(member.extent_lba * SECTOR_SIZE)
    data = source.read(member.size)
    if len(data) != member.size:
        raise Tim2InjectionCliError(f"short read for {member.path}")
    return data


def require_work_path(path: Path, label: str, suffix: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(WORK_ROOT.resolve())
    except ValueError as error:
        raise Tim2InjectionCliError(
            f"{label} must stay under {WORK_ROOT}"
        ) from error
    if resolved.suffix.lower() != suffix:
        raise Tim2InjectionCliError(
            f"{label} must have a {suffix} suffix"
        )
    return resolved


def require_manifest_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(MANIFEST_ROOT.resolve())
    except ValueError as error:
        raise Tim2InjectionCliError(
            f"manifest output must stay under {MANIFEST_ROOT}"
        ) from error
    if resolved.suffix.lower() != ".json":
        raise Tim2InjectionCliError("manifest output must have a .json suffix")
    return resolved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inject an edited PNG into one exact-size 256x256 4-bpp "
            "KVMDATA TIM2 chunk. The existing CLUT and container metadata "
            "are preserved."
        )
    )
    parser.add_argument("member", help="ISO archive member path")
    parser.add_argument("--chunk", type=int, required=True)
    parser.add_argument("--edited-png", type=Path, required=True)
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--source-file",
        type=Path,
        help="Optional same-size archive member to use instead of original bytes.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Rebuilt archive member; must stay under work/ and end in .bin.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Metadata-only JSON report under work/.",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="Optional byte-free copy of the report under manifests/.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    config_path = args.config.resolve()
    edited_png = args.edited_png.resolve()
    source_file = (
        args.source_file.resolve() if args.source_file is not None else None
    )
    for path, label in (
        (iso_path, "ISO"),
        (config_path, "asset config"),
        (edited_png, "edited PNG"),
    ):
        if not path.is_file():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2
    if source_file is not None and not source_file.is_file():
        print(f"error: source file not found: {source_file}", file=sys.stderr)
        return 2

    try:
        output = require_work_path(args.output, "archive output", ".bin")
        report_path = require_work_path(args.report, "JSON report", ".json")
        manifest_path = (
            require_manifest_path(args.manifest_output)
            if args.manifest_output is not None
            else None
        )
        distinct_paths = [output, report_path]
        if manifest_path is not None:
            distinct_paths.append(manifest_path)
        if len(set(distinct_paths)) != len(distinct_paths):
            raise Tim2InjectionCliError("output paths must be distinct")
        if source_file is not None and output == source_file:
            raise Tim2InjectionCliError(
                "refusing to overwrite the source archive in place"
            )
        existing = [path for path in distinct_paths if path.exists()]
        if existing and not args.force:
            raise FileExistsError(
                f"refusing to replace existing file: {existing[0]}"
            )

        config = AssetInventoryConfig.from_mapping(
            json.loads(config_path.read_text(encoding="utf-8"))
        )
        spec = config.archive_for_member(args.member)
        if spec is None:
            raise Tim2InjectionCliError(
                f"member is not a declared archive: {args.member}"
            )
        if spec.storage != "raw":
            raise Tim2InjectionCliError(
                f"minimal TIM2 injection requires raw storage, got {spec.storage}"
            )

        image = scan_iso9660(iso_path)
        members = member_map(image)
        required = {config.executable_member, args.member}
        missing = sorted(required - members.keys())
        if missing:
            raise Tim2InjectionCliError(f"ISO members are missing: {missing}")
        with iso_path.open("rb") as source:
            executable = read_member(
                source,
                members[config.executable_member],
            )
            original_archive = read_member(source, members[args.member])
        archive = (
            source_file.read_bytes()
            if source_file is not None
            else original_archive
        )
        if len(archive) != len(original_archive):
            raise Tim2InjectionCliError(
                f"source archive has {len(archive)} bytes, "
                f"expected {len(original_archive)}"
            )

        layout_spec = ExecutableOffsetSpec(
            name=spec.name,
            member=spec.member,
            table_start=spec.table_start,
            table_end=spec.table_end,
        )
        offsets = read_executable_archive_offsets(
            executable,
            layout_spec,
            len(archive),
        )
        if not 0 <= args.chunk < len(offsets) - 1:
            raise Tim2InjectionCliError(
                f"chunk index {args.chunk} is outside 0..{len(offsets) - 2}"
            )
        chunk_start = offsets[args.chunk]
        chunk_end = offsets[args.chunk + 1]
        chunk = archive[chunk_start:chunk_end]

        magick = require_imagemagick()
        with tempfile.TemporaryDirectory(prefix="srwz-tim2-") as temp_dir:
            temporary = Path(temp_dir)
            source_tim2 = temporary / "source.tm2"
            reference_png = temporary / "reference.png"
            output_tim2 = temporary / "output.tm2"
            output_png = temporary / "output.png"
            source_tim2.write_bytes(chunk)
            render_tim2_png8(magick, source_tim2, reference_png)
            original_rgba = read_rgba8(
                magick,
                reference_png,
                expected_width=CANARY_WIDTH,
                expected_height=CANARY_HEIGHT,
            )
            edited_rgba = read_rgba8(
                magick,
                edited_png,
                expected_width=CANARY_WIDTH,
                expected_height=CANARY_HEIGHT,
            )
            result = inject_indexed4_rgba(
                chunk,
                original_rgba,
                edited_rgba,
            )
            output_tim2.write_bytes(result.data)
            render_tim2_png8(magick, output_tim2, output_png)
            output_rgba = read_rgba8(
                magick,
                output_png,
                expected_width=CANARY_WIDTH,
                expected_height=CANARY_HEIGHT,
            )
        if output_rgba != edited_rgba:
            raise Tim2InjectionCliError(
                "ImageMagick output does not match the edited PNG after injection"
            )

        rebuilt = archive[:chunk_start] + result.data + archive[chunk_end:]
        if len(rebuilt) != len(archive):
            raise Tim2InjectionCliError("rebuilt archive size changed")
        non_target_exact = (
            rebuilt[:chunk_start] == archive[:chunk_start]
            and rebuilt[chunk_end:] == archive[chunk_end:]
        )
        if not non_target_exact:
            raise Tim2InjectionCliError("non-target archive bytes changed")

        member_ranges = [
            {
                "start": chunk_start + result.image_offset + start,
                "end": chunk_start + result.image_offset + end,
            }
            for start, end in result.changed_image_byte_ranges
        ]
        report = {
            "schema_version": 1,
            "content_policy": (
                "Hashes, sizes, counts and half-open changed ranges only. "
                "Game bytes remain in ignored work/."
            ),
            "writer_contract": (
                "Single-picture 256x256 4-bpp in-place index injection; "
                "existing TIM2 header, GS registers, CLUT, padding and "
                "archive geometry are preserved."
            ),
            "config_sha256": sha256_file(config_path),
            "runtime_acceptance": "not tested",
            "toolchain": {
                "imagemagick": imagemagick_version(magick),
            },
            "source": {
                "iso_file_name": iso_path.name,
                "member": args.member,
                "source_kind": (
                    "same_size_source_file"
                    if source_file is not None
                    else "original_iso_member"
                ),
                "member_size": len(archive),
                "member_sha256": sha256_bytes(archive),
                "chunk_index": args.chunk,
                "chunk_start": chunk_start,
                "chunk_end": chunk_end,
                "chunk_size": len(chunk),
                "chunk_sha256": sha256_bytes(chunk),
                "edited_png_file_name": edited_png.name,
                "edited_png_sha256": sha256_file(edited_png),
            },
            "injection": {
                **result.to_metadata(),
                "member_byte_ranges": member_ranges,
                "visual_rgba_exact": True,
                "chunk_size_unchanged": len(result.data) == len(chunk),
                "non_target_archive_bytes_exact": non_target_exact,
            },
            "output": {
                "file_name": output.name,
                "member_size": len(rebuilt),
                "member_sha256": sha256_bytes(rebuilt),
                "chunk_sha256": sha256_bytes(result.data),
                "archive_byte_identical": rebuilt == archive,
                "chunk_byte_identical": result.data == chunk,
            },
        }

        output.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(rebuilt)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if manifest_path is not None:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except (
        AssetInventoryError,
        FileExistsError,
        ImageMagickError,
        IsoLayoutError,
        Tim2InjectionCliError,
        Tim2WritebackError,
        json.JSONDecodeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"{output}: chunk={args.chunk}, "
        f"changed_pixels={result.changed_pixel_count}, "
        f"changed_bytes={result.changed_image_byte_count}"
    )
    print(f"report: {report_path}")
    if manifest_path is not None:
        print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
