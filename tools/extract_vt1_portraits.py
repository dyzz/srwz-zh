#!/usr/bin/env python3
"""Read-only VT1 portrait extraction for Original, BEST and Special Disc.

Uses the repository Rust decoder and GS PSMT8 helper. No Pillow or sibling
website checkout is required. Native records and full-canvas PNGs are saved;
optional cropped previews are separate from the original texture data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from srwz.codec import decode_production
from srwz.iso9660 import member_map, scan_iso9660
from srwz.tim2_writeback import unswizzle_psmt8


@dataclass(frozen=True)
class Group:
    index: int
    table: int
    count: int
    width: int
    height: int
    trailer: int


PROFILES = {
    "original": ("SLPS_258.87", 0x2FA100, {
        "battle": Group(10, 0x30E8F0, 1742, 128, 128, 0),
        "story": Group(11, 0x310430, 2516, 512, 512, 16),
    }),
    "best": ("SLPS_732.70", 0x2FA880, {
        "battle": Group(10, 0x30F070, 1742, 128, 128, 0),
        "story": Group(11, 0x310BB0, 2516, 512, 512, 16),
    }),
    "sp": ("SLPS_259.20", 0x353790, {
        "battle": Group(12, 0x368910, 1751, 128, 128, 0),
        "story": Group(13, 0x36A470, 2531, 512, 512, 16),
    }),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_words(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    if offset < 0 or offset + count * 4 > len(data):
        raise ValueError(f"offset table outside executable: 0x{offset:X}")
    return struct.unpack_from(f"<{count}I", data, offset)


def read_inputs(args, exe_name: str) -> tuple[bytes, bytes, dict]:
    if args.iso:
        path = args.iso.resolve()
        before = path.stat()
        members = member_map(scan_iso9660(path))
        data, locations = {}, {}
        with path.open("rb") as stream:
            for name in (exe_name, "DATA/VT1.BIN"):
                if name not in members:
                    raise ValueError(f"ISO missing {name}; check --edition")
                member = members[name]
                stream.seek(member.extent_lba * 2048)
                data[name] = stream.read(member.size)
                if len(data[name]) != member.size:
                    raise ValueError(f"truncated ISO member: {name}")
                locations[name] = {"size": member.size, "lba": member.extent_lba}
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise ValueError("ISO changed while reading")
        return data[exe_name], data["DATA/VT1.BIN"], {
            "iso": str(path), "iso_members": locations,
        }
    return args.exe.read_bytes(), args.vt1.read_bytes(), {
        "executable": str(args.exe.resolve()), "vt1": str(args.vt1.resolve()),
    }


def image_data(decoded: bytes, group: Group) -> tuple[bytes, bytes, bytes]:
    required = 512 + group.width * group.height + group.trailer
    if len(decoded) != required:
        raise ValueError(f"unexpected decoded length {len(decoded)}; expected {required}")
    indexes = unswizzle_psmt8(decoded[512:512 + group.width * group.height],
                              group.width, group.height)
    colors = struct.unpack_from("<256H", decoded)
    rgb, alpha = bytearray(768), bytearray(256)
    for i in range(256):
        stored = (i & 0xE7) | ((i & 0x08) << 1) | ((i & 0x10) >> 1)
        color = colors[stored]
        rgb[i * 3:i * 3 + 3] = bytes((
            (color & 31) << 3, ((color >> 5) & 31) << 3,
            ((color >> 10) & 31) << 3,
        ))
        # Match the current game-specific TEXA/AEM interpretation, not generic
        # ARGB1555 alpha. This still needs independent in-game visual checking.
        alpha[i] = 0 if color == 0 else 255
    return indexes, bytes(rgb), bytes(alpha)


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def png(width: int, height: int, indexes: bytes, rgb: bytes, alpha: bytes) -> bytes:
    rows = b"".join(b"\0" + indexes[y * width:(y + 1) * width] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", rgb) + chunk(b"tRNS", alpha)
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def preview(indexes: bytes, group: Group, alpha: bytes):
    width, height = group.width, group.height
    left, top, right, bottom = width, height, -1, -1
    for i, color in enumerate(indexes):
        if alpha[color]:
            x, y = i % width, i // width
            left, top, right, bottom = min(left, x), min(top, y), max(right, x), max(bottom, y)
    if right < 0:
        return indexes, width, height, [0, 0, width, height]
    left, top = max(0, left - 8), max(0, top - 8)
    right, bottom = min(width, right + 9), min(height, bottom + 9)
    cropped = b"".join(indexes[y * width + left:y * width + right] for y in range(top, bottom))
    return cropped, right - left, bottom - top, [left, top, right, bottom]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=PROFILES, required=True)
    parser.add_argument("--kind", choices=("battle", "story"), required=True)
    parser.add_argument("--iso", type=Path, help="read both native members from this ISO")
    parser.add_argument("--exe", type=Path, help="already extracted native executable")
    parser.add_argument("--vt1", type=Path, help="already extracted VT1.BIN")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--record", nargs="+", type=lambda s: int(s, 0), help="record IDs; decimal or 0xHEX")
    selection.add_argument("--all", action="store_true", help="extract records 2 through N-1")
    parser.add_argument("--record-count", type=int, help="explicit count for a candidate with appended records")
    parser.add_argument("--crop-preview", action="store_true", help="also write separately cropped PNG previews")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.iso and (args.exe or args.vt1):
        parser.error("use --iso OR the pair --exe and --vt1")
    if not args.iso and not (args.exe and args.vt1):
        parser.error("supply --iso OR both --exe and --vt1")
    exe_name, outer_table, groups = PROFILES[args.edition]
    group = groups[args.kind]
    count = group.count if args.record_count is None else args.record_count
    if not 2 < count <= 65536:
        parser.error("record count must be in 3..65536")
    records = list(range(2, count)) if args.all else sorted(set(args.record))
    if any(not 2 <= i < count for i in records):
        parser.error(f"image IDs must be in 2..{count - 1}; 0 and 1 are reserved")
    executable, archive, source = read_inputs(args, exe_name)
    outer = read_words(executable, outer_table, group.index + 2)
    if outer[0] != 0 or any(a >= b for a, b in zip(outer, outer[1:])) or outer[-1] > len(archive):
        raise ValueError("invalid VT1 outer offsets")
    base, end = outer[group.index:group.index + 2]
    offsets = read_words(executable, group.table, count + 1)
    if offsets[0] != 0 or any(a >= b for a, b in zip(offsets, offsets[1:])) or offsets[-1] > end - base:
        raise ValueError("invalid member offsets; check edition and record count")
    output = args.output.resolve()
    files = [output / "manifest.json"]
    extensions = ["stored.bin", "decoded.bin", "clut.bin", "psmt8.bin", "png"]
    if args.crop_preview:
        extensions.append("preview.png")
    for record in records:
        files.extend(output / f"{args.kind}-{record:04d}.{ext}" for ext in extensions)
    if any(path.exists() for path in files):
        raise ValueError("output files already exist; use a fresh output directory")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1, "edition": args.edition, "kind": args.kind,
        "source": source, "executable_sha256": sha(executable),
        "vt1_sha256": sha(archive), "vt1_size": len(archive),
        "outer_table_file_offset": outer_table, "member_table_file_offset": group.table,
        "group_index": group.index, "group_start": base, "group_end": end,
        "record_count": count, "palette_format": "PSMCT16/CSM1",
        "pixel_format": "PSMT8/swizzled", "visual_validation": "not_verified_in_game",
        "records": [],
    }
    for record in records:
        start, stop = base + offsets[record], base + offsets[record + 1]
        stored = archive[start:stop]
        result = decode_production(stored)
        decoded = result.output
        indexes, rgb, alpha = image_data(decoded, group)
        stem = f"{args.kind}-{record:04d}"
        native_pixel_end = 512 + group.width * group.height
        payloads = {
            "stored.bin": stored, "decoded.bin": decoded,
            "clut.bin": decoded[:512], "psmt8.bin": decoded[512:native_pixel_end],
            "png": png(group.width, group.height, indexes, rgb, alpha),
        }
        box = [0, 0, group.width, group.height]
        if args.crop_preview:
            cropped, w, h, box = preview(indexes, group, alpha)
            payloads["preview.png"] = png(w, h, cropped, rgb, alpha)
        for extension, data in payloads.items():
            (output / f"{stem}.{extension}").write_bytes(data)
        tail = stored[result.consumed:]
        manifest["records"].append({
            "record_id": record, "vt1_offset": start, "stored_size": len(stored),
            "compressed_stream_size": result.consumed, "stored_tail_size": len(tail),
            "stored_tail_all_zero": not any(tail), "stored_sha256": sha(stored),
            "decoded_size": len(decoded), "decoded_sha256": sha(decoded),
            "canvas_width": group.width, "canvas_height": group.height,
            "decoded_trailer_hex": decoded[native_pixel_end:].hex(),
            "preview_crop_box": box if args.crop_preview else None,
            "files": {ext: {"path": f"{stem}.{ext}", "sha256": sha(data)}
                      for ext, data in payloads.items()},
        })
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Extracted {len(records)} portrait(s): {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Extraction failed: {error}", file=sys.stderr)
        raise SystemExit(1)
