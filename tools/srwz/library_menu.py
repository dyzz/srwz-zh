"""Deterministic fixed-record writeback for the LIBRARY main-menu atlas."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

from .imagemagick import (
    imagemagick_version,
    render_grayscale_text_mask,
    require_imagemagick,
)
from .library import LibraryScopeError, verify_jtim_library_menu_record
from .tim2 import scan_tim2


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise LibraryScopeError(f"{label} must be an integer")
    return value


def _crop(
    image: bytes | bytearray,
    width: int,
    x: int,
    y: int,
    crop_width: int,
    crop_height: int,
) -> bytes:
    return b"".join(
        image[(y + row) * width + x : (y + row) * width + x + crop_width]
        for row in range(crop_height)
    )


def _palette_luminance(
    palette: bytes,
    index: int,
) -> float:
    # TIM2 CSM1 rearranges each 8-entry pair inside a 32-color block.
    stored_index = (
        (index & 0xE7)
        | ((index & 0x08) << 1)
        | ((index & 0x10) >> 1)
    )
    start = stored_index * 4
    red, green, blue, alpha = palette[start : start + 4]
    if alpha == 0:
        raise LibraryScopeError(
            f"LIBRARY menu palette index {index} is transparent"
        )
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def build_jtim_library_menu(
    source: bytes,
    raw_lock: Mapping[str, object],
    *,
    font_path: Path,
) -> tuple[bytes, dict[str, object]]:
    """Replace all twelve visible label variants without changing TIM2 shape."""

    source_metadata = verify_jtim_library_menu_record(source, raw_lock)
    render = raw_lock.get("writeback")
    labels = raw_lock.get("labels")
    if not isinstance(render, Mapping) or not isinstance(labels, Mapping):
        raise LibraryScopeError("JTIM LIBRARY menu writeback contract is missing")
    magick = require_imagemagick()
    version = imagemagick_version(magick)
    if version != render.get("imagemagick_version"):
        raise LibraryScopeError("JTIM LIBRARY menu ImageMagick version drift")
    masks = render.get("masks")
    if not isinstance(masks, list) or len(masks) != 12:
        raise LibraryScopeError("JTIM LIBRARY menu must define twelve masks")

    record_index = _integer(raw_lock.get("record_index"), "record index")
    record = scan_tim2(source)[record_index]
    picture = record.pictures[0]
    if picture.image_size != picture.width * picture.height:
        raise LibraryScopeError("JTIM LIBRARY menu is not linear 8-bpp")
    image_start = picture.offset + picture.header_size
    image_end = image_start + picture.image_size
    palette_end = image_end + picture.clut_size
    image = bytearray(source[image_start:image_end])
    palette = source[image_end:palette_end]
    if len(palette) != 256 * 4:
        raise LibraryScopeError("JTIM LIBRARY menu palette size drift")

    point_size = _integer(render.get("point_size"), "menu point size")
    stroke_gray = render.get("stroke_gray")
    stroke_width = render.get("stroke_width")
    fill_stroke_width = render.get("fill_stroke_width", 0)
    if (
        not isinstance(stroke_gray, str)
        or not isinstance(stroke_width, (int, float))
        or isinstance(stroke_width, bool)
        or not isinstance(fill_stroke_width, (int, float))
        or isinstance(fill_stroke_width, bool)
    ):
        raise LibraryScopeError("JTIM LIBRARY menu render style drift")

    reports = []
    seen_ids = set()
    for raw_mask in masks:
        if not isinstance(raw_mask, Mapping):
            raise LibraryScopeError("JTIM LIBRARY menu mask is malformed")
        mask_id = raw_mask.get("id")
        source_text = raw_mask.get("source_text")
        if (
            not isinstance(mask_id, str)
            or not mask_id
            or mask_id in seen_ids
            or not isinstance(source_text, str)
            or source_text not in labels
        ):
            raise LibraryScopeError("JTIM LIBRARY menu mask identity drift")
        seen_ids.add(mask_id)
        translation = labels[source_text]
        if not isinstance(translation, str) or not translation:
            raise LibraryScopeError("JTIM LIBRARY menu translation drift")
        x = _integer(raw_mask.get("x"), f"{mask_id} x")
        y = _integer(raw_mask.get("y"), f"{mask_id} y")
        width = _integer(raw_mask.get("width"), f"{mask_id} width")
        height = _integer(raw_mask.get("height"), f"{mask_id} height")
        horizontal_offset = _integer(
            raw_mask.get("horizontal_offset", 0),
            f"{mask_id} horizontal offset",
        )
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > picture.width
            or y + height > picture.height
        ):
            raise LibraryScopeError(f"JTIM LIBRARY menu mask is outside: {mask_id}")
        source_crop = _crop(image, picture.width, x, y, width, height)
        expected_source_hash = raw_mask.get("source_indexes_sha256")
        if _sha256(source_crop) != expected_source_hash:
            raise LibraryScopeError(
                f"JTIM LIBRARY menu source-pixel drift: {mask_id}"
            )
        palette_start = _integer(
            raw_mask.get("palette_start"),
            f"{mask_id} palette start",
        )
        palette_stop = _integer(
            raw_mask.get("palette_stop"),
            f"{mask_id} palette stop",
        )
        if not 0 < palette_start <= palette_stop < 256:
            raise LibraryScopeError(f"JTIM LIBRARY menu palette range drift: {mask_id}")
        ramp = [
            (index, _palette_luminance(palette, index))
            for index in range(palette_start, palette_stop + 1)
        ]
        maximum_luminance = max(value for _index, value in ramp)
        mask = render_grayscale_text_mask(
            magick,
            font_path,
            translation,
            width=width,
            height=height,
            point_size=_integer(
                raw_mask.get("point_size", point_size),
                f"{mask_id} point size",
            ),
            stroke_gray=stroke_gray,
            stroke_width=float(stroke_width),
            fill_stroke_width=float(fill_stroke_width),
            horizontal_offset=horizontal_offset,
        )
        changed_pixels = 0
        for row in range(height):
            destination = (y + row) * picture.width + x
            mask_start = row * width
            for column, tone in enumerate(mask[mask_start : mask_start + width]):
                prior = image[destination + column]
                if tone == 0:
                    replacement = 0
                else:
                    target = tone * maximum_luminance / 255
                    replacement = min(
                        ramp,
                        key=lambda item: (abs(item[1] - target), item[0]),
                    )[0]
                image[destination + column] = replacement
                changed_pixels += prior != replacement
        output_crop = _crop(image, picture.width, x, y, width, height)
        if not set(output_crop) <= {0, *range(palette_start, palette_stop + 1)}:
            raise LibraryScopeError(
                f"JTIM LIBRARY menu output index escaped palette: {mask_id}"
            )
        reports.append(
            {
                "id": mask_id,
                "source_text": source_text,
                "translation": translation,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "horizontal_offset": horizontal_offset,
                "palette_start": palette_start,
                "palette_stop": palette_stop,
                "source_indexes_sha256": expected_source_hash,
                "output_indexes_sha256": _sha256(output_crop),
                "changed_pixel_count": changed_pixels,
                "visible_pixel_count": sum(value != 0 for value in output_crop),
            }
        )

    output = source[:image_start] + bytes(image) + source[image_end:]
    if len(output) != len(source):
        raise LibraryScopeError("JTIM LIBRARY menu changed member size")
    output_record = scan_tim2(output)[record_index]
    if output_record != record:
        raise LibraryScopeError("JTIM LIBRARY menu changed TIM2 metadata")
    if output[:image_start] != source[:image_start] or output[image_end:] != source[image_end:]:
        raise LibraryScopeError("JTIM LIBRARY menu changed bytes outside pixels")
    return output, {
        "member": raw_lock.get("member"),
        "record_index": record_index,
        "source_record": source_metadata,
        "output_record_sha256": _sha256(
            output[record.offset : record.offset + record.size]
        ),
        "image_offset": image_start,
        "image_size": picture.image_size,
        "font_path": str(font_path),
        "font_sha256": _sha256(font_path.read_bytes()),
        "imagemagick_version": version,
        "labels": reports,
        "all_six_labels_built_in_both_states": len(reports) == 12,
        "member_size_preserved": len(output) == len(source),
        "tim2_metadata_preserved": output_record == record,
        "clut_and_non_image_bytes_preserved": (
            output[:image_start] == source[:image_start]
            and output[image_end:] == source[image_end:]
        ),
        "linear_index_reread_exact": output[image_start:image_end] == bytes(image),
    }


__all__ = ["build_jtim_library_menu"]
