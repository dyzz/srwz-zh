"""Align the text-width measurement with the glyph renderer's narrow range.

The stock renderer keeps two metric pairs: pair A for ordinary double-byte
codes and pair B for codes the active style narrows (Latin, kana, and a
"broad" symbol band when the fifth style flag is set).  The glyph renderer
(``FUN_0013a290``) applies the broad band to ``0x8140..0x829E`` only, but the
two width-measurement routines used for centred and right-aligned labels
(``FUN_00139b00`` and ``FUN_00261650``) compare against ``0x889F``.  Codes in
``0x8492..0x889E`` are therefore measured narrow yet drawn wide, which shifts
every centred label by ``(A - B) / 2`` pixels per such character.  The
Japanese release only had box-drawing glyphs there; the Chinese font stores
370 common ideographs in that band.

Each patch rewrites the ``ori at, zero, 0x889F`` immediate to ``0x829F`` so
measurement and drawing classify the same codes.  Nothing else changes: the
subrange flags, metric pairs and every renderer stay intact.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping, Sequence


class TextMeasureRangeError(ValueError):
    """The measurement-range contract or executable preimage drifted."""


ORI_OPCODE = 0x0D
REGISTER_AT = 1
REGISTER_ZERO = 0


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise TextMeasureRangeError(f"{label} is not an integer") from error
    raise TextMeasureRangeError(f"{label} must be an integer")


def _instruction(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise TextMeasureRangeError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise TextMeasureRangeError(f"{label} is not hexadecimal") from error
    if len(raw) != 4:
        raise TextMeasureRangeError(f"{label} must encode one instruction")
    return raw


def _ori_immediate(word: bytes, label: str) -> int:
    value = struct.unpack("<I", word)[0]
    if (
        value >> 26 != ORI_OPCODE
        or (value >> 21) & 0x1F != REGISTER_ZERO
        or (value >> 16) & 0x1F != REGISTER_AT
    ):
        raise TextMeasureRangeError(f"{label} is not `ori at, zero, imm`")
    return value & 0xFFFF


def apply_text_measurement_range_patch(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Rewrite the broad-band upper bound in both width-measurement routines."""

    if not isinstance(raw_contract, Mapping):
        raise TextMeasureRangeError("measurement-range contract must be an object")
    if raw_contract.get("member") != "SLPS_258.87":
        raise TextMeasureRangeError("measurement-range executable member drift")
    if raw_contract.get("policy") != "match_measurement_broad_band_to_renderer":
        raise TextMeasureRangeError("measurement-range policy drift")
    original_bound = _number(raw_contract.get("original_upper_bound"), "original upper bound")
    replacement_bound = _number(
        raw_contract.get("replacement_upper_bound"), "replacement upper bound"
    )
    renderer_bound = _number(raw_contract.get("renderer_upper_bound"), "renderer upper bound")
    if not (0x8140 < replacement_bound < original_bound <= 0xFFFF):
        raise TextMeasureRangeError("measurement-range bounds are not ordered")
    if replacement_bound != renderer_bound + 1:
        raise TextMeasureRangeError(
            "replacement bound must be the renderer's inclusive bound plus one"
        )
    file_base = _number(raw_contract.get("elf_file_offset_base"), "ELF file offset base")
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"), "ELF virtual address base"
    )
    patches = raw_contract.get("patches")
    if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes)):
        raise TextMeasureRangeError("measurement-range patches must be a list")
    if len(patches) != 2:
        raise TextMeasureRangeError("measurement-range site inventory drift")

    source = bytes(executable)
    output = bytearray(source)
    reports: list[dict[str, object]] = []
    seen_offsets: set[int] = set()
    seen_sites: set[str] = set()
    for raw_patch in patches:
        if not isinstance(raw_patch, Mapping):
            raise TextMeasureRangeError("measurement-range patch must be an object")
        site = raw_patch.get("id")
        if not isinstance(site, str) or not site or site in seen_sites:
            raise TextMeasureRangeError("measurement-range site ID is invalid or duplicated")
        seen_sites.add(site)
        virtual_address = _number(raw_patch.get("virtual_address"), f"{site} virtual address")
        file_offset = _number(raw_patch.get("file_offset"), f"{site} file offset")
        if virtual_address - virtual_base + file_base != file_offset:
            raise TextMeasureRangeError(f"{site} ELF virtual/file mapping drift")
        if file_offset in seen_offsets or file_offset < 0 or file_offset + 8 > len(output):
            raise TextMeasureRangeError(f"{site} instruction range is invalid")
        seen_offsets.add(file_offset)

        original = _instruction(raw_patch.get("original_instruction_hex"), f"{site} original")
        replacement = _instruction(
            raw_patch.get("replacement_instruction_hex"), f"{site} replacement"
        )
        following = _instruction(
            raw_patch.get("following_instruction_hex"), f"{site} following instruction"
        )
        if _ori_immediate(original, f"{site} original") != original_bound:
            raise TextMeasureRangeError(f"{site} original immediate is not the stock bound")
        if _ori_immediate(replacement, f"{site} replacement") != replacement_bound:
            raise TextMeasureRangeError(f"{site} replacement immediate drift")
        # The compare that consumes `at` must follow immediately: slt/sltu at, code, at.
        compare = struct.unpack("<I", following)[0]
        if (
            compare >> 26 != 0
            or compare & 0x3F not in (0x2A, 0x2B)
            or (compare >> 11) & 0x1F != REGISTER_AT
            or (compare >> 16) & 0x1F != REGISTER_AT
        ):
            raise TextMeasureRangeError(f"{site} following instruction is not the bound compare")

        observed = bytes(output[file_offset : file_offset + 4])
        observed_following = bytes(output[file_offset + 4 : file_offset + 8])
        if observed not in (original, replacement) or observed_following != following:
            raise TextMeasureRangeError(
                f"{site} instruction preimage drift at 0x{file_offset:X}: "
                f"{observed.hex().upper()} {observed_following.hex().upper()}"
            )
        already_patched = observed == replacement
        output[file_offset : file_offset + 4] = replacement
        reports.append(
            {
                "id": site,
                "function": raw_patch.get("function"),
                "virtual_address": f"0x{virtual_address:X}",
                "file_offset": f"0x{file_offset:X}",
                "original_instruction_hex": original.hex().upper(),
                "replacement_instruction_hex": replacement.hex().upper(),
                "following_instruction_hex": following.hex().upper(),
                "already_patched": already_patched,
                "changed": not already_patched,
            }
        )

    changed_offsets = [
        offset for offset in range(0, len(source) - 3, 4)
        if source[offset : offset + 4] != output[offset : offset + 4]
    ]
    if any(offset not in seen_offsets for offset in changed_offsets):
        raise TextMeasureRangeError("measurement-range patch wrote outside its sites")

    return bytes(output), {
        "member": raw_contract["member"],
        "policy": raw_contract["policy"],
        "original_upper_bound": f"0x{original_bound:X}",
        "replacement_upper_bound": f"0x{replacement_bound:X}",
        "renderer_upper_bound": f"0x{renderer_bound:X}",
        "site_count": len(reports),
        "changed_site_count": sum(1 for report in reports if report["changed"]),
        "patches": reports,
        "executable_size_preserved": len(output) == len(source),
        "writes_confined_to_sites": True,
    }


__all__ = ["TextMeasureRangeError", "apply_text_measurement_range_patch"]
