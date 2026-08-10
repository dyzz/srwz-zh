"""Discover and rewrite title-idle auto-demo overlay name fields."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .text import TextTable, decode_text, encode_text


NAME_FIELD_CAPACITY = 20


class AutoDemoError(ValueError):
    """An auto-demo archive or fixed-field invariant failed."""


@dataclass(frozen=True)
class AutoDemoNameSlot:
    offset: int
    capacity: int
    source_text: str


def parse_auto_demo_seg(seg: bytes, payload_size: int) -> tuple[int, ...]:
    """Return the meaningful little-endian offsets from an OP*.SEG file."""

    if not seg or len(seg) % 4:
        raise AutoDemoError("auto-demo SEG size is invalid")
    raw_offsets = struct.unpack(f"<{len(seg) // 4}I", seg)
    if len(raw_offsets) < 4 or raw_offsets[:3] != (0, 0x10, 0x40450):
        raise AutoDemoError("auto-demo SEG header offsets drifted")
    final_index = max(
        (index for index, value in enumerate(raw_offsets) if value),
        default=-1,
    )
    offsets = (0, *raw_offsets[1 : final_index + 1])
    if (
        offsets[-1] != payload_size
        or any(right <= left for left, right in zip(offsets, offsets[1:]))
    ):
        raise AutoDemoError("auto-demo SEG boundaries drifted")
    return offsets


def _contains_japanese_name_character(text: str) -> bool:
    return any(
        "\u3040" <= character <= "\u30ff"
        or "\u3400" <= character <= "\u9fff"
        for character in text
    )


def discover_auto_demo_name_slots(
    payload: bytes,
    seg: bytes,
) -> list[AutoDemoNameSlot]:
    """Find the fixed 20-byte speaker-name cells in an OP*.BIN payload."""

    offsets = parse_auto_demo_seg(seg, len(payload))
    demo_start = offsets[2]
    demo_end = offsets[-1]
    slots = []
    for offset in range(demo_start + 0x0C, demo_end - NAME_FIELD_CAPACITY + 1, 0x10):
        field = payload[offset : offset + NAME_FIELD_CAPACITY]
        terminator = field.find(b"\0")
        if terminator <= 0 or any(field[terminator:]):
            continue
        try:
            source_text = field[:terminator].decode("cp932")
        except UnicodeDecodeError:
            continue
        if not _contains_japanese_name_character(source_text):
            continue
        slots.append(
            AutoDemoNameSlot(
                offset=offset,
                capacity=NAME_FIELD_CAPACITY,
                source_text=source_text,
            )
        )
    return slots


def rewrite_auto_demo_names(
    payload: bytes,
    seg: bytes,
    translations: dict[str, str],
    table: TextTable,
    *,
    encoding_overrides: dict[str, int],
    output_table: TextTable,
    expected_slot_count: int,
) -> tuple[bytes, list[dict]]:
    """Rewrite every discovered name cell and independently reread it."""

    slots = discover_auto_demo_name_slots(payload, seg)
    if len(slots) != expected_slot_count:
        raise AutoDemoError(
            "auto-demo name-slot count drift: "
            f"expected {expected_slot_count}, found {len(slots)}"
        )
    output = bytearray(payload)
    reports = []
    target_ranges = []
    for slot in slots:
        translation = translations.get(slot.source_text)
        if not isinstance(translation, str) or not translation:
            raise AutoDemoError(
                f"auto-demo name has no canonical translation: {slot.source_text!r}"
            )
        encoded = encode_text(
            translation,
            table,
            overrides=encoding_overrides,
            terminate=True,
        )
        if len(encoded) > slot.capacity:
            raise AutoDemoError(
                f"auto-demo name overflows {slot.capacity} bytes: "
                f"{slot.source_text!r} -> {translation!r} ({len(encoded)} bytes)"
            )
        replacement = encoded + bytes(slot.capacity - len(encoded))
        start = slot.offset
        end = start + slot.capacity
        output[start:end] = replacement
        target_ranges.append((start, end))
        reread = decode_text(bytes(output), start, output_table).text
        if reread != translation:
            raise AutoDemoError(
                f"auto-demo name reread mismatch at 0x{start:X}: "
                f"{reread!r} != {translation!r}"
            )
        reports.append(
            {
                "offset": start,
                "capacity": slot.capacity,
                "source_text": slot.source_text,
                "translation": translation,
                "encoded_size": len(encoded),
                "headroom": slot.capacity - len(encoded),
            }
        )
    for offset, (before, after) in enumerate(zip(payload, output)):
        if before != after and not any(
            start <= offset < end for start, end in target_ranges
        ):
            raise AutoDemoError("auto-demo bytes changed outside name fields")
    if len(output) != len(payload):
        raise AutoDemoError("auto-demo archive size changed")
    return bytes(output), reports
