"""Frozen indexed headings and their exact KVPDATA drawing references.

The English UI reuses individual letters from whole atlas words. Keep those
words intact; Chinese cells occupy the old FORMATION rectangle, the blank
margins of the already localized COMMAND MENU rectangle, the OTHERS/COMMAND
letters no other heading samples (page 4) and the SORT / "ORM" letters left
unreferenced after the titles moved (page 2). Every cell is rendered at its
on-screen size and drawn 1:1. Both the texture and the drawing references
must be installed together.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path

from .iso9660 import member_map, scan_iso9660
from .tim2 import parse_tim2


class UiHeadingError(ValueError):
    """A heading input or its bounded writeback contract has drifted."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lock(data: bytes) -> dict:
    return {"size": len(data), "sha256": sha(data)}


def checked(data: bytes, reference: dict, label: str) -> bytes:
    if any(reference.get(k) != v for k, v in lock(data).items()):
        raise UiHeadingError(f"{label} size or SHA-256 drift")
    return data


def _path(root: Path, raw: str) -> Path:
    path = (root / raw).resolve()
    if not path.is_relative_to(root.resolve()):
        raise UiHeadingError(f"heading path escapes project: {raw}")
    return path


def apply_draw_patches(source: bytes, patches: list[dict]) -> bytes:
    result = bytearray(source)
    claimed: set[int] = set()
    for patch in patches:
        offset = patch["offset"]
        before = bytes.fromhex(patch["before_hex"])
        after = bytes.fromhex(patch["after_hex"])
        if len(before) != 34 or len(after) != 34 or not 0 <= offset <= len(source) - 34:
            raise UiHeadingError("heading polygon must remain exactly 34 bytes")
        if source[offset:offset + 34] != before:
            raise UiHeadingError(f"heading polygon preimage drift at {offset:#x}")
        positions = set(range(offset, offset + 34))
        if positions & claimed:
            raise UiHeadingError("heading polygon ownership overlaps")
        claimed.update(positions)
        # Polygon topology, termination flag, material and color are immutable.
        # Only the texture page nibble, vertices and UV rectangle can change.
        if before[:4] != after[:4] or before[4] & 0xF0 != after[4] & 0xF0 or before[5:10] != after[5:10]:
            raise UiHeadingError("heading polygon flags or color changed")
        if before[0] & 15 != 7:
            raise UiHeadingError("heading patch is not a textured polygon")
        result[offset:offset + 34] = after
    return bytes(result)


def _apply_page_cells(archive: bytes, chunk: dict, cells: list[tuple[dict, dict]]) -> bytes:
    start, end = chunk["start"], chunk["end"]
    source = checked(archive[start:end], chunk, f"heading base texture page {chunk['index']}")
    picture = parse_tim2(source).pictures[0]
    if (picture.width, picture.height, picture.image_type) != (256, 256, 4):
        raise UiHeadingError("heading atlas geometry changed")
    image_start = picture.offset + picture.header_size
    image_end = image_start + picture.image_size
    # KVMDATA is linear low-nibble-first 4-bpp (unlike swizzled TRICMN).
    indices = bytes(v for byte in source[image_start:image_end] for v in (byte & 15, byte >> 4))
    output = bytearray(indices)
    claimed: set[int] = set()
    for spec, frozen in cells:
        x, y, width, height = spec["rect"]
        if not (0 <= x < x + width <= 256 and 0 <= y < y + height <= 256):
            raise UiHeadingError("heading cell is outside the atlas")
        positions = [yy * 256 + xx for yy in range(y, y + height) for xx in range(x, x + width)]
        if claimed.intersection(positions):
            raise UiHeadingError("heading cell ownership overlaps")
        claimed.update(positions)
        before = bytes(indices[i] for i in positions)
        if sha(before) != spec["source_indices_sha256"] or frozen["id"] != spec["id"]:
            raise UiHeadingError("heading cell identity or preimage drift")
        try:
            pixels = zlib.decompress(base64.b64decode(frozen["indices"]["zlib_base64"], validate=True))
        except (ValueError, zlib.error) as error:
            raise UiHeadingError("invalid frozen heading cell") from error
        checked(pixels, frozen["indices"], "frozen heading cell")
        if len(pixels) != width * height or any(v > 15 for v in pixels):
            raise UiHeadingError("invalid heading index data")
        if not any(1 <= v <= 7 for v in pixels) or not any(8 <= v <= 15 for v in pixels):
            raise UiHeadingError("heading fill or outline layer is missing")
        for i, value in zip(positions, pixels):
            output[i] = value
    packed = bytes(output[i] | output[i + 1] << 4 for i in range(0, len(output), 2))
    if bytes(v for byte in packed for v in (byte & 15, byte >> 4)) != output:
        raise UiHeadingError("heading index round-trip failed")
    result = bytearray(archive)
    result[start + image_start:start + image_end] = packed
    # CLUT banks, headers, archive allocations and all non-cell indices survive.
    assert result[:start + image_start] == archive[:start + image_start]
    assert result[start + image_end:] == archive[start + image_end:]
    assert all(output[i] == indices[i] for i in range(65536) if i not in claimed)
    return bytes(result)


def apply_index_cells(archive: bytes, config: dict, snapshot: dict) -> bytes:
    """Write every frozen cell into its own KVMDATA texture page.

    Pages 2 and 4 share the grayscale CLUT bank the heading polygons sample,
    and pages 0-9 are loaded as one resident group; each cell names its page.
    """

    chunks = config["texture_chunks"]
    pages = {chunk["index"]: chunk for chunk in chunks}
    if len(pages) != len(chunks) or not pages:
        raise UiHeadingError("heading texture pages must be unique")
    spans = sorted((chunk["start"], chunk["end"]) for chunk in chunks)
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise UiHeadingError("heading texture pages overlap")
    if len(snapshot["cells"]) != len(config["cells"]):
        raise UiHeadingError("heading cell count drift")
    by_page: dict[int, list[tuple[dict, dict]]] = {index: [] for index in pages}
    for spec, frozen in zip(config["cells"], snapshot["cells"]):
        page = spec.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or page not in by_page:
            raise UiHeadingError(f"heading cell {spec.get('id')!r} names an unregistered page")
        by_page[page].append((spec, frozen))
    result = archive
    for index in sorted(pages):
        if by_page[index]:
            result = _apply_page_cells(result, pages[index], by_page[index])
    return result


def build_ui_headings(root: Path, config_path: Path) -> tuple[dict[str, bytes], dict]:
    config_data = config_path.read_bytes()
    config = json.loads(config_data)
    inputs = {"config": {"path": str(config_path.relative_to(root)), **lock(config_data)}}
    values = {}
    for key in ("base_atlas", "corpus", "snapshot"):
        reference = config[key]
        values[key] = checked(_path(root, reference["path"]).read_bytes(), reference, key)
        inputs[key] = reference
    corpus = json.loads(values["corpus"])
    snapshot = json.loads(values["snapshot"])
    if snapshot["corpus_sha256"] != sha(values["corpus"]) or snapshot["cell_contract_sha256"] != sha(json.dumps(config["cells"], sort_keys=True, ensure_ascii=False).encode()):
        raise UiHeadingError("heading snapshot provenance drift")
    if snapshot["translations"] != {entry["id"]: entry["translation"] for entry in corpus["entries"]}:
        raise UiHeadingError("heading translation snapshot drift")
    iso = _path(root, config["source_iso"])
    member = config["source_drawings"]["member"]
    record = member_map(scan_iso9660(iso))[member]
    with iso.open("rb") as source:
        source.seek(record.extent_lba * 2048)
        drawings = checked(source.read(record.size), config["source_drawings"], "original KVPDATA")
    outputs = {
        "KURODATA/KVMDATA.BIN": apply_index_cells(values["base_atlas"], config, snapshot),
        member: apply_draw_patches(drawings, config["draw_patches"]),
    }
    for name, payload in outputs.items():
        checked(payload, config["expected_outputs"][name], name)
    report = {
        "schema_version": 1,
        "profile_id": config["profile_id"],
        "status": "static_component_validated_runtime_pending",
        "inputs": inputs,
        "source_drawings": config["source_drawings"],
        "heading_count": len(corpus["entries"]),
        "cell_count": len(config["cells"]),
        "drawing_patch_count": len(config["draw_patches"]),
        "outputs": {name: {"path": f"{config['output_root']}/{name}", **lock(payload)} for name, payload in outputs.items()},
        "acceptance": {
            "locked_translation_and_index_snapshot": True,
            "non_target_indices_exact": True,
            "headers_clut_and_trailing_bytes_exact": True,
            "polygon_preimages_and_non_target_bytes_exact": True,
            "polygon_topology_material_color_and_termination_preserved": True,
            "member_sizes_preserved": True,
            "indexed_round_trip_exact": True,
        },
        "runtime": {"status": "not_tested"},
    }
    return outputs, report
