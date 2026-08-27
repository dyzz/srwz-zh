"""Fail-closed SLPS coordinate patch for the intermission Library menu."""

from __future__ import annotations

import hashlib
import struct
from typing import Mapping, Sequence


class IntermissionLibraryAlignmentError(ValueError):
    """The Library-menu position-table contract or preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise IntermissionLibraryAlignmentError(
                f"{label} is not an integer"
            ) from error
    raise IntermissionLibraryAlignmentError(f"{label} must be an integer")


def apply_intermission_library_alignment(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Move only the Robot Encyclopedia row ten pixels to the left."""

    if not isinstance(raw_contract, Mapping):
        raise IntermissionLibraryAlignmentError(
            "intermission Library alignment contract must be an object"
        )
    if raw_contract.get("member") != "SLPS_258.87":
        raise IntermissionLibraryAlignmentError(
            "intermission Library executable member drift"
        )
    if (
        raw_contract.get("policy")
        != "move_robot_encyclopedia_coordinate_without_changing_text_padding"
    ):
        raise IntermissionLibraryAlignmentError(
            "intermission Library alignment policy drift"
        )

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    table_offset = _number(
        raw_contract.get("position_table_file_offset"),
        "position-table file offset",
    )
    stride = _number(raw_contract.get("entry_stride"), "entry stride")
    if stride != 8:
        raise IntermissionLibraryAlignmentError(
            "intermission Library entry stride must be eight bytes"
        )
    target_surface = raw_contract.get("target_surface")
    if target_surface != "robot_encyclopedia":
        raise IntermissionLibraryAlignmentError(
            "intermission Library target surface drift"
        )
    entries = raw_contract.get("entries")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise IntermissionLibraryAlignmentError(
            "intermission Library entries must be a list"
        )
    if len(entries) != 6:
        raise IntermissionLibraryAlignmentError(
            "intermission Library alignment requires six rows"
        )

    source = bytes(executable)
    output = bytearray(source)
    if table_offset < 0 or table_offset + len(entries) * stride > len(output):
        raise IntermissionLibraryAlignmentError(
            "intermission Library position table exceeds executable"
        )

    expected_surfaces = (
        "robot_encyclopedia",
        "character_encyclopedia",
        "glossary",
        "sound_select",
        "scenario_chart",
        "strategy_qa",
    )
    reports = []
    target_coordinate_offset = None
    target_original_x = None
    target_replacement_x = None
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, Mapping):
            raise IntermissionLibraryAlignmentError(
                "intermission Library row must be an object"
            )
        surface = raw_entry.get("surface")
        if surface != expected_surfaces[index]:
            raise IntermissionLibraryAlignmentError(
                f"intermission Library row {index} surface drift"
            )
        label = raw_entry.get("label")
        if not isinstance(label, str) or not label:
            raise IntermissionLibraryAlignmentError(
                f"{surface} label must be non-empty"
            )
        string_offset = _number(
            raw_entry.get("source_string_file_offset"),
            f"{surface} source-string file offset",
        )
        expected_pointer = _number(
            raw_entry.get("pointer_virtual_address"),
            f"{surface} pointer virtual address",
        )
        if string_offset - file_base + virtual_base != expected_pointer:
            raise IntermissionLibraryAlignmentError(
                f"{surface} string virtual/file mapping drift"
            )
        row_offset = table_offset + index * stride
        pointer, observed_x, tail = struct.unpack_from("<IhH", source, row_offset)
        if pointer != expected_pointer or tail != 0:
            raise IntermissionLibraryAlignmentError(
                f"{surface} position-table row drift"
            )
        original_x = _number(raw_entry.get("original_x"), f"{surface} original X")
        replacement_value = raw_entry.get("replacement_x")
        if surface == target_surface:
            replacement_x = _number(
                replacement_value, f"{surface} replacement X"
            )
            if replacement_x - original_x != -10:
                raise IntermissionLibraryAlignmentError(
                    "Robot Encyclopedia adjustment must be exactly ten pixels left"
                )
            if observed_x not in {original_x, replacement_x}:
                raise IntermissionLibraryAlignmentError(
                    f"{surface} coordinate preimage drift: expected "
                    f"{original_x} or {replacement_x}, got {observed_x}"
                )
            coordinate_offset = row_offset + 4
            struct.pack_into("<h", output, coordinate_offset, replacement_x)
            target_coordinate_offset = coordinate_offset
            target_original_x = original_x
            target_replacement_x = replacement_x
            output_x = replacement_x
        else:
            if replacement_value is not None:
                raise IntermissionLibraryAlignmentError(
                    f"{surface} must not define a replacement coordinate"
                )
            if observed_x != original_x:
                raise IntermissionLibraryAlignmentError(
                    f"{surface} coordinate drift: expected {original_x}, got {observed_x}"
                )
            output_x = observed_x
        reports.append(
            {
                "surface": surface,
                "label": label,
                "source_string_file_offset": f"0x{string_offset:X}",
                "pointer_virtual_address": f"0x{pointer:08X}",
                "row_file_offset": f"0x{row_offset:X}",
                "source_x": observed_x,
                "output_x": output_x,
                "targeted": surface == target_surface,
            }
        )

    if target_coordinate_offset is None:
        raise IntermissionLibraryAlignmentError(
            "intermission Library target row is missing"
        )
    result = bytes(output)
    changed_offsets = {
        index
        for index, (before, after) in enumerate(zip(source, result))
        if before != after
    }
    allowed_offsets = {target_coordinate_offset, target_coordinate_offset + 1}
    if changed_offsets - allowed_offsets:
        raise IntermissionLibraryAlignmentError(
            "intermission Library patch escaped the target coordinate"
        )
    target_row_offset = table_offset
    pointer_table_preserved = all(
        source[table_offset + index * stride : table_offset + index * stride + 4]
        == result[table_offset + index * stride : table_offset + index * stride + 4]
        for index in range(len(entries))
    )
    sibling_rows_preserved = all(
        source[table_offset + index * stride : table_offset + (index + 1) * stride]
        == result[table_offset + index * stride : table_offset + (index + 1) * stride]
        for index in range(1, len(entries))
    )
    target_tail_preserved = (
        source[target_row_offset + 6 : target_row_offset + 8]
        == result[target_row_offset + 6 : target_row_offset + 8]
    )
    return result, {
        "policy": raw_contract["policy"],
        "member": raw_contract["member"],
        "target_surface": target_surface,
        "position_table_file_offset": f"0x{table_offset:X}",
        "target_coordinate_file_offset": f"0x{target_coordinate_offset:X}",
        "original_x": target_original_x,
        "replacement_x": target_replacement_x,
        "shift_pixels": target_replacement_x - target_original_x,
        "entries": reports,
        "entry_count": len(reports),
        "changed_byte_count": len(changed_offsets),
        "changed_bytes_confined_to_target_coordinate": (
            changed_offsets <= allowed_offsets
        ),
        "pointer_table_preserved": pointer_table_preserved,
        "sibling_rows_preserved": sibling_rows_preserved,
        "target_tail_preserved": target_tail_preserved,
        "executable_size_preserved": len(result) == len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
    }


__all__ = [
    "IntermissionLibraryAlignmentError",
    "apply_intermission_library_alignment",
]
