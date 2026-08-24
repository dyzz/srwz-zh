"""Fail-closed executable patches for route-specific full-name order."""

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


def _is_lb_v0_from_record_order(instruction: bytes) -> bool:
    """Return whether the instruction is ``lb $v0, 45($v1)``."""

    word = struct.unpack("<I", instruction)[0]
    return (
        word >> 26 == 0x20
        and (word >> 21) & 0x1F == 3
        and (word >> 16) & 0x1F == 2
        and word & 0xFFFF == 45
    )


def _is_sltu_v0_zero_a0(instruction: bytes) -> bool:
    """Return whether the instruction is ``sltu $v0, $zero, $a0``."""

    word = struct.unpack("<I", instruction)[0]
    return (
        word >> 26 == 0
        and (word >> 21) & 0x1F == 0
        and (word >> 16) & 0x1F == 4
        and (word >> 11) & 0x1F == 2
        and (word >> 6) & 0x1F == 0
        and word & 0x3F == 0x2B
    )


def _mapped_site(
    raw_site: object,
    *,
    label: str,
    file_base: int,
    virtual_base: int,
) -> tuple[Mapping[str, object], int, int, bytes, bytes]:
    if not isinstance(raw_site, Mapping):
        raise FullNameOrderError(f"{label} contract must be an object")
    virtual_address = _number(
        raw_site.get("virtual_address"), f"{label} virtual address"
    )
    file_offset = _number(raw_site.get("file_offset"), f"{label} file offset")
    if virtual_address - virtual_base + file_base != file_offset:
        raise FullNameOrderError(f"{label} ELF virtual/file mapping drift")
    original = _instruction_bytes(
        raw_site.get("original_instruction_hex"), f"original {label} instruction"
    )
    replacement = _instruction_bytes(
        raw_site.get("replacement_instruction_hex"),
        f"replacement {label} instruction",
    )
    return raw_site, virtual_address, file_offset, original, replacement


def _replace_site(
    source: bytes,
    *,
    label: str,
    file_offset: int,
    original: bytes,
    replacement: bytes,
) -> tuple[bytes, bytes, bool]:
    if file_offset < 0 or file_offset + 4 > len(source):
        raise FullNameOrderError(f"{label} instruction exceeds executable")
    observed = source[file_offset : file_offset + 4]
    if observed not in (original, replacement):
        raise FullNameOrderError(
            f"{label} instruction preimage drift: "
            f"expected {original.hex().upper()} or "
            f"{replacement.hex().upper()}, got {observed.hex().upper()}"
        )
    if observed == replacement:
        return source, observed, False
    return (
        source[:file_offset] + replacement + source[file_offset + 4 :],
        observed,
        True,
    )


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
    """Use the protagonist route for story and save-screen full-name order."""

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

    (
        formatter_contract,
        formatter_virtual_address,
        formatter_file_offset,
        formatter_original,
        formatter_replacement,
    ) = _mapped_site(
        raw_contract.get("savedata_formatter"),
        label="savedata formatter",
        file_base=file_base,
        virtual_base=virtual_base,
    )
    if formatter_contract.get("route_argument_multiplier") != 7:
        raise FullNameOrderError("savedata formatter route multiplier drift")
    if not _is_lb_v0_from_record_order(formatter_original):
        raise FullNameOrderError(
            "savedata formatter original instruction must be lb $v0, 45($v1)"
        )
    if not _is_sltu_v0_zero_a0(formatter_replacement):
        raise FullNameOrderError(
            "savedata formatter replacement must be sltu $v0, $zero, $a0"
        )

    (
        writeback_contract,
        writeback_virtual_address,
        writeback_file_offset,
        writeback_original,
        writeback_replacement,
    ) = _mapped_site(
        raw_contract.get("savedata_writeback"),
        label="savedata writeback",
        file_base=file_base,
        virtual_base=virtual_base,
    )
    writeback_base_register_value = _number(
        writeback_contract.get("base_register_runtime_value"),
        "savedata writeback $at runtime value",
    )
    writeback_original_load_address = _number(
        writeback_contract.get("original_load_address"),
        "savedata writeback original load address",
    )
    writeback_replacement_load_address = _number(
        writeback_contract.get("replacement_load_address"),
        "savedata writeback replacement load address",
    )
    if (
        _lb_effective_address(
            writeback_original,
            base_register_value=writeback_base_register_value,
        )
        != writeback_original_load_address
    ):
        raise FullNameOrderError("savedata writeback original load address drift")
    if (
        _lb_effective_address(
            writeback_replacement,
            base_register_value=writeback_base_register_value,
        )
        != writeback_replacement_load_address
    ):
        raise FullNameOrderError("savedata writeback route load address drift")

    source = bytes(executable)
    output, observed, story_changed = _replace_site(
        source,
        label="story full-name order",
        file_offset=file_offset,
        original=original,
        replacement=replacement,
    )
    output, formatter_observed, formatter_changed = _replace_site(
        output,
        label="savedata formatter",
        file_offset=formatter_file_offset,
        original=formatter_original,
        replacement=formatter_replacement,
    )
    output, writeback_observed, writeback_changed = _replace_site(
        output,
        label="savedata writeback",
        file_offset=writeback_file_offset,
        original=writeback_original,
        replacement=writeback_replacement,
    )
    changed_sites = (story_changed, formatter_changed, writeback_changed)
    already_patched = not any(changed_sites)
    changed_byte_count = sum(
        before != after for before, after in zip(source, output)
    )
    formatter_report = {
        "virtual_address": f"0x{formatter_virtual_address:X}",
        "file_offset": f"0x{formatter_file_offset:X}",
        "original_instruction_hex": formatter_original.hex().upper(),
        "replacement_instruction_hex": formatter_replacement.hex().upper(),
        "route_argument_multiplier": 7,
        "source_instruction_hex": formatter_observed.hex().upper(),
        "output_instruction_hex": output[
            formatter_file_offset : formatter_file_offset + 4
        ].hex().upper(),
        "already_patched": not formatter_changed,
        "instruction_replacement_exact": (
            output[formatter_file_offset : formatter_file_offset + 4]
            == formatter_replacement
        ),
    }
    writeback_report = {
        "virtual_address": f"0x{writeback_virtual_address:X}",
        "file_offset": f"0x{writeback_file_offset:X}",
        "base_register_runtime_value": f"0x{writeback_base_register_value:X}",
        "original_instruction_hex": writeback_original.hex().upper(),
        "replacement_instruction_hex": writeback_replacement.hex().upper(),
        "original_load_address": f"0x{writeback_original_load_address:X}",
        "replacement_load_address": f"0x{writeback_replacement_load_address:X}",
        "source_instruction_hex": writeback_observed.hex().upper(),
        "output_instruction_hex": output[
            writeback_file_offset : writeback_file_offset + 4
        ].hex().upper(),
        "already_patched": not writeback_changed,
        "instruction_replacement_exact": (
            output[writeback_file_offset : writeback_file_offset + 4]
            == writeback_replacement
        ),
    }
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
        "changed_instruction_count": sum(changed_sites),
        "changed_byte_count": changed_byte_count,
        "source_size": len(source),
        "output_size": len(output),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "instruction_replacement_exact": (
            output[file_offset : file_offset + 4] == replacement
        ),
        "savedata_formatter": formatter_report,
        "savedata_writeback": writeback_report,
        "all_instruction_replacements_exact": (
            output[file_offset : file_offset + 4] == replacement
            and formatter_report["instruction_replacement_exact"]
            and writeback_report["instruction_replacement_exact"]
        ),
        "executable_size_preserved": len(output) == len(source),
    }


__all__ = [
    "FullNameOrderError",
    "apply_route_specific_full_name_order",
]
