"""Frozen SP command/formation cells and native draw records, installed as a pair.

SP adds two coloured COMMAND bars (chunks 167/168). Reusing the main game's
matched records misses them and samples unrelated help cells. Formation also
needs its own cell: SP still uses the original ORM letters reclaimed by the
main game. The SUPPORT window uses one centred command title; its old texture
remains reserved because other native sprite UVs overlap it. SETUP's native
Japanese suffix crop is shifted to include the complete Chinese title.
No rasterizer is used by the production writer.
"""
from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path

from srwz.tim2 import parse_tim2

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config/assets/special-disc/command-headings.json"
KVM = "KURODATA/KVMDATA.BIN"
KVP = "KURODATA/KVPDATA.BIN"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def apply_command_headings(atlas: bytes, drawings: bytes, config=None):
    config = json.loads(CONFIG.read_text()) if config is None else config
    page = config["page"]
    require(len(atlas) == config["atlas_size"] and len(drawings) == config["drawings_size"],
            "SP command member size drift")
    chunk = atlas[page["start"]:page["end"]]
    picture = parse_tim2(chunk).pictures[0]
    require((picture.width, picture.height, picture.image_type) == (256, 256, 4),
            "SP command texture geometry drift")
    start = picture.offset + picture.header_size
    end = start + picture.image_size
    require(sha(chunk[:start] + chunk[end:]) == page["container_sha256"],
            "SP command header/CLUT/trailer drift")
    indices = bytearray(v for byte in chunk[start:end] for v in (byte & 15, byte >> 4))
    claimed = set()
    for cell in config["cells"]:
        x, y, width, height = cell["rect"]
        require(0 <= x < x + width <= 256 and 0 <= y < y + height <= 256,
                "SP command cell bounds")
        positions = [yy * 256 + xx for yy in range(y, y + height) for xx in range(x, x + width)]
        require(not claimed.intersection(positions), "SP command cell overlap")
        claimed.update(positions)
        pixels = zlib.decompress(base64.b64decode(cell["indices_zlib_base64"], validate=True))
        require(len(pixels) == width * height and max(pixels) <= 15 and sha(pixels) == cell["sha256"],
                "SP command frozen pixels drift")
        require(any(1 <= v <= 7 for v in pixels) and any(8 <= v <= 15 for v in pixels),
                "SP command index layers missing")
        before = bytes(indices[i] for i in positions)
        require(sha(before) in (cell["before_sha256"], cell["sha256"]), "SP command cell preimage drift")
        for i, value in zip(positions, pixels):
            indices[i] = value
    packed = bytes(indices[i] | indices[i + 1] << 4 for i in range(0, len(indices), 2))
    atlas_out = atlas[:page["start"] + start] + packed + atlas[page["start"] + end:]
    draw_out = bytearray(drawings)
    claimed = set()
    for patch in config["patches"]:
        offset = patch["offset"]
        native = bytes.fromhex(patch["native_hex"])
        after = bytes.fromhex(patch["after_hex"])
        require(len(native) == len(after) in (16, 34) and 0 <= offset <= len(drawings) - len(after),
                "SP command draw bounds")
        positions = set(range(offset, offset + len(after)))
        require(not claimed.intersection(positions), "SP command draw overlap")
        claimed.update(positions)
        header_ok = (native[:4] == after[:4] and native[4] & 0xf0 == after[4] & 0xf0
                     and native[5:10] == after[5:10]) if len(after) == 34 else native[:8] == after[:8]
        require(header_ok, "SP command native flags/material/colour changed")
        require(drawings[offset:offset + len(after)].hex() in
                (patch["native_hex"], patch["before_hex"], patch["after_hex"], patch.get("previous_hex")),
                f"SP command draw preimage drift at {offset:#x}")
        draw_out[offset:offset + len(after)] = after
    return atlas_out, bytes(draw_out), {
        "status": "static_verified_runtime_pending", "config_sha256": sha(CONFIG.read_bytes()),
        "cells": len(config["cells"]), "drawing_records": len(config["patches"]),
        "native_material_colours_preserved": True, "non_target_bytes_preserved": True,
        "files": {KVM: sha(atlas_out), KVP: sha(draw_out)},
    }
