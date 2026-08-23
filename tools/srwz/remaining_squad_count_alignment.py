"""Fail-closed SLPS patch for the automatic-formation remaining-count field."""

from __future__ import annotations

import hashlib
from typing import Mapping


class RemainingSquadCountAlignmentError(ValueError):
    """The remaining-count layout contract or executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise RemainingSquadCountAlignmentError(
                f"{label} is not an integer"
            ) from error
    raise RemainingSquadCountAlignmentError(f"{label} must be an integer")


def _instruction(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise RemainingSquadCountAlignmentError(
            f"{label} must be hexadecimal text"
        )
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise RemainingSquadCountAlignmentError(
            f"{label} is not hexadecimal"
        ) from error
    if len(raw) != 4:
        raise RemainingSquadCountAlignmentError(
            f"{label} must encode one MIPS instruction"
        )
    return raw


def apply_remaining_squad_count_alignment(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Move only the formatted squad-count field eight pixels to the right."""

    if not isinstance(raw_contract, Mapping):
        raise RemainingSquadCountAlignmentError(
            "remaining squad-count alignment contract must be an object"
        )
    if raw_contract.get("member") != "SLPS_258.87":
        raise RemainingSquadCountAlignmentError(
            "remaining squad-count executable member drift"
        )
    if (
        raw_contract.get("policy")
        != "move_printf_number_right_without_touching_adjacent_text"
    ):
        raise RemainingSquadCountAlignmentError(
            "remaining squad-count alignment policy drift"
        )

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    source = bytes(executable)
    output = bytearray(source)

    fields: dict[str, dict[str, object]] = {}
    for name in ("prefix", "number", "suffix"):
        raw_field = raw_contract.get(name)
        if not isinstance(raw_field, Mapping):
            raise RemainingSquadCountAlignmentError(
                f"remaining squad-count {name} field is invalid"
            )
        virtual_address = _number(
            raw_field.get("instruction_virtual_address"),
            f"{name} instruction virtual address",
        )
        file_offset = _number(
            raw_field.get("instruction_file_offset"),
            f"{name} instruction file offset",
        )
        if virtual_address - virtual_base + file_base != file_offset:
            raise RemainingSquadCountAlignmentError(
                f"{name} ELF virtual/file offset mapping drift"
            )
        if file_offset < 0 or file_offset + 4 > len(output):
            raise RemainingSquadCountAlignmentError(
                f"{name} coordinate instruction exceeds executable"
            )
        original_x = _number(raw_field.get("original_x"), f"{name} original X")
        expected = _instruction(
            raw_field.get("original_instruction_hex"),
            f"{name} original instruction",
        )
        fields[name] = {
            "virtual_address": virtual_address,
            "file_offset": file_offset,
            "original_x": original_x,
            "expected": expected,
        }

    prefix_x = int(fields["prefix"]["original_x"])
    original_number_x = int(fields["number"]["original_x"])
    suffix_x = int(fields["suffix"]["original_x"])
    replacement_x = _number(
        raw_contract.get("replacement_number_x"), "replacement number X"
    )
    if not (prefix_x < original_number_x < replacement_x < suffix_x):
        raise RemainingSquadCountAlignmentError(
            "remaining squad-count X-coordinate order drift"
        )
    if replacement_x - original_number_x != 8:
        raise RemainingSquadCountAlignmentError(
            "remaining squad-count adjustment must be exactly eight pixels"
        )

    replacement = _instruction(
        raw_contract.get("replacement_number_instruction_hex"),
        "replacement number instruction",
    )
    number_offset = int(fields["number"]["file_offset"])
    original_number_instruction = bytes(fields["number"]["expected"])
    observed_number_instruction = bytes(output[number_offset : number_offset + 4])
    if observed_number_instruction not in {
        original_number_instruction,
        replacement,
    }:
        raise RemainingSquadCountAlignmentError(
            "remaining squad-count number-coordinate preimage drift: "
            f"expected {original_number_instruction.hex().upper()} or "
            f"{replacement.hex().upper()}, got "
            f"{observed_number_instruction.hex().upper()}"
        )

    for name in ("prefix", "suffix"):
        offset = int(fields[name]["file_offset"])
        expected = bytes(fields[name]["expected"])
        observed = bytes(output[offset : offset + 4])
        if observed != expected:
            raise RemainingSquadCountAlignmentError(
                f"remaining squad-count {name} coordinate drift: expected "
                f"{expected.hex().upper()}, got {observed.hex().upper()}"
            )

    output[number_offset : number_offset + 4] = replacement
    result = bytes(output)
    changed_byte_count = sum(
        before != after for before, after in zip(source, result)
    )
    return result, {
        "policy": raw_contract["policy"],
        "member": raw_contract["member"],
        "source_format_file_offset": raw_contract.get(
            "source_format_file_offset"
        ),
        "prefix_x": prefix_x,
        "original_number_x": original_number_x,
        "replacement_number_x": replacement_x,
        "suffix_x": suffix_x,
        "shift_pixels": replacement_x - original_number_x,
        "number_instruction_virtual_address": (
            f"0x{int(fields['number']['virtual_address']):X}"
        ),
        "number_instruction_file_offset": f"0x{number_offset:X}",
        "original_number_instruction_hex": (
            original_number_instruction.hex().upper()
        ),
        "replacement_number_instruction_hex": replacement.hex().upper(),
        "source_number_instruction_hex": (
            observed_number_instruction.hex().upper()
        ),
        "output_number_instruction_hex": (
            bytes(result[number_offset : number_offset + 4]).hex().upper()
        ),
        "already_patched": observed_number_instruction == replacement,
        "changed_byte_count": changed_byte_count,
        "source_size": len(source),
        "output_size": len(result),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
        "adjacent_coordinates_preserved": True,
        "format_token_untouched": True,
        "instruction_replacement_exact": (
            bytes(result[number_offset : number_offset + 4]) == replacement
        ),
        "executable_size_preserved": len(result) == len(source),
    }


__all__ = [
    "RemainingSquadCountAlignmentError",
    "apply_remaining_squad_count_alignment",
]
