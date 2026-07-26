"""Fixed title-menu label composition for the verified VT1 texture."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Sequence


TITLE_TEXTURE_WIDTH = 512
TITLE_TEXTURE_HEIGHT = 256
TITLE_LABEL_WIDTH = 128
TITLE_LABEL_HEIGHT = 32
TITLE_LABEL_COUNT = 4
SELECTED_RAMP_BASE = 48
UNSELECTED_RAMP_BASE = 64
RAMP_LEVEL_COUNT = 16


class TitleMenuError(ValueError):
    """A title-menu mask or source texture violates the fixed contract."""


@dataclass(frozen=True)
class TitleMenuEditResult:
    indexes: bytes
    changed_pixel_count: int
    masks: tuple[dict, ...]
    edited_slots: tuple[dict, ...]

    def to_metadata(self) -> dict:
        return {
            "changed_pixel_count": self.changed_pixel_count,
            "masks": list(self.masks),
            "edited_slots": list(self.edited_slots),
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quantize_mask(mask: bytes, ramp_base: int) -> bytes:
    """Quantize an 8-bit grayscale mask into one existing 16-index ramp."""

    source = bytes(mask)
    expected_size = TITLE_LABEL_WIDTH * TITLE_LABEL_HEIGHT
    if len(source) != expected_size:
        raise TitleMenuError(
            f"title mask has {len(source)} bytes, expected {expected_size}"
        )
    if not 0 <= ramp_base <= 256 - RAMP_LEVEL_COUNT:
        raise TitleMenuError("title ramp base is outside one-byte indexes")
    return bytes(
        ramp_base + (value * (RAMP_LEVEL_COUNT - 1) + 127) // 255
        for value in source
    )


def apply_title_menu_masks(
    original_indexes: bytes,
    masks: Sequence[bytes],
) -> TitleMenuEditResult:
    """Replace four labels in both selected and unselected atlas rows."""

    source = bytes(original_indexes)
    expected_size = TITLE_TEXTURE_WIDTH * TITLE_TEXTURE_HEIGHT
    if len(source) != expected_size:
        raise TitleMenuError(
            f"title texture has {len(source)} indexes, "
            f"expected {expected_size}"
        )
    if len(masks) != TITLE_LABEL_COUNT:
        raise TitleMenuError(
            f"title menu requires {TITLE_LABEL_COUNT} masks"
        )

    normalized_masks = tuple(bytes(mask) for mask in masks)
    selected = tuple(
        quantize_mask(mask, SELECTED_RAMP_BASE)
        for mask in normalized_masks
    )
    unselected = tuple(
        quantize_mask(mask, UNSELECTED_RAMP_BASE)
        for mask in normalized_masks
    )
    edited = bytearray(source)
    slots = []
    for state, tiles, row_base in (
        ("selected", selected, 0),
        ("unselected", unselected, TITLE_LABEL_COUNT),
    ):
        for label_index, tile in enumerate(tiles):
            slot_index = row_base + label_index
            y = slot_index * TITLE_LABEL_HEIGHT
            for tile_y in range(TITLE_LABEL_HEIGHT):
                source_start = tile_y * TITLE_LABEL_WIDTH
                target_start = (
                    (y + tile_y) * TITLE_TEXTURE_WIDTH
                )
                edited[
                    target_start : target_start + TITLE_LABEL_WIDTH
                ] = tile[
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

    output = bytes(edited)
    changed_pixel_count = sum(
        before != after for before, after in zip(source, output)
    )
    mask_metadata = tuple(
        {
            "label_index": index,
            "size": len(mask),
            "sha256": _sha256(mask),
            "nonzero_pixel_count": sum(value != 0 for value in mask),
        }
        for index, mask in enumerate(normalized_masks)
    )
    return TitleMenuEditResult(
        indexes=output,
        changed_pixel_count=changed_pixel_count,
        masks=mask_metadata,
        edited_slots=tuple(slots),
    )


__all__ = [
    "RAMP_LEVEL_COUNT",
    "SELECTED_RAMP_BASE",
    "TITLE_LABEL_COUNT",
    "TITLE_LABEL_HEIGHT",
    "TITLE_LABEL_WIDTH",
    "TITLE_TEXTURE_HEIGHT",
    "TITLE_TEXTURE_WIDTH",
    "TitleMenuEditResult",
    "TitleMenuError",
    "UNSELECTED_RAMP_BASE",
    "apply_title_menu_masks",
    "quantize_mask",
]
