"""Verify native progress checks for the main-game LIBRARY."""

from __future__ import annotations

import struct
from typing import Mapping, Sequence


class LibraryUnlockError(ValueError):
    """The LIBRARY unlock contract or retail executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise LibraryUnlockError(f"{label} is not an integer") from error
    raise LibraryUnlockError(f"{label} must be an integer")


def _instruction_bytes(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise LibraryUnlockError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise LibraryUnlockError(f"{label} is not hexadecimal") from error
    if len(raw) != 4:
        raise LibraryUnlockError(f"{label} must encode one MIPS instruction")
    return raw


def _is_and_to_or(original: bytes, replacement: bytes) -> bool:
    original_word = struct.unpack("<I", original)[0]
    replacement_word = struct.unpack("<I", replacement)[0]
    return (
        original_word >> 26 == 0
        and replacement_word >> 26 == 0
        and original_word & 0x3F == 0x24
        and replacement_word & 0x3F == 0x25
        and original_word & ~0x3F == replacement_word & ~0x3F
    )


def verify_library_progress_visibility(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> dict[str, object]:
    """Require the four native visibility instructions and report their cheat counterparts."""

    if not isinstance(raw_contract, Mapping):
        raise LibraryUnlockError("LIBRARY unlock contract must be an object")
    if raw_contract.get("member") != "SLPS_258.87":
        raise LibraryUnlockError("LIBRARY unlock executable member drift")
    if raw_contract.get("policy") != (
        "include_all_valid_entries_without_save_writeback"
    ):
        raise LibraryUnlockError("LIBRARY unlock policy drift")

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    patches = raw_contract.get("patches")
    if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes)):
        raise LibraryUnlockError("LIBRARY unlock patches must be a list")
    if len(patches) != 4:
        raise LibraryUnlockError("LIBRARY unlock must contain four patches")

    reports = []
    seen_surfaces: set[str] = set()
    seen_offsets: set[int] = set()
    for raw_patch in patches:
        if not isinstance(raw_patch, Mapping):
            raise LibraryUnlockError("LIBRARY unlock patch must be an object")
        surface = raw_patch.get("surface")
        if not isinstance(surface, str) or not surface:
            raise LibraryUnlockError("LIBRARY unlock surface must be non-empty")
        if surface in seen_surfaces:
            raise LibraryUnlockError(f"duplicate LIBRARY unlock surface: {surface}")
        seen_surfaces.add(surface)

        virtual_address = _number(
            raw_patch.get("virtual_address"), f"{surface} virtual address"
        )
        file_offset = _number(
            raw_patch.get("file_offset"), f"{surface} file offset"
        )
        if virtual_address - virtual_base + file_base != file_offset:
            raise LibraryUnlockError(
                f"{surface} ELF virtual/file offset mapping drift"
            )
        if file_offset in seen_offsets:
            raise LibraryUnlockError(
                f"duplicate LIBRARY unlock file offset: 0x{file_offset:X}"
            )
        seen_offsets.add(file_offset)
        if file_offset < 0 or file_offset + 4 > len(executable):
            raise LibraryUnlockError(
                f"{surface} unlock instruction exceeds executable"
            )

        original = _instruction_bytes(
            raw_patch.get("original_instruction_hex"),
            f"{surface} original instruction",
        )
        replacement = _instruction_bytes(
            raw_patch.get("replacement_instruction_hex"),
            f"{surface} replacement instruction",
        )
        if not _is_and_to_or(original, replacement):
            raise LibraryUnlockError(
                f"{surface} unlock is not a register-preserving AND-to-OR patch"
            )
        observed = executable[file_offset : file_offset + 4]
        if observed != original:
            raise LibraryUnlockError(
                f"{surface} native visibility instruction drift: "
                f"expected {original.hex().upper()}, got {observed.hex().upper()}"
            )
        reports.append(
            {
                "surface": surface,
                "virtual_address": f"0x{virtual_address:X}",
                "file_offset": f"0x{file_offset:X}",
                "native_instruction_hex": observed.hex().upper(),
                "cheat_instruction_hex": replacement.hex().upper(),
            }
        )

    required_surfaces = {
        "robot_encyclopedia",
        "character_encyclopedia",
        "keyword_encyclopedia",
        "scenario_chart",
    }
    if seen_surfaces != required_surfaces:
        raise LibraryUnlockError(
            "LIBRARY unlock surface set drift: "
            f"missing={sorted(required_surfaces - seen_surfaces)}, "
            f"extra={sorted(seen_surfaces - required_surfaces)}"
        )

    return {
        "policy": "native_progress",
        "member": raw_contract["member"],
        "checks": reports,
        "surface_count": len(reports),
    }


__all__ = [
    "LibraryUnlockError",
    "verify_library_progress_visibility",
]
