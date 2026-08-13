"""Deterministic fixed-record writeback for the LIBRARY main-menu atlas."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import zlib
from pathlib import Path
from typing import Mapping

from .imagemagick import (
    imagemagick_version,
    render_grayscale_text_mask,
    render_tim2_png8,
    require_imagemagick,
)
from .library import LibraryScopeError, verify_jtim_library_menu_record
from .tim2 import scan_tim2


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha256(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _frozen_bytes(data: bytes) -> dict[str, object]:
    return {
        "size": len(data),
        "sha256": _sha256(data),
        "zlib_base64": base64.b64encode(zlib.compress(data, 9)).decode("ascii"),
    }


def _thaw_bytes(raw: object, *, label: str, expected_size: int) -> bytes:
    if not isinstance(raw, Mapping):
        raise LibraryScopeError(f"{label} snapshot payload is missing")
    encoded = raw.get("zlib_base64")
    if not isinstance(encoded, str) or not encoded:
        raise LibraryScopeError(f"{label} snapshot payload is invalid")
    try:
        data = zlib.decompress(base64.b64decode(encoded, validate=True))
    except (ValueError, zlib.error) as error:
        raise LibraryScopeError(
            f"{label} snapshot payload cannot be decoded"
        ) from error
    if (
        len(data) != expected_size
        or raw.get("size") != len(data)
        or raw.get("sha256") != _sha256(data)
    ):
        raise LibraryScopeError(f"{label} snapshot payload drift")
    return data


def _project_path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise LibraryScopeError("LIBRARY menu project path is invalid")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise LibraryScopeError("LIBRARY menu path escapes project root") from error
    return path


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
    project_root: Path | None = None,
    live_render: bool = False,
    render_snapshot_sink: dict | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Replace all labels from frozen masks or an explicit refreeze."""

    source_metadata = verify_jtim_library_menu_record(source, raw_lock)
    render = raw_lock.get("writeback")
    labels = raw_lock.get("labels")
    if not isinstance(render, Mapping) or not isinstance(labels, Mapping):
        raise LibraryScopeError("JTIM LIBRARY menu writeback contract is missing")
    configured_version = render.get("imagemagick_version")
    if not isinstance(configured_version, str) or not configured_version:
        raise LibraryScopeError("JTIM LIBRARY menu ImageMagick lock is missing")
    if live_render:
        magick = require_imagemagick()
        version = imagemagick_version(magick)
        if version != configured_version:
            raise LibraryScopeError("JTIM LIBRARY menu ImageMagick version drift")
    else:
        magick = None
        version = configured_version
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

    font_sha256 = _sha256(font_path.read_bytes())
    source_record_sha256 = _sha256(
        source[record.offset : record.offset + record.size]
    )
    render_contract_sha256 = _json_sha256(
        {
            "labels": dict(labels),
            "point_size": point_size,
            "stroke_gray": stroke_gray,
            "stroke_width": stroke_width,
            "fill_stroke_width": fill_stroke_width,
            "masks": masks,
        }
    )
    render_snapshot_path = None
    render_snapshot = None
    if not live_render:
        if project_root is None:
            raise LibraryScopeError(
                "JTIM LIBRARY menu project root is required for frozen renders"
            )
        snapshot_reference = render.get("render_snapshot")
        if not isinstance(snapshot_reference, Mapping):
            raise LibraryScopeError(
                "JTIM LIBRARY menu frozen render snapshot is missing"
            )
        render_snapshot_path = _project_path(
            project_root,
            snapshot_reference.get("path"),
        )
        if (
            not render_snapshot_path.is_file()
            or render_snapshot_path.stat().st_size
            != snapshot_reference.get("size")
            or _sha256(render_snapshot_path.read_bytes())
            != snapshot_reference.get("sha256")
        ):
            raise LibraryScopeError(
                "JTIM LIBRARY menu frozen render snapshot lock drift"
            )
        try:
            render_snapshot = json.loads(
                render_snapshot_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise LibraryScopeError(
                "JTIM LIBRARY menu frozen render snapshot is unreadable"
            ) from error
        if (
            not isinstance(render_snapshot, dict)
            or render_snapshot.get("schema_version") != 1
            or render_snapshot.get("status") != "reviewed_locked"
            or render_snapshot.get("selection_authority")
            != "frozen_rendered_text_masks"
            or render_snapshot.get("source_record_sha256")
            != source_record_sha256
            or render_snapshot.get("font_sha256") != font_sha256
            or render_snapshot.get("render_contract_sha256")
            != render_contract_sha256
            or render_snapshot.get("imagemagick_version") != version
            or not isinstance(render_snapshot.get("labels"), list)
            or len(render_snapshot["labels"]) != len(masks)
        ):
            raise LibraryScopeError(
                "JTIM LIBRARY menu frozen render provenance drift"
            )

    reports = []
    seen_ids = set()
    grayscale_masks = []
    for mask_index, raw_mask in enumerate(masks):
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
        if live_render:
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
        else:
            frozen_label = render_snapshot["labels"][mask_index]
            if (
                not isinstance(frozen_label, Mapping)
                or frozen_label.get("id") != mask_id
                or frozen_label.get("translation_sha256")
                != _sha256(translation.encode("utf-8"))
            ):
                raise LibraryScopeError(
                    "JTIM LIBRARY menu frozen render label identity drift"
                )
            mask = _thaw_bytes(
                frozen_label.get("mask"),
                label=f"{mask_id} text mask",
                expected_size=width * height,
            )
        grayscale_masks.append(mask)
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
    frozen_preview = None
    if live_render:
        with tempfile.TemporaryDirectory(prefix="srwz-library-menu-freeze-") as directory:
            temporary = Path(directory)
            record_path = temporary / "library-menu.tm2"
            preview_path = temporary / "library-menu.png"
            record_path.write_bytes(
                output[record.offset : record.offset + record.size]
            )
            render_tim2_png8(magick, record_path, preview_path)
            frozen_preview = _frozen_bytes(preview_path.read_bytes())
        if render_snapshot_sink is not None:
            render_snapshot_sink.update(
                {
                    "schema_version": 1,
                    "status": "reviewed_locked",
                    "selection_authority": "frozen_rendered_text_masks",
                    "source_record_sha256": source_record_sha256,
                    "font_sha256": font_sha256,
                    "render_contract_sha256": render_contract_sha256,
                    "imagemagick_version": version,
                    "labels": [
                        {
                            "id": raw_mask["id"],
                            "translation_sha256": _sha256(
                                labels[raw_mask["source_text"]].encode("utf-8")
                            ),
                            "mask": _frozen_bytes(mask),
                        }
                        for raw_mask, mask in zip(masks, grayscale_masks)
                    ],
                    "preview_png": frozen_preview,
                }
            )
    else:
        frozen_preview = render_snapshot.get("preview_png")
        if not isinstance(frozen_preview, Mapping) or not isinstance(
            frozen_preview.get("size"), int
        ):
            raise LibraryScopeError(
                "JTIM LIBRARY menu frozen preview is invalid"
            )
        _thaw_bytes(
            frozen_preview,
            label="JTIM LIBRARY menu preview PNG",
            expected_size=frozen_preview["size"],
        )
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
        "render_source": (
            "live_explicit_refreeze" if live_render else "locked_snapshot"
        ),
        "render_snapshot": (
            {
                "path": str(
                    render_snapshot_path.resolve().relative_to(
                        project_root.resolve()
                    )
                ),
                "size": render_snapshot_path.stat().st_size,
                "sha256": _sha256(render_snapshot_path.read_bytes()),
            }
            if render_snapshot_path is not None and project_root is not None
            else {
                "source": "live_explicit_refreeze",
                "render_contract_sha256": render_contract_sha256,
            }
        ),
        "frozen_preview_png": {
            "size": frozen_preview["size"],
            "sha256": frozen_preview["sha256"],
        },
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
