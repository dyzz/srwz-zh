"""Deterministic writeback for the localized title-menu texture."""

from __future__ import annotations

import base64
import hashlib
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .tim2 import scan_tim2
from .tim2_writeback import (
    Tim2WritebackError,
    extract_vt1_title_indexes,
    inject_vt1_title_indexes,
)


TITLE_TEXTURE_WIDTH = 512
TITLE_TEXTURE_HEIGHT = 256
TITLE_LABEL_WIDTH = 128
TITLE_LABEL_HEIGHT = 32
TITLE_LABEL_COUNT = 4
SELECTED_RAMP_BASE = 48
UNSELECTED_RAMP_BASE = 64
RAMP_LEVEL_COUNT = 16


class TitleMenuError(ValueError):
    """The title-menu source or frozen localized masks violate the contract."""


@dataclass(frozen=True)
class TitleMenuEditResult:
    data: bytes
    changed_pixel_count: int
    changed_image_byte_count: int
    masks: tuple[dict, ...]
    edited_slots: tuple[dict, ...]

    def to_metadata(self) -> dict:
        return {
            "changed_pixel_count": self.changed_pixel_count,
            "changed_image_byte_count": self.changed_image_byte_count,
            "masks": list(self.masks),
            "edited_slots": list(self.edited_slots),
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _thaw_mask(raw: object) -> bytes:
    if not isinstance(raw, Mapping):
        raise TitleMenuError("title-menu mask snapshot is missing")
    encoded = raw.get("zlib_base64")
    if not isinstance(encoded, str) or not encoded:
        raise TitleMenuError("title-menu mask snapshot is invalid")
    try:
        data = zlib.decompress(base64.b64decode(encoded, validate=True))
    except (ValueError, zlib.error) as error:
        raise TitleMenuError("title-menu mask snapshot cannot be decoded") from error
    if (
        len(data) != TITLE_LABEL_WIDTH * TITLE_LABEL_HEIGHT
        or raw.get("size") != len(data)
        or raw.get("sha256") != _sha256(data)
    ):
        raise TitleMenuError("title-menu mask snapshot drift")
    return data


def quantize_mask(mask: bytes, ramp_base: int) -> bytes:
    source = bytes(mask)
    if len(source) != TITLE_LABEL_WIDTH * TITLE_LABEL_HEIGHT:
        raise TitleMenuError("title-menu mask size is invalid")
    if not 0 <= ramp_base <= 256 - RAMP_LEVEL_COUNT:
        raise TitleMenuError("title-menu ramp is outside one-byte indexes")
    return bytes(
        ramp_base + (value * (RAMP_LEVEL_COUNT - 1) + 127) // 255
        for value in source
    )


def apply_title_menu_masks(
    original_indexes: bytes,
    masks: Sequence[bytes],
) -> tuple[bytes, tuple[dict, ...]]:
    source = bytes(original_indexes)
    if len(source) != TITLE_TEXTURE_WIDTH * TITLE_TEXTURE_HEIGHT:
        raise TitleMenuError("title-menu texture size is invalid")
    if len(masks) != TITLE_LABEL_COUNT:
        raise TitleMenuError("title menu requires four localized masks")
    output = bytearray(source)
    slots = []
    for state, ramp_base, row_base in (
        ("selected", SELECTED_RAMP_BASE, 0),
        ("unselected", UNSELECTED_RAMP_BASE, TITLE_LABEL_COUNT),
    ):
        for label_index, mask in enumerate(masks):
            tile = quantize_mask(mask, ramp_base)
            slot_index = row_base + label_index
            y = slot_index * TITLE_LABEL_HEIGHT
            for tile_y in range(TITLE_LABEL_HEIGHT):
                source_start = tile_y * TITLE_LABEL_WIDTH
                target_start = (y + tile_y) * TITLE_TEXTURE_WIDTH
                output[target_start : target_start + TITLE_LABEL_WIDTH] = tile[
                    source_start : source_start + TITLE_LABEL_WIDTH
                ]
            slots.append(
                {
                    "state": state,
                    "label_index": label_index,
                    "x": 0,
                    "y": y,
                    "width": TITLE_LABEL_WIDTH,
                    "height": TITLE_LABEL_HEIGHT,
                }
            )
    return bytes(output), tuple(slots)


def build_title_menu(decoded_chunk: bytes, contract: dict) -> TitleMenuEditResult:
    """Apply the reviewed masks to VT1 chunk 6 without touching other bytes."""

    if (
        not isinstance(contract, dict)
        or contract.get("profile_id") != "title-menu-zh"
        or contract.get("status") != "reviewed_locked"
    ):
        raise TitleMenuError("title-menu contract identity drift")
    target = contract.get("target")
    raw_masks = contract.get("masks")
    if not isinstance(target, dict) or not isinstance(raw_masks, list):
        raise TitleMenuError("title-menu contract is incomplete")
    source = bytes(decoded_chunk)
    if (
        len(source) != target.get("decoded_size")
        or _sha256(source) != target.get("decoded_sha256")
    ):
        raise TitleMenuError("title-menu decoded chunk drift")
    records = scan_tim2(source)
    record_index = target.get("record_index")
    if not isinstance(record_index, int) or not 0 <= record_index < len(records):
        raise TitleMenuError("title-menu TIM2 record is missing")
    record = records[record_index]
    record_data = source[record.offset : record.end]
    if (
        record.offset != target.get("record_offset")
        or record.size != target.get("record_size")
        or _sha256(record_data) != target.get("record_sha256")
    ):
        raise TitleMenuError("title-menu TIM2 record drift")
    source_indexes = extract_vt1_title_indexes(record_data)
    if _sha256(source_indexes) != target.get("source_indexes_sha256"):
        raise TitleMenuError("title-menu source indexes drift")
    masks = tuple(_thaw_mask(raw) for raw in raw_masks)
    edited_indexes, slots = apply_title_menu_masks(source_indexes, masks)
    changed_pixel_count = sum(
        before != after for before, after in zip(source_indexes, edited_indexes)
    )
    if (
        changed_pixel_count != target.get("expected_changed_pixel_count")
        or _sha256(edited_indexes) != target.get("output_indexes_sha256")
    ):
        raise TitleMenuError("title-menu localized indexes drift")
    try:
        injection = inject_vt1_title_indexes(record_data, edited_indexes)
    except Tim2WritebackError as error:
        raise TitleMenuError(str(error)) from error
    output = source[: record.offset] + injection.data + source[record.end :]
    if len(output) != len(source):
        raise TitleMenuError("title-menu writeback changed the decoded chunk size")
    mask_report = tuple(
        {
            "label_index": index,
            "size": len(mask),
            "sha256": _sha256(mask),
            "nonzero_pixel_count": sum(value != 0 for value in mask),
        }
        for index, mask in enumerate(masks)
    )
    return TitleMenuEditResult(
        data=output,
        changed_pixel_count=changed_pixel_count,
        changed_image_byte_count=injection.changed_image_byte_count,
        masks=mask_report,
        edited_slots=slots,
    )


__all__ = [
    "TitleMenuEditResult",
    "TitleMenuError",
    "apply_title_menu_masks",
    "build_title_menu",
    "quantize_mask",
]
