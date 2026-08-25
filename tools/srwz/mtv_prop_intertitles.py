"""Fail-closed localization for the two baked MTV_PROP chapter intertitles."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Mapping

from .codec import decode_production, reencode_changed_suffix
from .imagemagick import (
    imagemagick_version,
    render_grayscale_text_mask,
    require_imagemagick,
)
from .tim2 import scan_tim2


class MtvPropIntertitleError(ValueError):
    """The source archive or frozen render contract drifted."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_sha256(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _source_bbox(indexes: bytes, width: int) -> list[int]:
    nonzero = [offset for offset, value in enumerate(indexes) if value]
    if not nonzero:
        raise MtvPropIntertitleError("intertitle source image is blank")
    xs = [offset % width for offset in nonzero]
    ys = [offset // width for offset in nonzero]
    return [min(xs), min(ys), max(xs), max(ys)]


def _chunk_inventory(source: bytes, offsets: tuple[int, ...]):
    inventory = []
    decoded_chunks = {}
    for chunk_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        chunk = source[start:end]
        decoded = decode_production(chunk)
        if any(chunk[decoded.consumed :]):
            raise MtvPropIntertitleError(
                f"MTV_PROP chunk {chunk_index} has nonzero compressed tail"
            )
        records = scan_tim2(decoded.output)
        item = {
            "chunk_index": chunk_index,
            "offset": start,
            "allocation_size": end - start,
            "encoded_size": decoded.consumed,
            "decoded_size": len(decoded.output),
            "decoded_sha256": _sha256(decoded.output),
            "tim2_count": len(records),
        }
        if len(records) == 1:
            record = records[0]
            picture = record.pictures[0]
            item.update(
                {
                    "tim2_offset": record.offset,
                    "tim2_size": record.size,
                    "picture_count": len(record.pictures),
                    "width": picture.width,
                    "height": picture.height,
                    "image_size": picture.image_size,
                    "clut_size": picture.clut_size,
                }
            )
        inventory.append(item)
        decoded_chunks[chunk_index] = (chunk, decoded, records)
    return inventory, decoded_chunks


def build_mtv_prop_intertitles(
    source_archive: bytes,
    source_slps: bytes,
    font_path: Path,
    contract: Mapping[str, object],
) -> tuple[bytes, dict]:
    """Render and inject the two reviewed Chinese transition subtitles."""

    table_start = contract.get("offset_table_start")
    table_end = contract.get("offset_table_end")
    expected_chunk_count = contract.get("expected_chunk_count")
    if (
        not isinstance(table_start, int)
        or not isinstance(table_end, int)
        or table_end <= table_start
        or (table_end - table_start) % 4
        or expected_chunk_count != (table_end - table_start) // 4 - 1
    ):
        raise MtvPropIntertitleError("MTV_PROP offset-table contract is invalid")
    if table_end > len(source_slps):
        raise MtvPropIntertitleError("MTV_PROP offset table exceeds SLPS")
    offsets = struct.unpack_from(
        f"<{(table_end - table_start) // 4}I",
        source_slps,
        table_start,
    )
    if (
        offsets[0] != 0
        or offsets[-1] != len(source_archive)
        or any(left >= right for left, right in zip(offsets, offsets[1:]))
        or any(offset % 16 for offset in offsets)
    ):
        raise MtvPropIntertitleError("MTV_PROP archive offsets drifted")

    inventory, decoded_chunks = _chunk_inventory(source_archive, offsets)
    if (
        len(inventory) != expected_chunk_count
        or any(item["tim2_count"] != 1 for item in inventory)
        or any(item.get("tim2_offset") != 32 for item in inventory)
        or _stable_sha256(inventory) != contract.get("inventory_sha256")
    ):
        raise MtvPropIntertitleError(
            "MTV_PROP full TIM2 inventory drift: "
            f"count={len(inventory)} sha256={_stable_sha256(inventory)}"
        )

    render = contract.get("render")
    entries = contract.get("entries")
    if not isinstance(render, dict) or not isinstance(entries, list):
        raise MtvPropIntertitleError("MTV_PROP render contract is invalid")
    executable = require_imagemagick()
    version = imagemagick_version(executable)
    if version != render.get("imagemagick_version"):
        raise MtvPropIntertitleError(
            f"ImageMagick version drift: {version!r}"
        )
    font = font_path.read_bytes()
    if (
        len(font) != render.get("font_size")
        or _sha256(font) != render.get("font_sha256")
    ):
        raise MtvPropIntertitleError("intertitle font lock drift")
    if (
        render.get("width") != 640
        or render.get("height") != 448
        or render.get("strip_y") != 200
        or render.get("strip_height") != 48
        or render.get("point_size") != 29
        or render.get("supersample_factor") != 2
        or render.get("palette_rounding") != "nearest_gray_16_cap_15"
        or render.get("storage_layout")
        != "linear_row_major_despite_psmt8_header"
    ):
        raise MtvPropIntertitleError("intertitle geometry contract drift")

    output = bytearray(source_archive)
    entry_reports = []
    owned_archive_indexes = set()
    expected_indexes = list(range(16))
    for entry in entries:
        if not isinstance(entry, dict):
            raise MtvPropIntertitleError("intertitle entry is malformed")
        chunk_index = entry.get("chunk_index")
        if not isinstance(chunk_index, int) or chunk_index not in decoded_chunks:
            raise MtvPropIntertitleError("intertitle chunk index is invalid")
        chunk, decoded, records = decoded_chunks[chunk_index]
        record = records[0]
        if len(record.pictures) != 1:
            raise MtvPropIntertitleError("intertitle TIM2 picture count drift")
        picture = record.pictures[0]
        if (
            record.offset != 32
            or record.size != len(decoded.output) - 32
            or picture.width != 640
            or picture.height != 448
            or picture.image_size != 640 * 448
            or picture.clut_size != 1024
            or picture.image_type != 5
            or picture.clut_color_count != 256
        ):
            raise MtvPropIntertitleError(
                f"intertitle TIM2 layout drift: chunk={chunk_index}"
            )
        if _sha256(decoded.output) != entry.get("source_decoded_sha256"):
            raise MtvPropIntertitleError(
                f"intertitle decoded preimage drift: chunk={chunk_index}"
            )
        image_offset = picture.offset + picture.header_size
        image_end = image_offset + picture.image_size
        # These two TIM2 pictures advertise indexed 8-bpp/PSMT8 metadata, but
        # their stored image bytes are already linear row-major indexes.  The
        # original Japanese glyphs are readable directly in this byte order;
        # applying the generic GS PSMT8 permutation turns them into the same
        # horizontal stripes seen at runtime.  Preserve that asset-specific
        # storage contract and edit the linear bytes in place.
        linear = bytearray(decoded.output[image_offset:image_end])
        palette = decoded.output[
            image_end : image_end + picture.clut_size
        ]
        if (
            _sha256(linear) != entry.get("source_linear_indexes_sha256")
            or sorted(set(linear)) != expected_indexes
            or _source_bbox(linear, picture.width) != entry.get("source_bbox")
            or _sha256(palette) != render.get("source_palette_sha256")
        ):
            raise MtvPropIntertitleError(
                f"intertitle indexed preimage drift: chunk={chunk_index}"
            )

        translation = entry.get("translation")
        if not isinstance(translation, str) or not translation:
            raise MtvPropIntertitleError("intertitle translation is invalid")
        mask = render_grayscale_text_mask(
            executable,
            font_path,
            translation,
            width=render["width"],
            height=render["strip_height"],
            point_size=render["point_size"],
            stroke_gray="white",
            stroke_width=0,
            supersample_factor=render["supersample_factor"],
        )
        if _sha256(mask) != entry.get("render_mask_sha256"):
            raise MtvPropIntertitleError(
                f"intertitle frozen render drift: chunk={chunk_index}"
            )
        strip_y = render["strip_y"]
        for y in range(strip_y, strip_y + render["strip_height"]):
            linear_row = y * picture.width
            mask_row = (y - strip_y) * picture.width
            for x in range(picture.width):
                linear[linear_row + x] = min(
                    15,
                    (mask[mask_row + x] + 8) // 16,
                )
        if _sha256(linear) != entry.get("output_linear_indexes_sha256"):
            raise MtvPropIntertitleError(
                f"intertitle output index drift: chunk={chunk_index}"
            )
        modified = bytearray(decoded.output)
        modified[image_offset:image_end] = linear
        modified_bytes = bytes(modified)
        if (
            modified_bytes[:image_offset] != decoded.output[:image_offset]
            or modified_bytes[image_end:] != decoded.output[image_end:]
            or scan_tim2(modified_bytes) != records
            or _sha256(modified_bytes) != entry.get("output_decoded_sha256")
        ):
            raise MtvPropIntertitleError(
                f"intertitle write escaped indexed pixels: chunk={chunk_index}"
            )
        encoded = reencode_changed_suffix(
            chunk,
            modified_bytes,
            strategy="rust-fit",
            min_match_length=2,
            max_match_chain=16384,
            lazy_matching=False,
            max_output_size=len(chunk),
            original_result=decoded,
        )
        if (
            len(encoded) != entry.get("output_encoded_size")
            or _sha256(encoded) != entry.get("output_encoded_sha256")
        ):
            raise MtvPropIntertitleError(
                "intertitle encoded output drift: "
                f"chunk={chunk_index} size={len(encoded)} "
                f"sha256={_sha256(encoded)}"
            )
        stored = encoded + bytes(len(chunk) - len(encoded))
        start, end = offsets[chunk_index], offsets[chunk_index + 1]
        current_owned = set(range(start, end))
        if current_owned & owned_archive_indexes:
            raise MtvPropIntertitleError("intertitle archive ownership overlaps")
        owned_archive_indexes.update(current_owned)
        output[start:end] = stored
        reread = decode_production(stored)
        if reread.output != modified_bytes or any(stored[reread.consumed :]):
            raise MtvPropIntertitleError(
                f"intertitle compressed reread drift: chunk={chunk_index}"
            )
        entry_reports.append(
            {
                "chunk_index": chunk_index,
                "source_text": entry.get("source_text"),
                "translation": translation,
                "source_bbox": entry["source_bbox"],
                "storage_layout": render["storage_layout"],
                "source_linear_indexes_sha256": entry[
                    "source_linear_indexes_sha256"
                ],
                "render_mask_sha256": entry["render_mask_sha256"],
                "output_linear_indexes_sha256": entry[
                    "output_linear_indexes_sha256"
                ],
                "source_allocation_size": len(chunk),
                "output_encoded_size": len(encoded),
                "compressed_headroom": len(chunk) - len(encoded),
                "fixed_chunk_span_preserved": True,
                "tim2_metadata_preserved": True,
                "palette_preserved_byte_exact": True,
                "translated_reread_exact": True,
            }
        )

    output_bytes = bytes(output)
    if (
        len(output_bytes) != len(source_archive)
        or _sha256(output_bytes) != contract.get("output_archive_sha256")
        or any(
            before != after and index not in owned_archive_indexes
            for index, (before, after) in enumerate(
                zip(source_archive, output_bytes)
            )
        )
    ):
        raise MtvPropIntertitleError("MTV_PROP archive writeback drift")
    return output_bytes, {
        "chunk_count": len(inventory),
        "tim2_chunk_count": sum(item["tim2_count"] for item in inventory),
        "inventory_sha256": _stable_sha256(inventory),
        "localized_chunk_indices": [
            item["chunk_index"] for item in entry_reports
        ],
        "localized_entry_count": len(entry_reports),
        "entries": entry_reports,
        "font_sha256": _sha256(font),
        "imagemagick_version": version,
        "codec_strategy": "rust-fit",
        "source_palette_sha256": render["source_palette_sha256"],
        "archive_size_preserved": True,
        "archive_offsets_preserved": True,
        "unchanged_chunk_count": len(inventory) - len(entry_reports),
        "non_target_chunks_preserved_byte_exact": True,
        "fixed_chunk_spans_preserved": True,
        "tim2_metadata_preserved": True,
        "palette_preserved_byte_exact": True,
        "translated_reread_exact": True,
        "runtime_acceptance": "not tested",
    }


__all__ = [
    "MtvPropIntertitleError",
    "build_mtv_prop_intertitles",
]
