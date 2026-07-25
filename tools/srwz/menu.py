"""Read-only parser for SRWZ executable and COMPDATA menu text."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Mapping, Optional

from .text import TextTable, decode_text


class MenuParseError(ValueError):
    """A menu descriptor or pointer references invalid input."""

    def __init__(self, message: str, *, offset: Optional[int] = None):
        self.offset = offset
        location = "" if offset is None else f" at input offset 0x{offset:X}"
        super().__init__(f"{message}{location}")


@dataclass(frozen=True)
class MenuTextEntry:
    entry_id: str
    section: str
    ordinal: int
    text: str
    pointer_offsets: tuple
    target_offsets: tuple
    embedded_hi: tuple = ()
    embedded_lo: tuple = ()
    unknown_code_count: int = 0

    def to_mapping(self) -> dict:
        return {
            "id": self.entry_id,
            "section": self.section,
            "ordinal": self.ordinal,
            "text": self.text,
            "pointer_offsets": list(self.pointer_offsets),
            "target_offsets": list(self.target_offsets),
            "embedded_hi": list(self.embedded_hi),
            "embedded_lo": list(self.embedded_lo),
            "unknown_code_count": self.unknown_code_count,
        }


@dataclass(frozen=True)
class MenuParseResult:
    friendly_name: str
    source_size: int
    base_offset: int
    entries: tuple
    section_names: tuple

    @property
    def unknown_code_count(self) -> int:
        return sum(entry.unknown_code_count for entry in self.entries)

    def to_mapping(self) -> dict:
        return {
            "friendly_name": self.friendly_name,
            "source_size": self.source_size,
            "base_offset": self.base_offset,
            "section_names": list(self.section_names),
            "entry_count": len(self.entries),
            "unknown_code_count": self.unknown_code_count,
            "entries": [entry.to_mapping() for entry in self.entries],
        }


def _require_span(data: bytes, offset: int, size: int, context: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise MenuParseError(f"{context} is outside the input", offset=offset)


def _u16(data: bytes, offset: int, context: str) -> int:
    _require_span(data, offset, 2, context)
    return struct.unpack_from("<H", data, offset)[0]


def _i16(data: bytes, offset: int, context: str) -> int:
    _require_span(data, offset, 2, context)
    return struct.unpack_from("<h", data, offset)[0]


def _u32(data: bytes, offset: int, context: str) -> int:
    _require_span(data, offset, 4, context)
    return struct.unpack_from("<I", data, offset)[0]


def _number(value, context: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise MenuParseError(f"{context} must be an integer")


def _style_steps(style: str) -> tuple:
    if not isinstance(style, str) or not style:
        raise MenuParseError("pointer style must be a non-empty string")
    tokens = tuple(
        token
        for token in re.split(r"([PT])|(\d+)", style)
        if token
    )
    if not tokens or any(
        token not in ("P", "T") and not token.isdigit()
        for token in tokens
    ):
        raise MenuParseError(f"invalid pointer style: {style!r}")
    return tokens


def _regular_pointers(
    data: bytes,
    start: int,
    end: int,
    base_offset: int,
    style: str,
) -> tuple:
    if not 0 <= start <= end <= len(data):
        raise MenuParseError("pointer range is outside the input", offset=start)
    pointer_offsets = []
    target_offsets = []
    position = start
    steps = _style_steps(style)
    while position < end:
        cycle_start = position
        for step in steps:
            if step == "P":
                pointer_offset = position
                value = _u32(data, position, "menu pointer")
                position += 4
                target = value - base_offset
                if pointer_offset < end and target > 0:
                    if target >= len(data):
                        raise MenuParseError(
                            "menu pointer target is outside the input",
                            offset=pointer_offset,
                        )
                    pointer_offsets.append(pointer_offset)
                    target_offsets.append(target)
            elif step == "T":
                if position >= end:
                    break
                pointer_offsets.append(position)
                target_offsets.append(position)
            else:
                skip = int(step)
                _require_span(data, position, skip, "pointer style skip")
                position += skip
        if position <= cycle_start:
            raise MenuParseError("pointer style made no progress", offset=position)
    return tuple(pointer_offsets), tuple(target_offsets)


def _standalone_pointers(
    data: bytes,
    values,
    base_offset: int,
) -> tuple:
    pointer_offsets = []
    target_offsets = []
    for raw_offset in values:
        pointer_offset = _number(raw_offset, "standalone pointer offset")
        value = _u32(data, pointer_offset, "standalone menu pointer")
        target = value - base_offset
        if not 0 <= target < len(data):
            raise MenuParseError(
                "standalone menu pointer target is outside the input",
                offset=pointer_offset,
            )
        pointer_offsets.append(pointer_offset)
        target_offsets.append(target)
    return tuple(pointer_offsets), tuple(target_offsets)


def _embedded_targets(
    data: bytes,
    descriptor: Mapping[str, object],
    base_offset: int,
) -> dict:
    by_section = {}
    raw_embedded = descriptor.get("embedded", {})
    if not isinstance(raw_embedded, dict):
        raise MenuParseError("embedded descriptor must be an object")
    for section, pairs in raw_embedded.items():
        if not isinstance(section, str) or not isinstance(pairs, list):
            raise MenuParseError("embedded section descriptor is malformed")
        section_targets = by_section.setdefault(section, {})
        for pair in pairs:
            if not isinstance(pair, dict):
                raise MenuParseError("embedded pointer pair must be an object")
            high_values = tuple(pair.get("HI", ()))
            low_values = tuple(pair.get("LO", ()))
            if not high_values or not low_values:
                raise MenuParseError("embedded pointer pair needs HI and LO offsets")
            high_offset = _number(high_values[0], "embedded HI offset")
            low_offset = _number(low_values[0], "embedded LO offset")
            high = _u16(
                data,
                high_offset - base_offset,
                "embedded HI instruction",
            ) << 16
            low = _i16(
                data,
                low_offset - base_offset,
                "embedded LO instruction",
            )
            target = high + low - base_offset
            if not 0 <= target < len(data):
                raise MenuParseError(
                    "embedded menu target is outside the input",
                    offset=low_offset - base_offset,
                )
            stored = section_targets.setdefault(
                target,
                {"hi": [], "lo": []},
            )
            stored["hi"].extend(
                _number(value, "embedded HI offset") for value in high_values
            )
            stored["lo"].extend(
                _number(value, "embedded LO offset") for value in low_values
            )
    return by_section


def parse_menu_file(
    data: bytes,
    descriptor: Mapping[str, object],
    table: TextTable,
) -> MenuParseResult:
    """Parse one menu descriptor while retaining all pointer provenance."""

    friendly_name = descriptor.get("friendly_name")
    if not isinstance(friendly_name, str) or not friendly_name:
        raise MenuParseError("menu descriptor needs a friendly_name")
    base_offset = _number(descriptor.get("base_offset"), "menu base_offset")
    raw_sections = descriptor.get("sections")
    if not isinstance(raw_sections, list):
        raise MenuParseError("menu descriptor sections must be a list")

    embedded = _embedded_targets(data, descriptor, base_offset)
    entries = []
    section_names = []

    for section_index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict):
            raise MenuParseError("menu section must be an object")
        section = raw_section.get("name")
        if not isinstance(section, str) or not section:
            raise MenuParseError("menu section needs a name")
        section_names.append(section)
        pointer_offsets = []
        target_offsets = []
        raw_pointer_groups = raw_section.get("pointers", [])
        if not isinstance(raw_pointer_groups, list):
            raise MenuParseError("menu pointers must be a list")
        for pointer_group in raw_pointer_groups:
            if not isinstance(pointer_group, dict):
                raise MenuParseError("menu pointer group must be an object")
            if "pointers_alone" in pointer_group:
                found_offsets, found_targets = _standalone_pointers(
                    data,
                    pointer_group["pointers_alone"],
                    base_offset,
                )
            else:
                start = (
                    _number(pointer_group.get("pointers_start"), "pointer start")
                    - base_offset
                )
                end = (
                    _number(pointer_group.get("pointers_end"), "pointer end")
                    - base_offset
                )
                found_offsets, found_targets = _regular_pointers(
                    data,
                    start,
                    end,
                    base_offset,
                    pointer_group.get("style"),
                )
            pointer_offsets.extend(found_offsets)
            target_offsets.extend(found_targets)

        # The upstream XML groups equal decoded text within each section.
        grouped = {}
        section_embedded = embedded.get(section, {})
        for pointer_offset, target_offset in zip(
            pointer_offsets,
            target_offsets,
        ):
            decoded = decode_text(data, target_offset, table)
            group = grouped.setdefault(
                decoded.text,
                {
                    "pointers": [],
                    "targets": [],
                    "hi": [],
                    "lo": [],
                    "unknown": 0,
                },
            )
            group["pointers"].append(pointer_offset)
            group["targets"].append(target_offset)
            group["unknown"] += decoded.unknown_code_count
            embedded_pointer = section_embedded.pop(target_offset, None)
            if embedded_pointer is not None:
                group["hi"].extend(embedded_pointer["hi"])
                group["lo"].extend(embedded_pointer["lo"])

        for target_offset, embedded_pointer in section_embedded.items():
            decoded = decode_text(data, target_offset, table)
            group = grouped.setdefault(
                decoded.text,
                {
                    "pointers": [],
                    "targets": [],
                    "hi": [],
                    "lo": [],
                    "unknown": 0,
                },
            )
            group["targets"].append(target_offset)
            group["hi"].extend(embedded_pointer["hi"])
            group["lo"].extend(embedded_pointer["lo"])
            group["unknown"] += decoded.unknown_code_count

        for ordinal, (text, group) in enumerate(grouped.items()):
            entries.append(
                MenuTextEntry(
                    entry_id=(
                        f"menu/{friendly_name}/"
                        f"{section_index:02d}/{ordinal:04d}"
                    ),
                    section=section,
                    ordinal=ordinal,
                    text=text,
                    pointer_offsets=tuple(group["pointers"]),
                    target_offsets=tuple(group["targets"]),
                    embedded_hi=tuple(group["hi"]),
                    embedded_lo=tuple(group["lo"]),
                    unknown_code_count=group["unknown"],
                )
            )

    return MenuParseResult(
        friendly_name=friendly_name,
        source_size=len(data),
        base_offset=base_offset,
        entries=tuple(entries),
        section_names=tuple(section_names),
    )


__all__ = [
    "MenuParseError",
    "MenuParseResult",
    "MenuTextEntry",
    "parse_menu_file",
]
