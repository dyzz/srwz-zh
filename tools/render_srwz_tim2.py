#!/usr/bin/env python3
"""Render one validated SRWZ TIM2 record to an ignored PNG with ImageMagick."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

try:
    from srwz.assets import AssetInventoryConfig, AssetInventoryError
    from srwz.codec import decode
    from srwz.codec_contract import SrwzCodecError
    from srwz.imagemagick import (
        ImageMagickError,
        render_tim2_png8,
        require_imagemagick,
    )
    from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from srwz.iso_layout import (
        ExecutableOffsetSpec,
        IsoLayoutError,
        read_executable_archive_offsets,
    )
    from srwz.tim2 import Tim2Error, extract_tim2_record
except ModuleNotFoundError:
    from tools.srwz.assets import AssetInventoryConfig, AssetInventoryError
    from tools.srwz.codec import decode
    from tools.srwz.codec_contract import SrwzCodecError
    from tools.srwz.imagemagick import (
        ImageMagickError,
        render_tim2_png8,
        require_imagemagick,
    )
    from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from tools.srwz.iso_layout import (
        ExecutableOffsetSpec,
        IsoLayoutError,
        read_executable_archive_offsets,
    )
    from tools.srwz.tim2 import Tim2Error, extract_tim2_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_ISO = PROJECT_ROOT / "rom" / "srwz.iso"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "assets" / "archive-inventory.json"


class Tim2RenderError(ValueError):
    """The selected source/member/chunk cannot be rendered safely."""


def read_member(source, member) -> bytes:
    source.seek(member.extent_lba * SECTOR_SIZE)
    data = source.read(member.size)
    if len(data) != member.size:
        raise Tim2RenderError(f"short read for {member.path}")
    return data


def selected_payload(
    iso_path: Path,
    config_path: Path,
    member_path: str,
    chunk_index: int | None,
    source_file: Path | None,
) -> bytes:
    config = AssetInventoryConfig.from_mapping(
        json.loads(config_path.read_text(encoding="utf-8"))
    )
    image = scan_iso9660(iso_path)
    members = member_map(image)
    if member_path not in members:
        raise Tim2RenderError(f"ISO member is missing: {member_path}")
    executable_path = config.executable_member
    if executable_path not in members:
        raise Tim2RenderError(f"ISO member is missing: {executable_path}")

    with iso_path.open("rb") as source:
        executable = read_member(source, members[executable_path])
        original = read_member(source, members[member_path])
    archive = source_file.read_bytes() if source_file is not None else original
    if len(archive) != len(original):
        raise Tim2RenderError(
            f"source size {len(archive)} != original member size {len(original)}"
        )

    spec = config.archive_for_member(member_path)
    if spec is None:
        if member_path not in config.direct_members:
            raise Tim2RenderError(
                f"member is not declared in asset config: {member_path}"
            )
        if chunk_index is not None:
            raise Tim2RenderError("direct member does not accept --chunk")
        return archive
    if chunk_index is None:
        raise Tim2RenderError("archive member requires --chunk")

    layout_spec = ExecutableOffsetSpec(
        name=spec.name,
        member=member_path,
        table_start=spec.table_start,
        table_end=spec.table_end,
    )
    offsets = read_executable_archive_offsets(
        executable,
        layout_spec,
        len(archive),
    )
    if not 0 <= chunk_index < len(offsets) - 1:
        raise Tim2RenderError(
            f"chunk index {chunk_index} is outside 0..{len(offsets) - 2}"
        )
    chunk = archive[offsets[chunk_index] : offsets[chunk_index + 1]]
    if spec.storage == "raw":
        return chunk
    if spec.storage == "srwz_stream":
        return decode(chunk).output
    raise Tim2RenderError(f"unsupported storage: {spec.storage!r}")


def require_work_png(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(WORK_ROOT.resolve())
    except ValueError as error:
        raise Tim2RenderError(f"PNG output must stay under {WORK_ROOT}") from error
    if resolved.suffix.lower() != ".png":
        raise Tim2RenderError("output must have a .png suffix")
    return resolved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render one validated TIM2 record from an SRWZ member/chunk."
    )
    parser.add_argument("member", help="ISO member path")
    parser.add_argument("--chunk", type=int)
    parser.add_argument("--record", type=int, default=0)
    parser.add_argument("--source-file", type=Path)
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    config_path = args.config.resolve()
    source_file = (
        args.source_file.resolve() if args.source_file is not None else None
    )
    for path, label in ((iso_path, "ISO"), (config_path, "asset config")):
        if not path.is_file():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2
    if source_file is not None and not source_file.is_file():
        print(f"error: source file not found: {source_file}", file=sys.stderr)
        return 2
    try:
        magick = require_imagemagick()
        output = require_work_png(args.output)
        if output.exists() and not args.force:
            raise FileExistsError(f"refusing to replace existing file: {output}")
        payload = selected_payload(
            iso_path,
            config_path,
            args.member,
            args.chunk,
            source_file,
        )
        record, stored = extract_tim2_record(payload, args.record)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".tm2") as temporary:
            temporary.write(stored)
            temporary.flush()
            render_tim2_png8(
                magick,
                Path(temporary.name),
                output,
            )
    except (
        AssetInventoryError,
        FileExistsError,
        ImageMagickError,
        IsoLayoutError,
        SrwzCodecError,
        Tim2Error,
        Tim2RenderError,
        json.JSONDecodeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    picture = record.pictures[0]
    print(
        f"{output}: {len(record.pictures)} picture(s), "
        f"first {picture.width}x{picture.height} {picture.bits_per_pixel}-bpp"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
