"""Fail-closed SLPS patch for Bazaar purchase-screen help prompts."""

from __future__ import annotations

import hashlib
from typing import Mapping, Sequence


class BazaarTopHelpAlignmentError(ValueError):
    """The Bazaar help-prompt contract or executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise BazaarTopHelpAlignmentError(
                f"{label} is not an integer"
            ) from error
    raise BazaarTopHelpAlignmentError(f"{label} must be an integer")


def _instruction(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise BazaarTopHelpAlignmentError(
            f"{label} must be hexadecimal text"
        )
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise BazaarTopHelpAlignmentError(
            f"{label} is not hexadecimal"
        ) from error
    if len(raw) != 4:
        raise BazaarTopHelpAlignmentError(
            f"{label} must encode one MIPS instruction"
        )
    return raw


def apply_bazaar_top_help_alignment(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Move the purchase screen's two help-prompt columns 12 pixels left."""

    if not isinstance(raw_contract, Mapping):
        raise BazaarTopHelpAlignmentError(
            "Bazaar top-help alignment contract must be an object"
        )
    if raw_contract.get("member") != "SLPS_258.87":
        raise BazaarTopHelpAlignmentError(
            "Bazaar top-help executable member drift"
        )
    if (
        raw_contract.get("policy")
        != "shift_purchase_help_left_without_changing_text"
    ):
        raise BazaarTopHelpAlignmentError(
            "Bazaar top-help alignment policy drift"
        )

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    shift_pixels = _number(raw_contract.get("shift_pixels"), "pixel shift")
    if shift_pixels != -12:
        raise BazaarTopHelpAlignmentError(
            "Bazaar top-help adjustment must be exactly 12 pixels left"
        )

    raw_patches = raw_contract.get("patches")
    if not isinstance(raw_patches, Sequence) or isinstance(
        raw_patches, (str, bytes)
    ):
        raise BazaarTopHelpAlignmentError(
            "Bazaar top-help patches must be a list"
        )
    if len(raw_patches) != 4:
        raise BazaarTopHelpAlignmentError(
            "Bazaar top-help alignment requires four draw sites"
        )

    source = bytes(executable)
    output = bytearray(source)
    reports: list[dict[str, object]] = []
    seen_surfaces: set[str] = set()
    allowed_offsets: set[int] = set()
    for raw_patch in raw_patches:
        if not isinstance(raw_patch, Mapping):
            raise BazaarTopHelpAlignmentError(
                "Bazaar top-help patch must be an object"
            )
        surface = raw_patch.get("surface")
        text = raw_patch.get("text")
        source_text = raw_patch.get("source_text")
        if not isinstance(surface, str) or not surface:
            raise BazaarTopHelpAlignmentError(
                "Bazaar top-help surface must be non-empty"
            )
        if surface in seen_surfaces:
            raise BazaarTopHelpAlignmentError(
                f"duplicate Bazaar top-help surface: {surface}"
            )
        seen_surfaces.add(surface)
        if (
            not isinstance(text, str)
            or not text.startswith("　")
            or text.startswith("　　")
            or "：" in text
        ):
            raise BazaarTopHelpAlignmentError(
                f"{surface} translated help text must replace the colon "
                "with one fullwidth space"
            )
        if not isinstance(source_text, str) or not source_text.startswith("："):
            raise BazaarTopHelpAlignmentError(
                f"{surface} source help text is invalid"
            )

        virtual_address = _number(
            raw_patch.get("instruction_virtual_address"),
            f"{surface} instruction virtual address",
        )
        file_offset = _number(
            raw_patch.get("instruction_file_offset"),
            f"{surface} instruction file offset",
        )
        if virtual_address - virtual_base + file_base != file_offset:
            raise BazaarTopHelpAlignmentError(
                f"{surface} ELF virtual/file offset mapping drift"
            )
        if file_offset in allowed_offsets:
            raise BazaarTopHelpAlignmentError(
                f"duplicate Bazaar top-help file offset: 0x{file_offset:X}"
            )
        allowed_offsets.add(file_offset)
        if file_offset < 0 or file_offset + 4 > len(output):
            raise BazaarTopHelpAlignmentError(
                f"{surface} coordinate instruction exceeds executable"
            )

        original_x = _number(
            raw_patch.get("original_x"), f"{surface} original X"
        )
        replacement_x = _number(
            raw_patch.get("replacement_x"), f"{surface} replacement X"
        )
        if replacement_x - original_x != shift_pixels:
            raise BazaarTopHelpAlignmentError(
                f"{surface} coordinate shift drift"
            )
        original = _instruction(
            raw_patch.get("original_instruction_hex"),
            f"{surface} original instruction",
        )
        replacement = _instruction(
            raw_patch.get("replacement_instruction_hex"),
            f"{surface} replacement instruction",
        )
        observed = bytes(output[file_offset : file_offset + 4])
        if observed not in {original, replacement}:
            raise BazaarTopHelpAlignmentError(
                f"{surface} coordinate preimage drift: expected "
                f"{original.hex().upper()} or {replacement.hex().upper()}, "
                f"got {observed.hex().upper()}"
            )
        output[file_offset : file_offset + 4] = replacement
        reports.append(
            {
                "surface": surface,
                "text": text,
                "source_text": source_text,
                "source_string_file_offset": raw_patch.get(
                    "source_string_file_offset"
                ),
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
        )

    required_surfaces = {
        "confirm",
        "owned_parts",
        "eligible_pilots",
        "owned_items",
    }
    if seen_surfaces != required_surfaces:
        raise BazaarTopHelpAlignmentError(
            "Bazaar top-help surface set drift: "
            f"missing={sorted(required_surfaces - seen_surfaces)}, "
            f"extra={sorted(seen_surfaces - required_surfaces)}"
        )

    result = bytes(output)
    changed_offsets = {
        index
        for index, (before, after) in enumerate(zip(source, result))
        if before != after
    }
    if changed_offsets - allowed_offsets:
        raise BazaarTopHelpAlignmentError(
            "Bazaar top-help patch escaped the coordinate instructions"
        )
    confirm = next(item for item in reports if item["surface"] == "confirm")
    secondary = [item for item in reports if item["surface"] != "confirm"]
    return result, {
        "policy": raw_contract["policy"],
        "member": raw_contract["member"],
        "shift_pixels": shift_pixels,
        "confirm_original_x": confirm["original_x"],
        "confirm_replacement_x": confirm["replacement_x"],
        "secondary_original_x": secondary[0]["original_x"],
        "secondary_replacement_x": secondary[0]["replacement_x"],
        "patches": reports,
        "site_count": len(reports),
        "changed_byte_count": len(changed_offsets),
        "changed_bytes_confined_to_coordinate_instructions": (
            changed_offsets <= allowed_offsets
        ),
        "all_instruction_replacements_exact": all(
            item["output_instruction_hex"]
            == item["replacement_instruction_hex"]
            for item in reports
        ),
        "text_bytes_untouched": True,
        "executable_size_preserved": len(result) == len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
    }


__all__ = [
    "BazaarTopHelpAlignmentError",
    "apply_bazaar_top_help_alignment",
]
