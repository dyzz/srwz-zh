"""Fail-closed localization for the tutorial title-card VEFF effects.

Stage 186 invokes effects 284..287 through opcode 0x13C8.  VEFF effect N is
stored in archive chunk N+1, so the four runtime copies live in chunks
285..288.  Each copy embeds the same four-picture PSMT8 TIM2 record.  This
writer changes only the indexed pixels inside declared text rectangles and
keeps the shared CLUT, TIM2 metadata, event data, archive offsets, and every
non-target chunk byte-exact.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Mapping

from .codec import decode_production, reencode_changed_suffix
from .imagemagick import (
    imagemagick_version,
    render_grayscale_text_mask,
    require_imagemagick,
)
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .psmt4 import swizzle_psmt4, unswizzle_psmt4
from .stage_formations import STAGE_OFFSET_SPEC
from .tim2 import scan_tim2
from .tim2_writeback import swizzle_psmt8, unswizzle_psmt8


class VeffTutorialTitleError(ValueError):
    """The tutorial effect binding, source, or render contract drifted."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise VeffTutorialTitleError(f"{label} must be an integer")
    return value


def _rectangle(value: object, label: str) -> tuple[int, int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    ):
        raise VeffTutorialTitleError(f"{label} must be a four-integer rectangle")
    x, y, width, height = value
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise VeffTutorialTitleError(f"{label} has invalid geometry")
    return x, y, width, height


def _picture_index_set(value: object, label: str) -> set[int]:
    if (
        not isinstance(value, list)
        or not all(isinstance(index, int) and not isinstance(index, bool) for index in value)
        or len(set(value)) != len(value)
        or any(not 0 <= index < 4 for index in value)
    ):
        raise VeffTutorialTitleError(f"{label} must be unique picture indexes 0..3")
    return set(value)


def _csm1_palette_offset(index: int) -> int:
    return (index & 0xE7) | ((index & 0x08) << 1) | ((index & 0x10) >> 1)


def _palette_color(palette: bytes, index: int) -> tuple[int, int, int, int]:
    offset = _csm1_palette_offset(index) * 4
    if offset + 4 > len(palette):
        raise VeffTutorialTitleError("tutorial palette index exceeds shared CLUT")
    return tuple(palette[offset : offset + 4])


def _coverage_ramp(
    palette: bytes,
    background_index: int,
    raw_indexes: object,
) -> tuple[int, ...]:
    """Expand a CLUT-cycle-safe foreground ramp to 256 mask levels.

    The tutorial effect cycles through four 256-color CLUT banks.  Selecting
    indexes by looking only at bank 0 is unsafe: several apparently useful
    grayscale indexes become opaque black in banks 1 and 2.  The contract
    therefore names a short, audited ramp whose colors stay light and opaque
    in every runtime bank.
    """

    if (
        not isinstance(raw_indexes, list)
        or len(raw_indexes) < 2
        or not all(isinstance(index, int) and not isinstance(index, bool) for index in raw_indexes)
        or len(set(raw_indexes)) != len(raw_indexes)
    ):
        raise VeffTutorialTitleError("tutorial safe coverage ramp is invalid")
    indexes = tuple(raw_indexes)
    if background_index in indexes or any(not 0 <= index <= 0xFF for index in indexes):
        raise VeffTutorialTitleError("tutorial safe coverage ramp index is invalid")
    if len(palette) != 4 * 256 * 4:
        raise VeffTutorialTitleError("tutorial shared palette bank inventory drift")
    for index in indexes:
        for bank in range(4):
            offset = (bank * 256 + _csm1_palette_offset(index)) * 4
            red, green, blue, alpha = palette[offset : offset + 4]
            if alpha != 0x80 or min(red, green, blue) < 180:
                raise VeffTutorialTitleError(
                    "tutorial coverage ramp is not light and opaque in every CLUT bank: "
                    f"index=0x{index:02X} bank={bank} rgba={(red, green, blue, alpha)!r}"
                )

    ramp = [background_index]
    for coverage in range(1, 256):
        ordinal = min(len(indexes) - 1, coverage * len(indexes) // 256)
        ramp.append(indexes[ordinal])
    return tuple(ramp)


def _mask_ink_bounds(mask: bytes, width: int, height: int) -> tuple[int, int, int, int]:
    points = [index for index, value in enumerate(mask) if value]
    if not points:
        raise VeffTutorialTitleError("tutorial rendered mask has no ink")
    xs = [index % width for index in points]
    ys = [index // width for index in points]
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _resample_mask(
    source: bytes,
    source_width: int,
    source_height: int,
    output_width: int,
    output_height: int,
) -> bytes:
    """Deterministically bilinear-resample a grayscale mask."""

    if min(source_width, source_height, output_width, output_height) <= 0:
        raise VeffTutorialTitleError("tutorial fitted-mask geometry is invalid")
    if len(source) != source_width * source_height:
        raise VeffTutorialTitleError("tutorial fitted-mask source size drift")
    output = bytearray(output_width * output_height)
    x_denominator = max(1, output_width - 1)
    y_denominator = max(1, output_height - 1)
    for output_y in range(output_height):
        source_y_numerator = output_y * max(0, source_height - 1)
        source_y0, y_fraction = divmod(source_y_numerator, y_denominator)
        source_y1 = min(source_height - 1, source_y0 + 1)
        for output_x in range(output_width):
            source_x_numerator = output_x * max(0, source_width - 1)
            source_x0, x_fraction = divmod(source_x_numerator, x_denominator)
            source_x1 = min(source_width - 1, source_x0 + 1)
            top = (
                source[source_y0 * source_width + source_x0]
                * (x_denominator - x_fraction)
                + source[source_y0 * source_width + source_x1] * x_fraction
            )
            bottom = (
                source[source_y1 * source_width + source_x0]
                * (x_denominator - x_fraction)
                + source[source_y1 * source_width + source_x1] * x_fraction
            )
            value = (
                top * (y_denominator - y_fraction)
                + bottom * y_fraction
                + x_denominator * y_denominator // 2
            ) // (x_denominator * y_denominator)
            output[output_y * output_width + output_x] = value
    return bytes(output)


def _clear_background_record(
    decoded: bytes,
    record_index: int,
    pictures_contract: list,
    source_hashes: list,
    output_hashes: list,
    background_index: int,
    clear_picture_indices: set[int],
) -> tuple[bytes, list[dict]]:
    """Remove the stock animated title underlay from the PSMT4 layer."""

    records = scan_tim2(decoded)
    if not 0 <= record_index < len(records):
        raise VeffTutorialTitleError("tutorial background TIM2 record is missing")
    record = records[record_index]
    if not (
        len(record.pictures)
        == len(pictures_contract)
        == len(source_hashes)
        == len(output_hashes)
        == 4
    ):
        raise VeffTutorialTitleError("tutorial background picture inventory drift")

    output = bytearray(decoded)
    reports = []
    owned_ranges = []
    for picture_index, (picture, contract, source_hash, output_hash) in enumerate(
        zip(record.pictures, pictures_contract, source_hashes, output_hashes)
    ):
        if not isinstance(contract, Mapping) or contract.get(
            "picture_index"
        ) != picture_index:
            raise VeffTutorialTitleError(
                "tutorial background picture contract ordering drift"
            )
        if (
            picture.width != 512
            or picture.height != 256
            or picture.image_type != 4
            or picture.image_size != 512 * 256 // 2
            or picture.clut_type != 3
            or (picture_index == 0 and picture.clut_size != 256)
            or (
                picture_index > 0
                and (picture.clut_size != 0 or not picture.uses_shared_clut)
            )
        ):
            raise VeffTutorialTitleError(
                f"tutorial background picture {picture_index} layout drift"
            )
        image_start = picture.offset + picture.header_size
        image_end = image_start + picture.image_size
        logical_source = unswizzle_psmt4(
            decoded[image_start:image_end], picture.width, picture.height
        )
        if _sha256(logical_source) != source_hash:
            raise VeffTutorialTitleError(
                f"tutorial background picture {picture_index} source lock drift"
            )
        if picture_index not in clear_picture_indices:
            if output_hash != source_hash:
                raise VeffTutorialTitleError(
                    "tutorial preserved background output lock differs from source"
                )
            reports.append(
                {
                    "picture_index": picture_index,
                    "source_logical_sha256": source_hash,
                    "output_logical_sha256": source_hash,
                    "changed_logical_pixel_count": 0,
                    "stock_title_underlay_removed": False,
                    "preserved_original": True,
                }
            )
            continue
        logical = bytearray(logical_source)
        x, y, width, height = _rectangle(
            contract.get("clear_rect"),
            f"tutorial background picture {picture_index} clear",
        )
        if x + width > picture.width or y + height > picture.height:
            raise VeffTutorialTitleError(
                "tutorial background clear rectangle exceeds picture"
            )
        for row in range(y, y + height):
            start = row * picture.width + x
            logical[start : start + width] = bytes([background_index]) * width
        logical_bytes = bytes(logical)
        if _sha256(logical_bytes) != output_hash:
            raise VeffTutorialTitleError(
                f"tutorial background picture {picture_index} output drift: "
                f"sha256={_sha256(logical_bytes)}"
            )
        packed = swizzle_psmt4(logical_bytes, picture.width, picture.height)
        if unswizzle_psmt4(packed, picture.width, picture.height) != logical_bytes:
            raise VeffTutorialTitleError("tutorial background PSMT4 round trip failed")
        output[image_start:image_end] = packed
        owned_ranges.append((image_start, image_end))
        reports.append(
            {
                "picture_index": picture_index,
                "clear_rect": [x, y, width, height],
                "source_logical_sha256": source_hash,
                "output_logical_sha256": output_hash,
                "changed_logical_pixel_count": sum(
                    before != after
                    for before, after in zip(logical_source, logical_bytes)
                ),
                "stock_title_underlay_removed": True,
                "preserved_original": False,
            }
        )

    output_bytes = bytes(output)
    if scan_tim2(output_bytes) != records:
        raise VeffTutorialTitleError("tutorial background TIM2 metadata changed")
    for offset, (before, after) in enumerate(zip(decoded, output_bytes)):
        if before != after and not any(start <= offset < end for start, end in owned_ranges):
            raise VeffTutorialTitleError(
                "tutorial background write escaped indexed images"
            )
    return output_bytes, reports


def _render_record(
    decoded: bytes,
    record_index: int,
    pictures_contract: list,
    output_hashes: list,
    render: Mapping[str, object],
    font_path: Path,
    localized_picture_indices: set[int],
) -> tuple[bytes, list[dict]]:
    records = scan_tim2(decoded)
    if not 0 <= record_index < len(records):
        raise VeffTutorialTitleError("tutorial TIM2 record is missing")
    record = records[record_index]
    if (
        len(record.pictures) != 4
        or len(pictures_contract) != 4
        or len(output_hashes) != 4
    ):
        raise VeffTutorialTitleError("tutorial TIM2 picture inventory drift")

    executable = require_imagemagick()
    version = imagemagick_version(executable)
    if version != render.get("imagemagick_version"):
        raise VeffTutorialTitleError(f"ImageMagick version drift: {version!r}")
    point_policy = render.get("point_policy")
    if point_policy != "centered-harmonyos-mask-to-existing-csm1-ramp":
        raise VeffTutorialTitleError("tutorial title render policy drift")
    supersample = _integer(render.get("supersample_factor"), "supersample factor")
    background_index = _integer(render.get("background_index"), "background index")

    first = record.pictures[0]
    first_image_start = first.offset + first.header_size
    palette_start = first_image_start + first.image_size
    palette = decoded[palette_start : palette_start + first.clut_size]
    if (
        first.clut_size != 4096
        or first.clut_color_count != 1024
        or _sha256(palette) != render.get("source_palette_sha256")
    ):
        raise VeffTutorialTitleError("tutorial shared palette lock drift")

    output = bytearray(decoded)
    picture_reports = []
    owned_ranges = []
    for picture_index, (picture, contract, output_hash) in enumerate(
        zip(record.pictures, pictures_contract, output_hashes)
    ):
        if not isinstance(contract, Mapping) or contract.get("picture_index") != picture_index:
            raise VeffTutorialTitleError("tutorial picture contract ordering drift")
        if (
            picture.width != 512
            or picture.height != 256
            or picture.image_type != 5
            or picture.image_size != 512 * 256
            or picture.clut_type != 3
            or (picture_index == 0 and picture.clut_size != 4096)
            or (picture_index > 0 and (picture.clut_size != 0 or not picture.uses_shared_clut))
        ):
            raise VeffTutorialTitleError(
                f"tutorial picture {picture_index} layout drift"
            )
        image_start = picture.offset + picture.header_size
        image_end = image_start + picture.image_size
        logical_source = unswizzle_psmt8(
            decoded[image_start:image_end], picture.width, picture.height
        )
        if _sha256(logical_source) != contract.get("source_logical_sha256"):
            raise VeffTutorialTitleError(
                f"tutorial picture {picture_index} source lock drift"
            )
        if picture_index not in localized_picture_indices:
            if output_hash != contract.get("source_logical_sha256"):
                raise VeffTutorialTitleError(
                    "tutorial preserved foreground output lock differs from source"
                )
            picture_reports.append(
                {
                    "picture_index": picture_index,
                    "source_text": contract.get("source_text"),
                    "translation": contract.get("translation"),
                    "source_logical_sha256": contract["source_logical_sha256"],
                    "output_logical_sha256": output_hash,
                    "changed_logical_pixel_count": 0,
                    "preserved_original": True,
                    "translated_reread_exact": True,
                }
            )
            continue
        logical = bytearray(logical_source)
        clear_x, clear_y, clear_width, clear_height = _rectangle(
            contract.get("clear_rect"), f"tutorial picture {picture_index} clear"
        )
        if clear_x + clear_width > picture.width or clear_y + clear_height > picture.height:
            raise VeffTutorialTitleError("tutorial clear rectangle exceeds picture")
        for y in range(clear_y, clear_y + clear_height):
            start = y * picture.width + clear_x
            logical[start : start + clear_width] = bytes([background_index]) * clear_width

        ramp = _coverage_ramp(
            palette,
            background_index,
            render.get("coverage_ramp_indices"),
        )
        raw_segments = contract.get("segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            raise VeffTutorialTitleError("tutorial title segments are missing")
        segment_reports = []
        for segment_index, segment in enumerate(raw_segments):
            if not isinstance(segment, Mapping):
                raise VeffTutorialTitleError("tutorial title segment is malformed")
            text = segment.get("text")
            if not isinstance(text, str) or not text:
                raise VeffTutorialTitleError("tutorial title segment text is invalid")
            x, y, width, height = _rectangle(
                segment.get("rect"),
                f"tutorial picture {picture_index} segment {segment_index}",
            )
            point_size = _integer(segment.get("point_size"), "tutorial point size")
            if x + width > picture.width or y + height > picture.height:
                raise VeffTutorialTitleError("tutorial title segment exceeds picture")
            if not (
                clear_x <= x
                and clear_y <= y
                and x + width <= clear_x + clear_width
                and y + height <= clear_y + clear_height
            ):
                raise VeffTutorialTitleError("tutorial title segment escapes clear ownership")
            mask = render_grayscale_text_mask(
                executable,
                font_path,
                text,
                width=width,
                height=height,
                point_size=point_size,
                stroke_gray="white",
                stroke_width=0,
                supersample_factor=supersample,
            )
            if _sha256(mask) != segment.get("mask_sha256"):
                raise VeffTutorialTitleError(
                    f"tutorial frozen mask drift: picture={picture_index} "
                    f"segment={segment_index} sha256={_sha256(mask)}"
                )
            raw_fit_rect = segment.get("fit_ink_rect")
            fitted_mask = mask
            output_x, output_y, output_width, output_height = x, y, width, height
            if raw_fit_rect is not None:
                output_x, output_y, output_width, output_height = _rectangle(
                    raw_fit_rect,
                    f"tutorial picture {picture_index} segment {segment_index} fitted ink",
                )
                if (
                    output_x + output_width > picture.width
                    or output_y + output_height > picture.height
                    or not (
                        clear_x <= output_x
                        and clear_y <= output_y
                        and output_x + output_width <= clear_x + clear_width
                        and output_y + output_height <= clear_y + clear_height
                    )
                ):
                    raise VeffTutorialTitleError(
                        "tutorial fitted ink rectangle escapes clear ownership"
                    )
                ink_x0, ink_y0, ink_x1, ink_y1 = _mask_ink_bounds(
                    mask, width, height
                )
                source_width = ink_x1 - ink_x0
                source_height = ink_y1 - ink_y0
                source_ink = bytearray(source_width * source_height)
                for source_y in range(source_height):
                    source_start = (ink_y0 + source_y) * width + ink_x0
                    destination_start = source_y * source_width
                    source_ink[destination_start : destination_start + source_width] = (
                        mask[source_start : source_start + source_width]
                    )
                fitted_mask = _resample_mask(
                    bytes(source_ink),
                    source_width,
                    source_height,
                    output_width,
                    output_height,
                )
                if _sha256(fitted_mask) != segment.get("fitted_mask_sha256"):
                    raise VeffTutorialTitleError(
                        f"tutorial frozen fitted mask drift: picture={picture_index} "
                        f"segment={segment_index} sha256={_sha256(fitted_mask)}"
                    )
            for row in range(output_height):
                logical_start = (output_y + row) * picture.width + output_x
                mask_start = row * output_width
                for column, coverage in enumerate(
                    fitted_mask[mask_start : mask_start + output_width]
                ):
                    if coverage:
                        logical[logical_start + column] = ramp[coverage]
            segment_reports.append(
                {
                    "text": text,
                    "rect": [x, y, width, height],
                    "point_size": point_size,
                    "mask_sha256": _sha256(mask),
                    "fit_ink_rect": (
                        [output_x, output_y, output_width, output_height]
                        if raw_fit_rect is not None
                        else None
                    ),
                    "fitted_mask_sha256": (
                        _sha256(fitted_mask) if raw_fit_rect is not None else None
                    ),
                    "ink_pixel_count": sum(bool(value) for value in fitted_mask),
                }
            )
        logical_bytes = bytes(logical)
        if _sha256(logical_bytes) != output_hash:
            raise VeffTutorialTitleError(
                f"tutorial picture {picture_index} output drift: "
                f"sha256={_sha256(logical_bytes)}"
            )
        packed = swizzle_psmt8(logical_bytes, picture.width, picture.height)
        if unswizzle_psmt8(packed, picture.width, picture.height) != logical_bytes:
            raise VeffTutorialTitleError("tutorial PSMT8 round trip failed")
        output[image_start:image_end] = packed
        owned_ranges.append((image_start, image_end))
        picture_reports.append(
            {
                "picture_index": picture_index,
                "source_text": contract.get("source_text"),
                "translation": contract.get("translation"),
                "clear_rect": [clear_x, clear_y, clear_width, clear_height],
                "segments": segment_reports,
                "source_logical_sha256": contract["source_logical_sha256"],
                "output_logical_sha256": output_hash,
                "changed_logical_pixel_count": sum(
                    before != after
                    for before, after in zip(logical_source, logical_bytes)
                ),
                "preserved_original": False,
                "translated_reread_exact": True,
            }
        )

    output_bytes = bytes(output)
    if scan_tim2(output_bytes) != records:
        raise VeffTutorialTitleError("tutorial TIM2 metadata changed")
    for offset, (before, after) in enumerate(zip(decoded, output_bytes)):
        if before != after and not any(start <= offset < end for start, end in owned_ranges):
            raise VeffTutorialTitleError("tutorial write escaped indexed images")
    return output_bytes, picture_reports


def audit_tutorial_effect_binding(
    stage: bytes,
    hb: bytes,
    contract: Mapping[str, object],
) -> dict:
    """Prove that the tutorial stage calls exactly the four localized effects."""

    stage_index = _integer(contract.get("stage_index"), "tutorial stage index")
    opcode = _integer(contract.get("opcode"), "tutorial effect opcode")
    raw_commands = contract.get("commands")
    if not isinstance(raw_commands, list) or not raw_commands:
        raise VeffTutorialTitleError("tutorial effect command inventory is missing")
    offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(stage))
    if not 0 <= stage_index < len(offsets) - 1:
        raise VeffTutorialTitleError("tutorial stage is outside STAGE archive")
    stored = stage[offsets[stage_index] : offsets[stage_index + 1]]
    decoded = decode_production(stored)
    if any(stored[decoded.consumed :]):
        raise VeffTutorialTitleError("tutorial stage compressed tail is nonzero")
    needle = struct.pack("<I", opcode)
    observed = []
    cursor = 0
    while True:
        cursor = decoded.output.find(needle, cursor)
        if cursor < 0:
            break
        if cursor + 16 > len(decoded.output):
            raise VeffTutorialTitleError("tutorial effect command is truncated")
        values = struct.unpack_from("<IIII", decoded.output, cursor)
        observed.append(
            {
                "decoded_offset": cursor,
                "effect_id": values[1],
                "duration": values[2],
                "parameter": values[3],
            }
        )
        cursor += 4
    if observed != raw_commands:
        raise VeffTutorialTitleError(
            f"tutorial effect command binding drift: {observed!r}"
        )
    effect_ids = sorted({item["effect_id"] for item in observed})
    if effect_ids != contract.get("expected_effect_ids"):
        raise VeffTutorialTitleError("tutorial effect-id coverage drift")
    return {
        "stage_index": stage_index,
        "opcode": f"0x{opcode:04X}",
        "command_count": len(observed),
        "effect_ids": effect_ids,
        "commands": observed,
        "all_four_effects_referenced": effect_ids == [284, 285, 286, 287],
    }


def build_veff_tutorial_titles(
    source_archive: bytes,
    source_slps: bytes,
    font_path: Path,
    contract: Mapping[str, object],
    *,
    archive_payload: bytes | None = None,
) -> tuple[bytes, dict]:
    """Localize only the title pictures used by each tutorial effect.

    The fourth effect is the stock mission-clear card and is preserved as one
    byte-exact archive allocation.
    """

    archive = source_archive if archive_payload is None else archive_payload
    if len(archive) != len(source_archive):
        raise VeffTutorialTitleError("tutorial VEFF archive size drift")
    archive_spec = contract.get("archive")
    render = contract.get("render")
    targets = contract.get("targets")
    if not isinstance(archive_spec, Mapping) or not isinstance(render, Mapping) or not isinstance(targets, list):
        raise VeffTutorialTitleError("tutorial title contract is incomplete")
    if (
        archive_spec.get("storage") != "srwz_stream"
        or archive_spec.get("alignment") != 16
        or len(targets) != 4
    ):
        raise VeffTutorialTitleError("tutorial VEFF archive policy drift")
    try:
        offset_spec = ExecutableOffsetSpec(
            name=str(archive_spec["name"]),
            member=str(archive_spec["member"]),
            table_start=int(str(archive_spec["table_start"]), 0),
            table_end=int(str(archive_spec["table_end"]), 0),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise VeffTutorialTitleError("tutorial VEFF offset spec is invalid") from error
    offsets = read_executable_archive_offsets(source_slps, offset_spec, len(archive))
    record_index = _integer(contract.get("record_index"), "tutorial TIM2 record index")
    record_size = _integer(contract.get("record_size"), "tutorial TIM2 record size")
    record_sha256 = contract.get("record_sha256")
    pictures_contract = contract.get("pictures")
    background_record_index = _integer(
        contract.get("background_record_index"),
        "tutorial background TIM2 record index",
    )
    background_record_size = _integer(
        contract.get("background_record_size"),
        "tutorial background TIM2 record size",
    )
    background_pictures_contract = contract.get("background_pictures")
    if not isinstance(pictures_contract, list) or not isinstance(
        background_pictures_contract, list
    ):
        raise VeffTutorialTitleError("tutorial picture contract is missing")
    if background_record_index == record_index:
        raise VeffTutorialTitleError("tutorial foreground/background records collide")

    font = font_path.read_bytes()
    if len(font) != render.get("font_size") or _sha256(font) != render.get("font_sha256"):
        raise VeffTutorialTitleError("tutorial title font lock drift")

    output = bytearray(archive)
    target_reports = []
    owned_archive_ranges = []
    for ordinal, target in enumerate(targets):
        if not isinstance(target, Mapping):
            raise VeffTutorialTitleError("tutorial target is malformed")
        effect_id = _integer(target.get("effect_id"), "tutorial effect id")
        chunk_index = _integer(target.get("chunk_index"), "tutorial chunk index")
        if effect_id != 284 + ordinal or chunk_index != effect_id + 1:
            raise VeffTutorialTitleError("tutorial effect-to-chunk mapping drift")
        start, end = offsets[chunk_index : chunk_index + 2]
        stored = archive[start:end]
        if (
            start != target.get("stored_start")
            or end != target.get("stored_end")
            or len(stored) != target.get("stored_size")
            or _sha256(stored) != target.get("stored_sha256")
        ):
            raise VeffTutorialTitleError(f"tutorial chunk {chunk_index} source lock drift")
        decoded = decode_production(stored)
        if (
            decoded.consumed != target.get("stored_consumed")
            or any(stored[decoded.consumed :])
            or len(decoded.output) != target.get("decoded_size")
            or _sha256(decoded.output) != target.get("decoded_sha256")
        ):
            raise VeffTutorialTitleError(f"tutorial chunk {chunk_index} decoded lock drift")
        records = scan_tim2(decoded.output)
        if not (
            0 <= record_index < len(records)
            and 0 <= background_record_index < len(records)
        ):
            raise VeffTutorialTitleError("tutorial TIM2 record is missing")
        record = records[record_index]
        background_record = records[background_record_index]
        if (
            record.size != record_size
            or _sha256(decoded.output[record.offset : record.end]) != record_sha256
        ):
            raise VeffTutorialTitleError("tutorial shared TIM2 record lock drift")
        if (
            background_record.size != background_record_size
            or _sha256(
                decoded.output[background_record.offset : background_record.end]
            )
            != target.get("background_record_sha256")
        ):
            raise VeffTutorialTitleError(
                "tutorial shared background TIM2 record lock drift"
            )
        background_source_hashes = target.get("background_source_logical_sha256")
        background_output_hashes = target.get("background_output_logical_sha256")
        if not isinstance(background_source_hashes, list) or not isinstance(
            background_output_hashes, list
        ):
            raise VeffTutorialTitleError(
                "tutorial target background logical locks are missing"
            )
        foreground_output_hashes = target.get("foreground_output_logical_sha256")
        if not isinstance(foreground_output_hashes, list):
            raise VeffTutorialTitleError(
                "tutorial target foreground logical locks are missing"
            )
        preserved_original = target.get("preserve_original", False)
        if not isinstance(preserved_original, bool):
            raise VeffTutorialTitleError("tutorial target preserve policy is invalid")
        localized_picture_indices = _picture_index_set(
            target.get("localized_picture_indices", []),
            "tutorial localized picture indexes",
        )
        clear_background_picture_indices = _picture_index_set(
            target.get("clear_background_picture_indices", []),
            "tutorial cleared background picture indexes",
        )
        if preserved_original and (
            localized_picture_indices or clear_background_picture_indices
        ):
            raise VeffTutorialTitleError(
                "tutorial preserved target cannot declare localized pictures"
            )
        modified, background_picture_reports = _clear_background_record(
            decoded.output,
            background_record_index,
            background_pictures_contract,
            background_source_hashes,
            background_output_hashes,
            _integer(render.get("background_index"), "background index"),
            clear_background_picture_indices,
        )
        modified, picture_reports = _render_record(
            modified,
            record_index,
            pictures_contract,
            foreground_output_hashes,
            render,
            font_path,
            localized_picture_indices,
        )
        if preserved_original:
            if modified != decoded.output:
                raise VeffTutorialTitleError("tutorial preserved target decoded bytes changed")
            encoded = stored[: decoded.consumed]
            padded = stored
        else:
            encoded = reencode_changed_suffix(
                stored[: decoded.consumed],
                modified,
                strategy="rust-fit",
                min_match_length=2,
                max_match_chain=16384,
                lazy_matching=False,
                max_output_size=len(stored),
                original_result=decoded,
            )
            padded = encoded + bytes(len(stored) - len(encoded))
        if (
            len(encoded) != target.get("output_encoded_size")
            or _sha256(encoded) != target.get("output_encoded_sha256")
            or _sha256(modified) != target.get("output_decoded_sha256")
        ):
            raise VeffTutorialTitleError(
                f"tutorial chunk {chunk_index} output lock drift: "
                f"size={len(encoded)} encoded={_sha256(encoded)} "
                f"decoded={_sha256(modified)}"
            )
        reread = decode_production(padded)
        if reread.output != modified or any(padded[reread.consumed :]):
            raise VeffTutorialTitleError("tutorial compressed reread drift")
        output[start:end] = padded
        owned_archive_ranges.append((start, end))
        target_reports.append(
            {
                "effect_id": effect_id,
                "chunk_index": chunk_index,
                "record_offset": record.offset,
                "background_record_offset": background_record.offset,
                "source_allocation_size": len(stored),
                "output_encoded_size": len(encoded),
                "compressed_headroom": len(stored) - len(encoded),
                "pictures": picture_reports,
                "background_pictures": background_picture_reports,
                "localized_picture_indices": sorted(localized_picture_indices),
                "clear_background_picture_indices": sorted(
                    clear_background_picture_indices
                ),
                "preserved_original": preserved_original,
                "source_allocation_preserved_byte_exact": (
                    padded == stored if preserved_original else False
                ),
                "translated_reread_exact": True,
            }
        )
    output_bytes = bytes(output)
    if len(output_bytes) != len(archive):
        raise VeffTutorialTitleError("tutorial VEFF archive size changed")
    for index, (before, after) in enumerate(zip(archive, output_bytes)):
        if before != after and not any(start <= index < end for start, end in owned_archive_ranges):
            raise VeffTutorialTitleError("tutorial write escaped target chunks")
    if read_executable_archive_offsets(source_slps, offset_spec, len(output_bytes)) != offsets:
        raise VeffTutorialTitleError("tutorial VEFF archive offsets changed")
    return output_bytes, {
        "member": archive_spec["member"],
        "effect_ids": [item["effect_id"] for item in target_reports],
        "chunk_indices": [item["chunk_index"] for item in target_reports],
        "localized_effect_count": sum(
            not item["preserved_original"] for item in target_reports
        ),
        "preserved_effect_count": sum(
            item["preserved_original"] for item in target_reports
        ),
        "localized_picture_count": sum(
            not picture["preserved_original"]
            for item in target_reports
            for picture in item["pictures"]
        ),
        "preserved_picture_count": sum(
            picture["preserved_original"]
            for item in target_reports
            for picture in item["pictures"]
        ),
        "localized_background_picture_count": sum(
            not picture["preserved_original"]
            for item in target_reports
            for picture in item["background_pictures"]
        ),
        "preserved_background_picture_count": sum(
            picture["preserved_original"]
            for item in target_reports
            for picture in item["background_pictures"]
        ),
        "targets": target_reports,
        "font_sha256": _sha256(font),
        "imagemagick_version": render["imagemagick_version"],
        "coverage_ramp_indices": render["coverage_ramp_indices"],
        "coverage_ramp_safe_across_all_four_clut_banks": True,
        "codec_strategy": "rust-fit",
        "archive_size_preserved": True,
        "archive_offsets_preserved": True,
        "non_target_chunks_preserved_byte_exact": True,
        "tim2_metadata_preserved": True,
        "localized_title_underlays_removed": True,
        "mission_clear_preserved_byte_exact": target_reports[-1][
            "source_allocation_preserved_byte_exact"
        ],
        "palette_preserved_byte_exact": True,
        "translated_reread_exact": True,
    }


__all__ = [
    "VeffTutorialTitleError",
    "audit_tutorial_effect_binding",
    "build_veff_tutorial_titles",
]
