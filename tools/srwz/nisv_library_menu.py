"""Frozen writeback for indexed runtime LIBRARY textures."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import zlib
from pathlib import Path
from typing import Mapping

from .codec import decode_production, reencode_changed_suffix
from .imagemagick import (
    imagemagick_version,
    render_grayscale_text_mask,
    require_imagemagick,
    write_deterministic_rgba8_png,
)
from .library import LibraryScopeError
from .tim2 import scan_tim2
from .tim2_writeback import swizzle_psmt8, unswizzle_psmt8


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
        raise LibraryScopeError("runtime LIBRARY menu project path is invalid")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise LibraryScopeError(
            "runtime LIBRARY menu path escapes project root"
        ) from error
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


def _stored_palette_index(index: int) -> int:
    return (
        (index & 0xE7)
        | ((index & 0x08) << 1)
        | ((index & 0x10) >> 1)
    )


def _palette_luminance(palette: bytes, index: int) -> float:
    start = _stored_palette_index(index) * 4
    red, green, blue, alpha = palette[start : start + 4]
    if alpha == 0:
        raise LibraryScopeError(
            f"runtime LIBRARY menu palette index {index} is transparent"
        )
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _render_rgba(indexes: bytes, palette: bytes) -> bytes:
    rendered = bytearray(len(indexes) * 4)
    for pixel, index in enumerate(indexes):
        source = _stored_palette_index(index) * 4
        target = pixel * 4
        red, green, blue, alpha = palette[source : source + 4]
        rendered[target : target + 4] = bytes(
            (red, green, blue, min(255, alpha * 2))
        )
    return bytes(rendered)


def _alpha_plane(indexes: bytes, palette: bytes) -> bytes:
    """Return the stored PS2 CLUT alpha value for every logical pixel."""

    return bytes(
        palette[_stored_palette_index(index) * 4 + 3]
        for index in indexes
    )


def _build_nisv_text_texture(
    archive: bytes,
    raw_lock: Mapping[str, object],
    *,
    font_path: Path,
    expected_chunk_index: int,
    expected_mask_count: int,
    selection_authority: str,
    temporary_prefix: str,
    preview_filename: str,
    project_root: Path | None = None,
    live_render: bool = False,
    render_snapshot_sink: dict | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Patch one compressed NISV text texture and preserve archive layout."""

    target = raw_lock.get("target")
    render = raw_lock.get("writeback")
    labels = raw_lock.get("labels")
    codec = raw_lock.get("codec")
    if not all(
        isinstance(value, Mapping)
        for value in (target, render, labels, codec)
    ):
        raise LibraryScopeError("runtime LIBRARY menu contract is incomplete")

    chunk_index = _integer(target.get("chunk_index"), "runtime menu chunk index")
    stored_start = _integer(target.get("stored_start"), "runtime menu stored start")
    stored_end = _integer(target.get("stored_end"), "runtime menu stored end")
    if (
        chunk_index != expected_chunk_index
        or not 0 <= stored_start < stored_end <= len(archive)
    ):
        raise LibraryScopeError("runtime LIBRARY menu chunk span drift")
    stored = archive[stored_start:stored_end]
    if (
        len(stored) != target.get("stored_size")
        or _sha256(stored) != target.get("stored_sha256")
    ):
        raise LibraryScopeError("runtime LIBRARY menu stored chunk lock drift")
    decoded = decode_production(stored)
    if (
        decoded.consumed != target.get("stored_consumed")
        or any(stored[decoded.consumed :])
        or len(decoded.output) != target.get("decoded_size")
        or _sha256(decoded.output) != target.get("decoded_sha256")
    ):
        raise LibraryScopeError("runtime LIBRARY menu decoded chunk lock drift")

    record_index = _integer(target.get("record_index"), "runtime menu record index")
    records = scan_tim2(decoded.output)
    if not 0 <= record_index < len(records):
        raise LibraryScopeError("runtime LIBRARY menu TIM2 record is missing")
    record = records[record_index]
    picture = record.pictures[0]
    source_record = decoded.output[record.offset : record.end]
    if (
        record.offset != target.get("record_offset")
        or record.size != target.get("record_size")
        or _sha256(source_record) != target.get("record_sha256")
        or len(record.pictures) != 1
        or picture.width != target.get("width")
        or picture.height != target.get("height")
        or picture.image_type != target.get("image_type")
        or picture.image_size != picture.width * picture.height
        or picture.clut_size != 256 * 4
    ):
        raise LibraryScopeError("runtime LIBRARY menu TIM2 lock drift")

    image_start = picture.offset + picture.header_size
    image_end = image_start + picture.image_size
    palette_end = image_end + picture.clut_size
    stored_indexes = decoded.output[image_start:image_end]
    storage_layout = target.get("storage_layout", "gs_psmt8")
    if storage_layout == "gs_psmt8":
        logical_source = unswizzle_psmt8(
            stored_indexes,
            picture.width,
            picture.height,
        )
    elif storage_layout == "linear_indexed8":
        logical_source = stored_indexes
    else:
        raise LibraryScopeError(
            "runtime LIBRARY menu storage-layout contract is invalid"
        )
    if _sha256(logical_source) != target.get("logical_indexes_sha256"):
        raise LibraryScopeError("runtime LIBRARY menu logical-index lock drift")
    logical = bytearray(logical_source)
    palette = decoded.output[image_end:palette_end]

    configured_version = render.get("imagemagick_version")
    if not isinstance(configured_version, str) or not configured_version:
        raise LibraryScopeError("runtime LIBRARY menu ImageMagick lock is missing")
    if live_render:
        magick = require_imagemagick()
        version = imagemagick_version(magick)
        if version != configured_version:
            raise LibraryScopeError("runtime LIBRARY menu ImageMagick version drift")
    else:
        magick = None
        version = configured_version
    masks = render.get("masks")
    if not isinstance(masks, list) or len(masks) != expected_mask_count:
        raise LibraryScopeError(
            "runtime NISV text texture mask-count drift: "
            f"expected {expected_mask_count}"
        )
    point_size = _integer(render.get("point_size"), "runtime menu point size")
    supersample_factor = _integer(
        render.get("supersample_factor", 1),
        "runtime menu supersample factor",
    )
    stroke_gray = render.get("stroke_gray")
    stroke_width = render.get("stroke_width")
    fill_stroke_width = render.get("fill_stroke_width", 0)
    clear_start = _integer(render.get("clear_index_start"), "clear index start")
    clear_stop = _integer(render.get("clear_index_stop"), "clear index stop")
    palette_start = _integer(render.get("palette_start"), "palette start")
    palette_stop = _integer(render.get("palette_stop"), "palette stop")
    raw_palette_indexes = render.get("palette_indexes")
    if raw_palette_indexes is None:
        palette_indexes = list(range(palette_start, palette_stop + 1))
    elif (
        not isinstance(raw_palette_indexes, list)
        or not raw_palette_indexes
        or any(
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 < index < 256
            for index in raw_palette_indexes
        )
        or len(set(raw_palette_indexes)) != len(raw_palette_indexes)
    ):
        raise LibraryScopeError(
            "runtime LIBRARY menu palette-index contract is invalid"
        )
    else:
        palette_indexes = list(raw_palette_indexes)
    require_alpha_mask_preserved = render.get(
        "require_alpha_mask_preserved", False
    )
    if (
        not isinstance(stroke_gray, str)
        or not isinstance(stroke_width, (int, float))
        or isinstance(stroke_width, bool)
        or not isinstance(fill_stroke_width, (int, float))
        or isinstance(fill_stroke_width, bool)
        or not 1 <= supersample_factor <= 8
        or not 0 < clear_start <= clear_stop < 256
        or not 0 < palette_start <= palette_stop < 256
        or not isinstance(require_alpha_mask_preserved, bool)
    ):
        raise LibraryScopeError("runtime LIBRARY menu render style drift")

    font_sha256 = _sha256(font_path.read_bytes())
    render_contract = {
        "labels": dict(labels),
        "point_size": point_size,
        "stroke_gray": stroke_gray,
        "stroke_width": stroke_width,
        "fill_stroke_width": fill_stroke_width,
        "supersample_factor": supersample_factor,
        "clear_index_start": clear_start,
        "clear_index_stop": clear_stop,
        "palette_start": palette_start,
        "palette_stop": palette_stop,
        "masks": masks,
    }
    if raw_palette_indexes is not None:
        render_contract["palette_indexes"] = palette_indexes
    if "require_alpha_mask_preserved" in render:
        render_contract["require_alpha_mask_preserved"] = (
            require_alpha_mask_preserved
        )
    render_contract_sha256 = _json_sha256(render_contract)
    snapshot_path = None
    snapshot = None
    if not live_render:
        if project_root is None:
            raise LibraryScopeError(
                "runtime LIBRARY menu project root is required for frozen renders"
            )
        snapshot_reference = render.get("render_snapshot")
        if not isinstance(snapshot_reference, Mapping):
            raise LibraryScopeError(
                "runtime LIBRARY menu frozen render snapshot is missing"
            )
        snapshot_path = _project_path(project_root, snapshot_reference.get("path"))
        if (
            not snapshot_path.is_file()
            or snapshot_path.stat().st_size != snapshot_reference.get("size")
            or _sha256(snapshot_path.read_bytes()) != snapshot_reference.get("sha256")
        ):
            raise LibraryScopeError("runtime LIBRARY menu snapshot lock drift")
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LibraryScopeError(
                "runtime LIBRARY menu frozen snapshot is unreadable"
            ) from error
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("schema_version") != 1
            or snapshot.get("status") != "reviewed_locked"
            or snapshot.get("selection_authority") != selection_authority
            or snapshot.get("source_record_sha256") != _sha256(source_record)
            or snapshot.get("source_logical_indexes_sha256")
            != _sha256(logical_source)
            or snapshot.get("font_sha256") != font_sha256
            or snapshot.get("render_contract_sha256") != render_contract_sha256
            or snapshot.get("imagemagick_version") != version
            or not isinstance(snapshot.get("labels"), list)
            or len(snapshot["labels"]) != len(masks)
        ):
            raise LibraryScopeError(
                "runtime LIBRARY menu frozen render provenance drift"
            )

    ramp = [
        (index, _palette_luminance(palette, index))
        for index in palette_indexes
    ]
    maximum_luminance = max(value for _index, value in ramp)
    reports = []
    grayscale_masks = []
    seen_ids = set()
    for mask_index, raw_mask in enumerate(masks):
        if not isinstance(raw_mask, Mapping):
            raise LibraryScopeError("runtime LIBRARY menu mask is malformed")
        mask_id = raw_mask.get("id")
        source_text = raw_mask.get("source_text")
        if (
            not isinstance(mask_id, str)
            or not mask_id
            or mask_id in seen_ids
            or not isinstance(source_text, str)
            or source_text not in labels
        ):
            raise LibraryScopeError("runtime LIBRARY menu mask identity drift")
        seen_ids.add(mask_id)
        translation = labels[source_text]
        if not isinstance(translation, str) or not translation:
            raise LibraryScopeError("runtime LIBRARY menu translation drift")
        x = _integer(raw_mask.get("x"), f"{mask_id} x")
        y = _integer(raw_mask.get("y"), f"{mask_id} y")
        width = _integer(raw_mask.get("width"), f"{mask_id} width")
        height = _integer(raw_mask.get("height"), f"{mask_id} height")
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > picture.width
            or y + height > picture.height
        ):
            raise LibraryScopeError(
                f"runtime LIBRARY menu mask is outside: {mask_id}"
            )
        before_label = _crop(
            logical,
            picture.width,
            x,
            y,
            width,
            height,
        )
        background_restore = raw_mask.get("background_restore")
        background_restore_report = None
        if background_restore is None:
            clear_x = _integer(raw_mask.get("clear_x"), f"{mask_id} clear x")
            clear_y = _integer(raw_mask.get("clear_y"), f"{mask_id} clear y")
            clear_width = _integer(
                raw_mask.get("clear_width"), f"{mask_id} clear width"
            )
            clear_height = _integer(
                raw_mask.get("clear_height"), f"{mask_id} clear height"
            )
            clear_dilation_radius = _integer(
                raw_mask.get("clear_dilation_radius", 0),
                f"{mask_id} clear dilation radius",
            )
            clear_replacement_index = _integer(
                raw_mask.get("clear_replacement_index", 0),
                f"{mask_id} clear replacement index",
            )
            if (
                clear_x < 0
                or clear_y < 0
                or clear_width <= 0
                or clear_height <= 0
                or clear_x + clear_width > picture.width
                or clear_y + clear_height > picture.height
                or not 0 <= clear_dilation_radius <= 8
                or not 0 <= clear_replacement_index < 256
            ):
                raise LibraryScopeError(
                    f"runtime LIBRARY menu clear mask is outside: {mask_id}"
                )
            source_crop = _crop(
                logical_source,
                picture.width,
                clear_x,
                clear_y,
                clear_width,
                clear_height,
            )
            if _sha256(source_crop) != raw_mask.get("source_indexes_sha256"):
                raise LibraryScopeError(
                    f"runtime LIBRARY menu source-pixel drift: {mask_id}"
                )
            clear_offsets = {
                row * picture.width + column
                for row in range(clear_y, clear_y + clear_height)
                for column in range(clear_x, clear_x + clear_width)
                if clear_start
                <= logical[row * picture.width + column]
                <= clear_stop
            }
            if clear_dilation_radius:
                clear_offsets = {
                    target_row * picture.width + target_column
                    for source_offset in clear_offsets
                    for target_row in range(
                        max(
                            clear_y,
                            source_offset // picture.width
                            - clear_dilation_radius,
                        ),
                        min(
                            clear_y + clear_height,
                            source_offset // picture.width
                            + clear_dilation_radius
                            + 1,
                        ),
                    )
                    for target_column in range(
                        max(
                            clear_x,
                            source_offset % picture.width
                            - clear_dilation_radius,
                        ),
                        min(
                            clear_x + clear_width,
                            source_offset % picture.width
                            + clear_dilation_radius
                            + 1,
                        ),
                    )
                }
            for offset in clear_offsets:
                logical[offset] = clear_replacement_index
        elif isinstance(background_restore, Mapping):
            restore_x = _integer(
                background_restore.get("x"),
                f"{mask_id} background restore x",
            )
            restore_y = _integer(
                background_restore.get("y"),
                f"{mask_id} background restore y",
            )
            restore_width = _integer(
                background_restore.get("width"),
                f"{mask_id} background restore width",
            )
            row_indexes = background_restore.get("row_indexes")
            if (
                not isinstance(row_indexes, list)
                or not row_indexes
                or any(
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or not 0 <= index < 256
                    for index in row_indexes
                )
                or restore_x < 0
                or restore_y < 0
                or restore_width <= 0
                or restore_x + restore_width > picture.width
                or restore_y + len(row_indexes) > picture.height
            ):
                raise LibraryScopeError(
                    f"runtime LIBRARY menu background restore is invalid: {mask_id}"
                )
            source_crop = _crop(
                logical_source,
                picture.width,
                restore_x,
                restore_y,
                restore_width,
                len(row_indexes),
            )
            if _sha256(source_crop) != raw_mask.get("source_indexes_sha256"):
                raise LibraryScopeError(
                    f"runtime LIBRARY menu source-pixel drift: {mask_id}"
                )
            for row, background_index in enumerate(row_indexes):
                start = (restore_y + row) * picture.width + restore_x
                logical[start : start + restore_width] = bytes(
                    [background_index]
                ) * restore_width
            restored_crop = _crop(
                logical,
                picture.width,
                restore_x,
                restore_y,
                restore_width,
                len(row_indexes),
            )
            background_restore_report = {
                "x": restore_x,
                "y": restore_y,
                "width": restore_width,
                "height": len(row_indexes),
                "row_indexes": list(row_indexes),
                "source_indexes_sha256": _sha256(source_crop),
                "restored_indexes_sha256": _sha256(restored_crop),
                "source_transparent_pixel_count": sum(
                    _alpha_plane(source_crop, palette)[pixel] == 0
                    for pixel in range(len(source_crop))
                ),
            }
        else:
            raise LibraryScopeError(
                f"runtime LIBRARY menu background restore is malformed: {mask_id}"
            )
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
                supersample_factor=supersample_factor,
                horizontal_offset=_integer(
                    raw_mask.get("horizontal_offset", 0),
                    f"{mask_id} horizontal offset",
                ),
            )
        else:
            frozen_label = snapshot["labels"][mask_index]
            if (
                not isinstance(frozen_label, Mapping)
                or frozen_label.get("id") != mask_id
                or frozen_label.get("translation_sha256")
                != _sha256(translation.encode("utf-8"))
            ):
                raise LibraryScopeError(
                    "runtime LIBRARY menu frozen label identity drift"
                )
            mask = _thaw_bytes(
                frozen_label.get("mask"),
                label=f"{mask_id} text mask",
                expected_size=width * height,
            )
        grayscale_masks.append(mask)
        for row in range(height):
            destination = (y + row) * picture.width + x
            mask_start = row * width
            for column, tone in enumerate(mask[mask_start : mask_start + width]):
                if tone == 0:
                    continue
                target_luminance = tone * maximum_luminance / 255
                logical[destination + column] = min(
                    ramp,
                    key=lambda item: (
                        abs(item[1] - target_luminance),
                        item[0],
                    ),
                )[0]
        output_label = b"".join(
            logical[
                (y + row) * picture.width + x :
                (y + row) * picture.width + x + width
            ]
            for row in range(height)
        )
        label_report = {
                "id": mask_id,
                "source_text": source_text,
                "translation": translation,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "source_indexes_sha256": raw_mask.get("source_indexes_sha256"),
                "output_indexes_sha256": _sha256(output_label),
                "changed_pixel_count": sum(
                    before != after
                    for before, after in zip(before_label, output_label)
                ),
            }
        if background_restore_report is not None:
            label_report["background_restore"] = background_restore_report
        reports.append(label_report)

    logical_output = bytes(logical)
    output_logical_sha256 = _sha256(logical_output)
    source_alpha_plane = _alpha_plane(logical_source, palette)
    output_alpha_plane = _alpha_plane(logical_output, palette)
    alpha_mask_preserved = output_alpha_plane == source_alpha_plane
    if require_alpha_mask_preserved and not alpha_mask_preserved:
        raise LibraryScopeError(
            "runtime LIBRARY menu alpha mask changed during writeback"
        )
    if not live_render and snapshot.get("output_logical_indexes_sha256") != output_logical_sha256:
        raise LibraryScopeError("runtime LIBRARY menu frozen output drift")
    preview_rgba = _render_rgba(logical_output, palette)
    frozen_preview = None
    if live_render:
        with tempfile.TemporaryDirectory(prefix=temporary_prefix) as directory:
            preview_path = Path(directory) / preview_filename
            write_deterministic_rgba8_png(
                magick,
                preview_rgba,
                preview_path,
                width=picture.width,
                height=picture.height,
            )
            frozen_preview = _frozen_bytes(preview_path.read_bytes())
        if render_snapshot_sink is not None:
            render_snapshot_sink.update(
                {
                    "schema_version": 1,
                    "status": "reviewed_locked",
                    "selection_authority": selection_authority,
                    "source_record_sha256": _sha256(source_record),
                    "source_logical_indexes_sha256": _sha256(logical_source),
                    "output_logical_indexes_sha256": output_logical_sha256,
                    "source_alpha_plane_sha256": _sha256(source_alpha_plane),
                    "output_alpha_plane_sha256": _sha256(output_alpha_plane),
                    "alpha_mask_preserved": alpha_mask_preserved,
                    "source_transparent_pixel_count": (
                        source_alpha_plane.count(0)
                    ),
                    "output_transparent_pixel_count": (
                        output_alpha_plane.count(0)
                    ),
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
        frozen_preview = snapshot.get("preview_png")
        if not isinstance(frozen_preview, Mapping) or not isinstance(
            frozen_preview.get("size"), int
        ):
            raise LibraryScopeError(
                "runtime LIBRARY menu frozen preview is invalid"
            )
        _thaw_bytes(
            frozen_preview,
            label="runtime LIBRARY menu preview PNG",
            expected_size=frozen_preview["size"],
        )

    if storage_layout == "gs_psmt8":
        stored_output_indexes = swizzle_psmt8(
            logical_output,
            picture.width,
            picture.height,
        )
    else:
        stored_output_indexes = logical_output
    output_decoded = (
        decoded.output[:image_start]
        + stored_output_indexes
        + decoded.output[image_end:]
    )
    if (
        len(output_decoded) != len(decoded.output)
        or output_decoded[:image_start] != decoded.output[:image_start]
        or output_decoded[image_end:] != decoded.output[image_end:]
        or scan_tim2(output_decoded) != records
    ):
        raise LibraryScopeError("runtime LIBRARY menu TIM2 writeback drift")
    reread_stored_indexes = output_decoded[image_start:image_end]
    if storage_layout == "gs_psmt8":
        reread_logical = unswizzle_psmt8(
            reread_stored_indexes,
            picture.width,
            picture.height,
        )
    else:
        reread_logical = reread_stored_indexes
    if reread_logical != logical_output:
        raise LibraryScopeError(
            "runtime LIBRARY menu indexed writeback did not round-trip"
        )
    try:
        rebuilt = reencode_changed_suffix(
            stored[: decoded.consumed],
            output_decoded,
            strategy=str(codec.get("strategy")),
            min_match_length=_integer(
                codec.get("min_match_length"), "codec min match length"
            ),
            max_match_chain=_integer(
                codec.get("max_match_chain"), "codec max match chain"
            ),
            lazy_matching=bool(codec.get("lazy_matching")),
            max_output_size=len(stored),
            original_result=decoded,
        )
    except (RuntimeError, ValueError) as error:
        raise LibraryScopeError(
            f"runtime LIBRARY menu compression failed: {error}"
        ) from error
    reread = decode_production(rebuilt)
    if (
        reread.consumed != len(rebuilt)
        or reread.output != output_decoded
        or reread.flags != decoded.flags
    ):
        raise LibraryScopeError("runtime LIBRARY menu codec round trip failed")
    padded = rebuilt + bytes(len(stored) - len(rebuilt))
    output_archive = archive[:stored_start] + padded + archive[stored_end:]
    if (
        len(output_archive) != len(archive)
        or output_archive[:stored_start] != archive[:stored_start]
        or output_archive[stored_end:] != archive[stored_end:]
    ):
        raise LibraryScopeError("runtime LIBRARY menu archive layout changed")

    return output_archive, {
        "member": raw_lock.get("member"),
        "chunk_index": chunk_index,
        "record_index": record_index,
        "record_offset": record.offset,
        "storage_layout": storage_layout,
        "source_record_sha256": _sha256(source_record),
        "output_record_sha256": _sha256(
            output_decoded[record.offset : record.end]
        ),
        "source_logical_indexes_sha256": _sha256(logical_source),
        "output_logical_indexes_sha256": output_logical_sha256,
        "source_alpha_plane_sha256": _sha256(source_alpha_plane),
        "output_alpha_plane_sha256": _sha256(output_alpha_plane),
        "alpha_mask_preserved": alpha_mask_preserved,
        "source_transparent_pixel_count": source_alpha_plane.count(0),
        "output_transparent_pixel_count": output_alpha_plane.count(0),
        "changed_pixel_count": sum(
            before != after
            for before, after in zip(logical_source, logical_output)
        ),
        "source_stored_size": len(stored),
        "output_encoded_size": len(rebuilt),
        "output_padding_size": len(stored) - len(rebuilt),
        "render_source": (
            "live_explicit_refreeze" if live_render else "locked_snapshot"
        ),
        "render_snapshot": (
            {
                "path": str(
                    snapshot_path.resolve().relative_to(project_root.resolve())
                ),
                "size": snapshot_path.stat().st_size,
                "sha256": _sha256(snapshot_path.read_bytes()),
            }
            if snapshot_path is not None and project_root is not None
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
        "all_labels_written": len(reports) == expected_mask_count,
        "all_six_labels_written": (
            expected_mask_count == 6 and len(reports) == 6
        ),
        "archive_size_preserved": len(output_archive) == len(archive),
        "archive_non_target_chunks_preserved": (
            output_archive[:stored_start] == archive[:stored_start]
            and output_archive[stored_end:] == archive[stored_end:]
        ),
        "tim2_metadata_preserved": scan_tim2(output_decoded) == records,
        "clut_and_non_image_bytes_preserved": (
            output_decoded[:image_start] == decoded.output[:image_start]
            and output_decoded[image_end:] == decoded.output[image_end:]
        ),
        "codec_round_trip_exact": True,
    }


def build_nisv_library_menu(
    archive: bytes,
    raw_lock: Mapping[str, object],
    *,
    font_path: Path,
    project_root: Path | None = None,
    live_render: bool = False,
    render_snapshot_sink: dict | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Patch the six-label runtime LIBRARY menu in NISVDATA chunk 0."""

    return _build_nisv_text_texture(
        archive,
        raw_lock,
        font_path=font_path,
        expected_chunk_index=0,
        expected_mask_count=6,
        selection_authority="runtime_nisv_frozen_rendered_text_masks",
        temporary_prefix="srwz-nisv-library-menu-freeze-",
        preview_filename="library-menu-runtime.png",
        project_root=project_root,
        live_render=live_render,
        render_snapshot_sink=render_snapshot_sink,
    )


def build_nisv_sound_select(
    archive: bytes,
    raw_lock: Mapping[str, object],
    *,
    font_path: Path,
    project_root: Path | None = None,
    live_render: bool = False,
    render_snapshot_sink: dict | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Patch the runtime sound-select title in NISVDATA chunk 1."""

    output, report = _build_nisv_text_texture(
        archive,
        raw_lock,
        font_path=font_path,
        expected_chunk_index=1,
        expected_mask_count=1,
        selection_authority="runtime_nisv_sound_select_frozen_text_mask",
        temporary_prefix="srwz-nisv-sound-select-freeze-",
        preview_filename="sound-select-runtime.png",
        project_root=project_root,
        live_render=live_render,
        render_snapshot_sink=render_snapshot_sink,
    )
    report["sound_select_title_written"] = report["all_labels_written"]
    return output, report


def build_hsfc_scenario_chart(
    archive: bytes,
    raw_lock: Mapping[str, object],
    *,
    font_path: Path,
    project_root: Path | None = None,
    live_render: bool = False,
    render_snapshot_sink: dict | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Patch the runtime Scenario Chart title in HSFC chunk 1."""

    output, report = _build_nisv_text_texture(
        archive,
        raw_lock,
        font_path=font_path,
        expected_chunk_index=1,
        expected_mask_count=1,
        selection_authority=(
            "runtime_hsfc_scenario_chart_alpha_preserving_text_mask"
        ),
        temporary_prefix="srwz-hsfc-scenario-chart-freeze-",
        preview_filename="scenario-chart-runtime.png",
        project_root=project_root,
        live_render=live_render,
        render_snapshot_sink=render_snapshot_sink,
    )
    report["scenario_chart_title_written"] = report["all_labels_written"]
    return output, report


__all__ = [
    "build_hsfc_scenario_chart",
    "build_nisv_library_menu",
    "build_nisv_sound_select",
]
