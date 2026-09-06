"""Fail-closed SLPS patch for the map-command status labels."""

from __future__ import annotations

import hashlib
from typing import Mapping


class CommandStatusLabelAlignmentError(ValueError):
    """The command-status alignment contract or executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise CommandStatusLabelAlignmentError(
                f"{label} is not an integer"
            ) from error
    raise CommandStatusLabelAlignmentError(f"{label} must be an integer")


def _instruction(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise CommandStatusLabelAlignmentError(
            f"{label} must be hexadecimal text"
        )
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise CommandStatusLabelAlignmentError(
            f"{label} is not hexadecimal"
        ) from error
    if len(raw) != 4:
        raise CommandStatusLabelAlignmentError(
            f"{label} must encode one MIPS instruction"
        )
    return raw


def apply_command_status_label_alignment(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Move the Chinese SR-points label eight pixels right."""

    if not isinstance(raw_contract, Mapping):
        raise CommandStatusLabelAlignmentError(
            "command-status alignment contract must be an object"
        )
    if raw_contract.get("member") != "SLPS_258.87":
        raise CommandStatusLabelAlignmentError(
            "command-status executable member drift"
        )
    if (
        raw_contract.get("policy")
        != "align_chinese_sr_points_with_turn_count"
    ):
        raise CommandStatusLabelAlignmentError(
            "command-status alignment policy drift"
        )

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    shift_pixels = _number(raw_contract.get("shift_pixels"), "pixel shift")
    if shift_pixels != 8:
        raise CommandStatusLabelAlignmentError(
            "command-status adjustment must be exactly 8 pixels right"
        )

    patch = raw_contract.get("patch")
    if not isinstance(patch, Mapping):
        raise CommandStatusLabelAlignmentError(
            "command-status patch must be an object"
        )
    if patch.get("surface") != "map_command_status_sr_points":
        raise CommandStatusLabelAlignmentError(
            "command-status target surface drift"
        )
    if patch.get("source_text") != "ＳＲポイント":
        raise CommandStatusLabelAlignmentError(
            "command-status Japanese source label drift"
        )
    if patch.get("translated_text") != "SR点数":
        raise CommandStatusLabelAlignmentError(
            "command-status translated label drift"
        )

    virtual_address = _number(
        patch.get("instruction_virtual_address"),
        "command-status instruction virtual address",
    )
    file_offset = _number(
        patch.get("instruction_file_offset"),
        "command-status instruction file offset",
    )
    if virtual_address - virtual_base + file_base != file_offset:
        raise CommandStatusLabelAlignmentError(
            "command-status ELF virtual/file offset mapping drift"
        )
    original_x = _number(patch.get("original_x"), "command-status original X")
    replacement_x = _number(
        patch.get("replacement_x"), "command-status replacement X"
    )
    if replacement_x - original_x != shift_pixels:
        raise CommandStatusLabelAlignmentError(
            "command-status coordinate shift drift"
        )

    original = _instruction(
        patch.get("original_instruction_hex"),
        "command-status original instruction",
    )
    replacement = _instruction(
        patch.get("replacement_instruction_hex"),
        "command-status replacement instruction",
    )
    if file_offset < 0 or file_offset + 4 > len(executable):
        raise CommandStatusLabelAlignmentError(
            "command-status coordinate instruction exceeds executable"
        )

    source = bytes(executable)
    observed = source[file_offset : file_offset + 4]
    if observed not in {original, replacement}:
        raise CommandStatusLabelAlignmentError(
            "command-status coordinate preimage drift: expected "
            f"{original.hex().upper()} or {replacement.hex().upper()}, "
            f"got {observed.hex().upper()}"
        )
    output = bytearray(source)
    output[file_offset : file_offset + 4] = replacement
    result = bytes(output)
    changed_offsets = {
        index
        for index, (before, after) in enumerate(zip(source, result))
        if before != after
    }
    instruction_offsets = set(range(file_offset, file_offset + 4))
    if not changed_offsets <= instruction_offsets:
        raise CommandStatusLabelAlignmentError(
            "command-status patch escaped the coordinate instruction"
        )

    patch_report = {
        "surface": patch["surface"],
        "source_text": patch["source_text"],
        "translated_text": patch["translated_text"],
        "instruction_virtual_address": f"0x{virtual_address:X}",
        "instruction_file_offset": f"0x{file_offset:X}",
        "original_x": original_x,
        "replacement_x": replacement_x,
        "shift_pixels": shift_pixels,
        "original_instruction_hex": original.hex().upper(),
        "replacement_instruction_hex": replacement.hex().upper(),
        "source_instruction_hex": observed.hex().upper(),
        "output_instruction_hex": replacement.hex().upper(),
        "already_patched": observed == replacement,
    }
    return result, {
        "policy": raw_contract["policy"],
        "member": raw_contract["member"],
        "shift_pixels": shift_pixels,
        "original_x": original_x,
        "replacement_x": replacement_x,
        "site_count": 1,
        "patch": patch_report,
        "changed_byte_count": len(changed_offsets),
        "changed_bytes_confined_to_coordinate_instruction": (
            changed_offsets <= instruction_offsets
        ),
        "instruction_replacement_exact": (
            patch_report["output_instruction_hex"]
            == patch_report["replacement_instruction_hex"]
        ),
        "text_bytes_untouched": True,
        "turn_count_coordinate_untouched": True,
        "executable_size_preserved": len(result) == len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
    }


__all__ = [
    "CommandStatusLabelAlignmentError",
    "apply_command_status_label_alignment",
]
