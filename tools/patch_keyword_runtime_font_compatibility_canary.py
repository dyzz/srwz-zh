#!/usr/bin/env python3
"""Patch only the runtime font stream in the isolated keyword canary ISO.

The production font component and the canary can use different VT1 segment
offsets.  This tool therefore extracts the decoded/encoded font stream through
each image's own SLPS offset table, then writes the new stream into the
canary's existing fixed-size slot.  No executable or other ISO member changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from srwz.codec import decode_production as decode  # noqa: E402
from srwz.font import (  # noqa: E402
    CORE_ARCHIVE_SPECS,
    FONT_SEGMENT_INDEX,
    GLYPH_SIZE,
    decode_font_stream,
    glyph_offset,
)
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660  # noqa: E402
from srwz.iso_layout import read_executable_archive_offsets  # noqa: E402


DEFAULT_ISO = (
    PROJECT_ROOT
    / "build/iso/keyword-runtime-font-compatibility-canary"
    / "srwz-zh-keyword-font-compat-canary.iso"
)
DEFAULT_COMPONENT_ROOT = PROJECT_ROOT / "work/build/zh-release-font/components"
DEFAULT_RETAIL_ROOT = PROJECT_ROOT / "work/disc"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--component-root", type=Path, default=DEFAULT_COMPONENT_ROOT)
    parser.add_argument("--retail-root", type=Path, default=DEFAULT_RETAIL_ROOT)
    return parser.parse_args()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_iso_member(iso_path: Path, member_name: str) -> tuple[object, bytes]:
    member = member_map(scan_iso9660(iso_path)).get(member_name)
    if member is None:
        raise SystemExit(f"canary ISO has no {member_name}")
    with iso_path.open("rb") as source:
        source.seek(member.extent_lba * SECTOR_SIZE)
        payload = source.read(member.size)
    if len(payload) != member.size:
        raise SystemExit(f"short ISO member read: {member_name}")
    return member, payload


def font_slot(executable: bytes, vt1: bytes) -> tuple[int, int]:
    offsets = read_executable_archive_offsets(
        executable,
        CORE_ARCHIVE_SPECS["VT1.BIN"],
        len(vt1),
    )
    return tuple(offsets[FONT_SEGMENT_INDEX : FONT_SEGMENT_INDEX + 2])


def glyph_bytes(decoded: bytes, index: int) -> bytes:
    start = glyph_offset(index, data_size=len(decoded))
    return decoded[start : start + GLYPH_SIZE]


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    component_root = args.component_root.resolve()
    retail_root = args.retail_root.resolve()
    if not iso_path.is_file():
        raise SystemExit(f"canary ISO does not exist: {iso_path}")

    executable_member, target_executable = read_iso_member(
        iso_path, "SLPS_258.87"
    )
    del executable_member
    vt1_member, target_vt1 = read_iso_member(iso_path, "DATA/VT1.BIN")
    component_executable = (component_root / "SLPS_258.87").read_bytes()
    component_vt1 = (component_root / "DATA/VT1.BIN").read_bytes()
    retail_executable = (retail_root / "SLPS_258.87").read_bytes()
    retail_vt1 = (retail_root / "DATA/VT1.BIN").read_bytes()

    target_start, target_end = font_slot(target_executable, target_vt1)
    component_start, component_end = font_slot(
        component_executable, component_vt1
    )
    component_segment = decode_font_stream(
        component_vt1[component_start:component_end], decoder=decode
    )
    target_segment = decode_font_stream(
        target_vt1[target_start:target_end], decoder=decode
    )
    retail_start, retail_end = font_slot(retail_executable, retail_vt1)
    retail_segment = decode_font_stream(
        retail_vt1[retail_start:retail_end], decoder=decode
    )
    if not (
        len(component_segment.decoded)
        == len(target_segment.decoded)
        == len(retail_segment.decoded)
    ):
        raise SystemExit("font decoded-size drift")

    encoded = component_vt1[
        component_start : component_start + component_segment.consumed
    ]
    target_size = target_end - target_start
    if len(encoded) > target_size:
        raise SystemExit(
            f"component font stream exceeds canary slot: {len(encoded)} > {target_size}"
        )
    replacement = encoded + bytes(target_size - len(encoded))
    reread = decode_font_stream(replacement, decoder=decode)
    if (
        reread.decoded != component_segment.decoded
        or reread.consumed != len(encoded)
        or not reread.padding_all_zero
    ):
        raise SystemExit("canary font replacement reread failed")

    # These stock punctuation glyphs are synthesized by runtime-only paths:
    # ASCII conversion emits 0x8151/0x815D, while the keyword title renderer
    # directly wraps its payload with 0x8175/0x8176.  They must be byte-exact
    # to retail before the canary is written.
    protected_glyphs = (17, 29, 53, 54)
    for index in protected_glyphs:
        if glyph_bytes(reread.decoded, index) != glyph_bytes(
            retail_segment.decoded, index
        ):
            raise SystemExit(f"protected stock glyph {index} was not restored")

    absolute_start = vt1_member.extent_lba * SECTOR_SIZE + target_start
    before_sha256 = sha256_file(iso_path)
    changed = target_vt1[target_start:target_end] != replacement
    if changed:
        with iso_path.open("r+b") as target:
            target.seek(absolute_start)
            if target.read(target_size) != target_vt1[target_start:target_end]:
                raise SystemExit("canary font slot changed during preparation")
            target.seek(absolute_start)
            target.write(replacement)
            target.flush()
            os.fsync(target.fileno())
    after_sha256 = sha256_file(iso_path)

    _member, final_vt1 = read_iso_member(iso_path, "DATA/VT1.BIN")
    final_segment = decode_font_stream(
        final_vt1[target_start:target_end], decoder=decode
    )
    if final_segment.decoded != component_segment.decoded:
        raise SystemExit("final ISO font decoded reread failed")
    report = {
        "schema_version": 1,
        "iso": str(iso_path.relative_to(PROJECT_ROOT)),
        "member": "DATA/VT1.BIN",
        "only_iso_member_changed_by_this_tool": True,
        "changed": changed,
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "member_lba": vt1_member.extent_lba,
        "member_size": vt1_member.size,
        "target_font_slot": {
            "start": target_start,
            "end": target_end,
            "size": target_size,
        },
        "encoded_size": len(encoded),
        "headroom": target_size - len(encoded),
        "decoded_size": len(final_segment.decoded),
        "decoded_sha256": sha256_bytes(final_segment.decoded),
        "protected_retail_glyphs_exact": list(protected_glyphs),
        "round_trip_exact": True,
    }
    report_path = iso_path.with_suffix(".json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
