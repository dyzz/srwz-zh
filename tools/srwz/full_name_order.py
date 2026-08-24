"""Fail-closed executable patch for route-specific ``$F`` name order."""

from __future__ import annotations

import hashlib
import struct
from typing import Mapping


class FullNameOrderError(ValueError):
    """The full-name order contract or executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise FullNameOrderError(f"{label} is not an integer") from error
    raise FullNameOrderError(f"{label} must be an integer")


def _instruction_bytes(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise FullNameOrderError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise FullNameOrderError(f"{label} is not hexadecimal") from error
    if len(raw) != 4:
        raise FullNameOrderError(f"{label} must encode one MIPS instruction")
    return raw


def _lb_effective_address(
    instruction: bytes,
    *,
    base_register_value: int,
) -> int:
    word = struct.unpack("<I", instruction)[0]
    opcode = word >> 26
    base_register = (word >> 21) & 0x1F
    target_register = (word >> 16) & 0x1F
    if opcode != 0x20 or base_register != 1 or target_register != 3:
        raise FullNameOrderError(
            "full-name order instruction must be lb $v1, immediate($at)"
        )
    immediate = word & 0xFFFF
    if immediate & 0x8000:
        immediate -= 0x10000
    return base_register_value + immediate


def _validated_route_contract(raw_contract: Mapping[str, object]) -> tuple[dict, dict]:
    route_values = raw_contract.get("route_values")
    output_orders = raw_contract.get("output_orders")
    if route_values != {"rand": 0, "setsuko": 1}:
        raise FullNameOrderError("protagonist route values drift")
    if output_orders != {
        "rand": "given_middle_dot_family",
        "setsuko": "family_given",
    }:
        raise FullNameOrderError("route-specific full-name orders drift")
    return dict(route_values), dict(output_orders)


def apply_route_specific_full_name_order(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Make ``$F`` select Chinese name order from the protagonist route."""

    if not isinstance(raw_contract, Mapping):
        raise FullNameOrderError("full-name order contract must be an object")
    if raw_contract.get("member") != "SLPS_258.87":
        raise FullNameOrderError("full-name order executable member drift")
    if raw_contract.get("policy") != (
        "select_chinese_full_name_order_by_protagonist_route"
    ):
        raise FullNameOrderError("full-name order policy drift")

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    virtual_address = _number(
        raw_contract.get("virtual_address"), "patch virtual address"
    )
    file_offset = _number(raw_contract.get("file_offset"), "patch file offset")
    if virtual_address - virtual_base + file_base != file_offset:
        raise FullNameOrderError("full-name order ELF virtual/file mapping drift")

    original = _instruction_bytes(
        raw_contract.get("original_instruction_hex"),
        "original full-name order instruction",
    )
    replacement = _instruction_bytes(
        raw_contract.get("replacement_instruction_hex"),
        "replacement full-name order instruction",
    )
    base_register_value = _number(
        raw_contract.get("base_register_runtime_value"),
        "$at runtime value",
    )
    original_load_address = _number(
        raw_contract.get("original_load_address"),
        "original load address",
    )
    replacement_load_address = _number(
        raw_contract.get("replacement_load_address"),
        "replacement load address",
    )
    if (
        _lb_effective_address(
            original,
            base_register_value=base_register_value,
        )
        != original_load_address
    ):
        raise FullNameOrderError("original name-order load address drift")
    if (
        _lb_effective_address(
            replacement,
            base_register_value=base_register_value,
        )
        != replacement_load_address
    ):
        raise FullNameOrderError("replacement route load address drift")
    route_values, output_orders = _validated_route_contract(raw_contract)

    source = bytes(executable)
    if file_offset < 0 or file_offset + 4 > len(source):
        raise FullNameOrderError("full-name order instruction exceeds executable")
    observed = source[file_offset : file_offset + 4]
    if observed not in (original, replacement):
        raise FullNameOrderError(
            "full-name order instruction preimage drift: "
            f"expected {original.hex().upper()}, got {observed.hex().upper()}"
        )
    already_patched = observed == replacement
    output = source if already_patched else (
        source[:file_offset] + replacement + source[file_offset + 4 :]
    )
    changed_byte_count = sum(
        before != after for before, after in zip(source, output)
    )
    return output, {
        "policy": raw_contract["policy"],
        "virtual_address": f"0x{virtual_address:X}",
        "file_offset": f"0x{file_offset:X}",
        "base_register_runtime_value": f"0x{base_register_value:X}",
        "original_instruction_hex": original.hex().upper(),
        "replacement_instruction_hex": replacement.hex().upper(),
        "original_load_address": f"0x{original_load_address:X}",
        "replacement_load_address": f"0x{replacement_load_address:X}",
        "route_values": route_values,
        "output_orders": output_orders,
        "source_instruction_hex": observed.hex().upper(),
        "output_instruction_hex": output[
            file_offset : file_offset + 4
        ].hex().upper(),
        "already_patched": already_patched,
        "changed_instruction_count": 0 if already_patched else 1,
        "changed_byte_count": changed_byte_count,
        "source_size": len(source),
        "output_size": len(output),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "instruction_replacement_exact": (
            output[file_offset : file_offset + 4] == replacement
        ),
        "executable_size_preserved": len(output) == len(source),
    }


__all__ = [
    "FullNameOrderError",
    "apply_route_specific_full_name_order",
]
