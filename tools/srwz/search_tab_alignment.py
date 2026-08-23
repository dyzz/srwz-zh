"""Fail-closed executable patch for the five Search category labels."""

from __future__ import annotations

import hashlib
from typing import Mapping, Sequence


class SearchTabAlignmentError(ValueError):
    """The Search-tab layout contract or executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise SearchTabAlignmentError(
                f"{label} is not an integer"
            ) from error
    raise SearchTabAlignmentError(f"{label} must be an integer")


def _byte(value: object, label: str) -> int:
    if not isinstance(value, str):
        raise SearchTabAlignmentError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise SearchTabAlignmentError(f"{label} is not hexadecimal") from error
    if len(raw) != 1:
        raise SearchTabAlignmentError(f"{label} must encode one byte")
    return raw[0]


def apply_search_tab_alignment(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Give every four-CJK Search label the same verified table coordinate."""

    if not isinstance(raw_contract, Mapping):
        raise SearchTabAlignmentError(
            "Search-tab alignment contract must be an object"
        )
    if raw_contract.get("member") != "SLPS_258.87":
        raise SearchTabAlignmentError("Search-tab executable member drift")
    if raw_contract.get("policy") != "five_four_cjk_labels_share_verified_center":
        raise SearchTabAlignmentError("Search-tab alignment policy drift")

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    patches = raw_contract.get("patches")
    if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes)):
        raise SearchTabAlignmentError("Search-tab patches must be a list")
    if len(patches) != 5:
        raise SearchTabAlignmentError("Search-tab alignment requires five patches")
    center = _byte(raw_contract.get("center_byte_hex"), "Search-tab center byte")

    source = bytes(executable)
    output = bytearray(source)
    reports = []
    seen_surfaces: set[str] = set()
    seen_offsets: set[int] = set()
    for raw_patch in patches:
        if not isinstance(raw_patch, Mapping):
            raise SearchTabAlignmentError("Search-tab patch must be an object")
        surface = raw_patch.get("surface")
        if not isinstance(surface, str) or not surface:
            raise SearchTabAlignmentError("Search-tab surface must be non-empty")
        if surface in seen_surfaces:
            raise SearchTabAlignmentError(
                f"duplicate Search-tab surface: {surface}"
            )
        seen_surfaces.add(surface)

        virtual_address = _number(
            raw_patch.get("virtual_address"), f"{surface} virtual address"
        )
        file_offset = _number(
            raw_patch.get("file_offset"), f"{surface} file offset"
        )
        if virtual_address - virtual_base + file_base != file_offset:
            raise SearchTabAlignmentError(
                f"{surface} ELF virtual/file offset mapping drift"
            )
        if file_offset in seen_offsets:
            raise SearchTabAlignmentError(
                f"duplicate Search-tab file offset: 0x{file_offset:X}"
            )
        seen_offsets.add(file_offset)
        if file_offset < 0 or file_offset >= len(output):
            raise SearchTabAlignmentError(
                f"{surface} alignment byte exceeds executable"
            )

        label = raw_patch.get("label")
        source_text = raw_patch.get("source_text")
        source_string_file_offset = _number(
            raw_patch.get("source_string_file_offset"),
            f"{surface} source string file offset",
        )
        if not isinstance(label, str) or len(label) != 4:
            raise SearchTabAlignmentError(
                f"{surface} translated label must contain four characters"
            )
        if not isinstance(source_text, str) or not source_text:
            raise SearchTabAlignmentError(
                f"{surface} source label must be non-empty"
            )

        original = _byte(
            raw_patch.get("original_byte_hex"), f"{surface} original byte"
        )
        raw_accepted = raw_patch.get("accepted_current_byte_hexes")
        if not isinstance(raw_accepted, Sequence) or isinstance(
            raw_accepted, (str, bytes)
        ):
            raise SearchTabAlignmentError(
                f"{surface} accepted current bytes must be a list"
            )
        accepted_current = {
            _byte(value, f"{surface} accepted current byte")
            for value in raw_accepted
        }
        observed = output[file_offset]
        accepted_preimages = {original, center, *accepted_current}
        if observed not in accepted_preimages:
            raise SearchTabAlignmentError(
                f"{surface} alignment preimage drift: expected one of "
                f"{'/'.join(f'{value:02X}' for value in sorted(accepted_preimages))}, "
                f"got {observed:02X}"
            )
        already_patched = observed == center
        output[file_offset] = center
        reports.append(
            {
                "surface": surface,
                "label": label,
                "source_text": source_text,
                "source_string_file_offset": f"0x{source_string_file_offset:X}",
                "virtual_address": f"0x{virtual_address:X}",
                "file_offset": f"0x{file_offset:X}",
                "original_byte_hex": f"{original:02X}",
                "accepted_current_byte_hexes": [
                    f"{value:02X}" for value in sorted(accepted_current)
                ],
                "replacement_byte_hex": f"{center:02X}",
                "source_byte_hex": f"{observed:02X}",
                "output_byte_hex": f"{output[file_offset]:02X}",
                "already_patched": already_patched,
                "changed": not already_patched,
            }
        )

    required_surfaces = {
        "spirit_command",
        "special_skill",
        "leader_effect",
        "special_ability",
        "squad_bonus",
    }
    if seen_surfaces != required_surfaces:
        raise SearchTabAlignmentError(
            "Search-tab surface set drift: "
            f"missing={sorted(required_surfaces - seen_surfaces)}, "
            f"extra={sorted(seen_surfaces - required_surfaces)}"
        )

    result = bytes(output)
    return result, {
        "policy": raw_contract["policy"],
        "member": raw_contract["member"],
        "source_reference": raw_contract.get("source_reference"),
        "center_byte_hex": f"{center:02X}",
        "patches": reports,
        "surface_count": len(reports),
        "changed_surface_count": sum(item["changed"] for item in reports),
        "changed_byte_count": sum(
            before != after for before, after in zip(source, result)
        ),
        "source_size": len(source),
        "output_size": len(result),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
        "all_replacements_exact": all(
            item["output_byte_hex"] == item["replacement_byte_hex"]
            for item in reports
        ),
        "executable_size_preserved": len(result) == len(source),
    }


__all__ = [
    "SearchTabAlignmentError",
    "apply_search_tab_alignment",
]
