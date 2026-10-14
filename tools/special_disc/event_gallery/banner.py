"""Append the frozen event-gallery banner without a live rasterization step."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from srwz.tim2 import parse_tim2

ASSETS = Path(__file__).resolve().parent / "assets"


def _asset(name: str) -> bytes:
    lock = json.loads((ASSETS / "manifest.json").read_text())
    payload = (ASSETS / name).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == lock["files"][name], f"Gallery asset drift: {name}"
    return payload


def append(decoded: bytes) -> tuple[bytes, dict]:
    """Add shared-CLUT picture 5 / bank 5 to decoded SP AID block 2."""
    count, header_size = struct.unpack_from("<II", decoded)
    assert (count, header_size) == (4, 0x30), "Unexpected AID block 2 wrapper"
    ends = [struct.unpack_from("<I", decoded, 0x10 + i * 8)[0] for i in range(count)]
    starts = [0] + ends[:-1]
    start, end = header_size + starts[1], header_size + ends[1]
    native = decoded[start:end]
    tim2 = parse_tim2(native)
    assert len(tim2.pictures) == 5 and tim2.size == len(native)
    owner = tim2.pictures[0]
    assert (owner.width, owner.height, owner.image_type, owner.clut_size,
            owner.clut_color_count) == (1024, 128, 5, 5120, 1280)
    clut = _asset("event-banner-clut.bin")
    picture = _asset("event-banner-picture.bin")
    assert len(clut) == 1024 and len(picture) == 131120
    palette_end = owner.offset + owner.total_size
    new = bytearray(native[:palette_end] + clut + native[palette_end:] + picture)
    struct.pack_into("<H", new, 6, 6)
    struct.pack_into("<I", new, owner.offset, owner.total_size + 1024)
    struct.pack_into("<I", new, owner.offset + 4, owner.clut_size + 1024)
    struct.pack_into("<H", new, owner.offset + 14, owner.clut_color_count + 256)
    updated = parse_tim2(new)
    assert len(updated.pictures) == 6 and updated.size == len(new)
    for before, after in zip(tim2.pictures, updated.pictures):
        assert native[before.offset + before.header_size:before.offset + before.header_size + before.image_size] == new[after.offset + after.header_size:after.offset + after.header_size + after.image_size]
    old_palette_start = owner.offset + owner.header_size + owner.image_size
    assert native[old_palette_start:palette_end] == new[old_palette_start:palette_end]
    delta = len(new) - len(native)
    result = bytearray(decoded[:start] + new + decoded[end:])
    for i in range(1, count):
        struct.pack_into("<I", result, 0x10 + i * 8, ends[i] + delta)
    assert bytes(result[header_size:start]) == decoded[header_size:start]
    assert bytes(result[end + delta:]) == decoded[end:]
    return bytes(result), {
        "base_decoded_size": len(decoded), "decoded_size": len(result), "added_bytes": delta,
        "tim2_record": 1, "tim2_offset": start, "picture": 5, "palette_bank": 5,
        "original_5_images_byte_identical": True, "original_5_palette_banks_byte_identical": True,
        "other_records_byte_identical": True,
        "wrapper_end_updates": [{"offset": hex(0x10 + i * 8), "old": ends[i],
                                 "new": ends[i] + delta} for i in range(1, count)],
    }
