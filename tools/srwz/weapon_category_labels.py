"""Fail-closed patches for weapon-detail category labels built in SLPS code."""

from __future__ import annotations

import struct
from collections.abc import Mapping


class WeaponCategoryLabelError(ValueError):
    """The weapon-category contract or executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise WeaponCategoryLabelError(
                f"{label} is not an integer"
            ) from error
    raise WeaponCategoryLabelError(f"{label} must be an integer")


def _hex_bytes(value: object, label: str, *, size: int) -> bytes:
    if not isinstance(value, str):
        raise WeaponCategoryLabelError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise WeaponCategoryLabelError(
            f"{label} is not hexadecimal"
        ) from error
    if len(raw) != size:
        raise WeaponCategoryLabelError(
            f"{label} must contain exactly {size} bytes"
        )
    return raw


def _instruction_fields(word: int) -> tuple[int, int, int, int]:
    return word >> 26, (word >> 21) & 0x1F, (word >> 16) & 0x1F, word & 0xFFFF


def _materialized_text(
    block: bytes,
    *,
    word_pairs: tuple[tuple[int, int], ...],
    terminator_index: int,
    label: str,
) -> bytes:
    """Assemble the four inline words and the separate NUL store."""

    if len(block) % 4:
        raise WeaponCategoryLabelError(
            f"{label} block is not instruction-aligned"
        )
    words = struct.unpack(f"<{len(block) // 4}I", block)
    assembled = bytearray()
    for pair_index, (lui_index, ori_index) in enumerate(word_pairs):
        try:
            lui = words[lui_index]
            ori = words[ori_index]
        except IndexError as error:
            raise WeaponCategoryLabelError(
                f"{label} word pair {pair_index} exceeds the block"
            ) from error
        lui_opcode, lui_source, lui_target, lui_immediate = (
            _instruction_fields(lui)
        )
        ori_opcode, ori_source, _ori_target, ori_immediate = (
            _instruction_fields(ori)
        )
        if (
            lui_opcode != 0x0F
            or lui_source != 0
            or ori_opcode != 0x0D
            or ori_source != lui_target
        ):
            raise WeaponCategoryLabelError(
                f"{label} word pair {pair_index} is not a LUI/ORI builder"
            )
        runtime_word = (lui_immediate << 16) | ori_immediate
        assembled.extend(runtime_word.to_bytes(4, "little"))

    try:
        terminator = words[terminator_index]
    except IndexError as error:
        raise WeaponCategoryLabelError(
            f"{label} terminator store exceeds the block"
        ) from error
    opcode, source, target, immediate = _instruction_fields(terminator)
    if (opcode, source, target, immediate) != (0x28, 20, 0, 30):
        raise WeaponCategoryLabelError(
            f"{label} no longer terminates the materialized label with NUL"
        )
    assembled.append(0)
    return bytes(assembled)


def apply_runtime_weapon_category_labels(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Simplify both shared category labels used by every weapon detail row."""

    if not isinstance(raw_contract, Mapping):
        raise WeaponCategoryLabelError(
            "weapon-category label contract must be an object"
        )
    if raw_contract.get("member") != "SLPS_258.87":
        raise WeaponCategoryLabelError("weapon-category executable member drift")
    if raw_contract.get("policy") != (
        "replace_runtime_materialized_weapon_category_labels"
    ):
        raise WeaponCategoryLabelError("weapon-category label policy drift")

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    sites = raw_contract.get("sites")
    if not isinstance(sites, list) or len(sites) != 2:
        raise WeaponCategoryLabelError("weapon-category site inventory drift")

    expected = {
        "melee": {
            "source_text": "格闘武器（　　）",
            "translation": "格斗武器（　　）",
            "source_hex": "8A6993AC95908AED816981408140816A00",
            "output_hex": "8A69936C95908AED816981408140816A00",
            "block_size": 76,
            "word_pairs": ((0, 2), (4, 5), (8, 9), (12, 14)),
            "terminator_index": 18,
            "changed_indexes": [1],
        },
        "ranged": {
            "source_text": "射撃武器（　　）",
            "translation": "射击武器（　　）",
            "source_hex": "8ECB8C8295908AED816981408140816A00",
            "output_hex": "8ECB90CA95908AED816981408140816A00",
            "block_size": 80,
            "word_pairs": ((2, 3), (4, 6), (8, 10), (12, 14)),
            "terminator_index": 18,
            "changed_indexes": [8, 9],
        },
    }
    if {
        site.get("id") for site in sites if isinstance(site, Mapping)
    } != set(expected):
        raise WeaponCategoryLabelError("weapon-category site IDs drift")

    output = bytearray(executable)
    reports: list[dict[str, object]] = []
    ranges: list[tuple[int, int]] = []
    for raw_site in sites:
        if not isinstance(raw_site, Mapping):
            raise WeaponCategoryLabelError(
                "weapon-category site must be an object"
            )
        site_id = raw_site.get("id")
        assert isinstance(site_id, str)
        semantics = expected[site_id]
        if (
            raw_site.get("source_text") != semantics["source_text"]
            or raw_site.get("translation") != semantics["translation"]
        ):
            raise WeaponCategoryLabelError(
                f"{site_id} weapon-category semantic contract drift"
            )

        file_offset = _number(
            raw_site.get("file_offset"), f"{site_id} file offset"
        )
        virtual_address = _number(
            raw_site.get("virtual_address"),
            f"{site_id} virtual address",
        )
        if virtual_address - virtual_base + file_base != file_offset:
            raise WeaponCategoryLabelError(
                f"{site_id} ELF virtual/file mapping drift"
            )
        block_size = int(semantics["block_size"])
        original = _hex_bytes(
            raw_site.get("original_block_hex"),
            f"{site_id} original block",
            size=block_size,
        )
        replacement = _hex_bytes(
            raw_site.get("replacement_block_hex"),
            f"{site_id} replacement block",
            size=block_size,
        )
        source_bytes = _hex_bytes(
            raw_site.get("source_materialized_hex"),
            f"{site_id} source materialized text",
            size=17,
        )
        translated_bytes = _hex_bytes(
            raw_site.get("output_materialized_hex"),
            f"{site_id} output materialized text",
            size=17,
        )
        word_pairs = semantics["word_pairs"]
        terminator_index = int(semantics["terminator_index"])
        assert isinstance(word_pairs, tuple)
        if (
            source_bytes.hex().upper() != semantics["source_hex"]
            or translated_bytes.hex().upper() != semantics["output_hex"]
            or _materialized_text(
                original,
                word_pairs=word_pairs,
                terminator_index=terminator_index,
                label=f"{site_id} original",
            )
            != source_bytes
            or _materialized_text(
                replacement,
                word_pairs=word_pairs,
                terminator_index=terminator_index,
                label=f"{site_id} replacement",
            )
            != translated_bytes
        ):
            raise WeaponCategoryLabelError(
                f"{site_id} materialized weapon-category text drift"
            )
        changed_indexes = [
            index
            for index, (before, after) in enumerate(
                zip(original, replacement)
            )
            if before != after
        ]
        if changed_indexes != semantics["changed_indexes"]:
            raise WeaponCategoryLabelError(
                f"{site_id} changes outside the category prefix immediate"
            )
        if file_offset < 0 or file_offset + block_size > len(output):
            raise WeaponCategoryLabelError(
                f"{site_id} block exceeds executable"
            )
        observed = bytes(output[file_offset : file_offset + block_size])
        if observed not in (original, replacement):
            raise WeaponCategoryLabelError(
                f"{site_id} block preimage drift: {observed.hex().upper()}"
            )
        already_patched = observed == replacement
        if not already_patched:
            output[file_offset : file_offset + block_size] = replacement
        ranges.append((file_offset, file_offset + block_size))

        first_lui_index = word_pairs[0][0]
        first_instruction_start = first_lui_index * 4
        reports.append(
            {
                "id": site_id,
                "source_text": semantics["source_text"],
                "translation": semantics["translation"],
                "virtual_address": virtual_address,
                "file_offset": file_offset,
                "source_materialized_hex": source_bytes.hex().upper(),
                "output_materialized_hex": translated_bytes.hex().upper(),
                "original_prefix_instruction_hex": original[
                    first_instruction_start : first_instruction_start + 4
                ].hex().upper(),
                "replacement_prefix_instruction_hex": replacement[
                    first_instruction_start : first_instruction_start + 4
                ].hex().upper(),
                "output_prefix_instruction_hex": replacement[
                    first_instruction_start : first_instruction_start + 4
                ].hex().upper(),
                "changed_byte_count": (
                    0 if already_patched else len(changed_indexes)
                ),
                "already_patched": already_patched,
                "shared_branch_applies_to_all_matching_weapons": True,
                "full_materialization_sequence_exact": True,
            }
        )

    output_bytes = bytes(output)
    changed_offsets = [
        offset
        for offset, (before, after) in enumerate(zip(executable, output_bytes))
        if before != after
    ]
    if len(output_bytes) != len(executable) or any(
        not any(start <= offset < end for start, end in ranges)
        for offset in changed_offsets
    ):
        raise WeaponCategoryLabelError(
            "weapon-category patch changed bytes outside sites"
        )
    if len(changed_offsets) != sum(
        int(report["changed_byte_count"]) for report in reports
    ):
        raise WeaponCategoryLabelError(
            "weapon-category changed-byte count drift"
        )

    return output_bytes, {
        "policy": raw_contract["policy"],
        "site_count": len(reports),
        "sites": reports,
        "changed_byte_count": len(changed_offsets),
        "all_matching_weapon_instances_covered_by_shared_branches": True,
        "all_materialization_sequences_exact": True,
        "all_replacements_exact": True,
        "executable_size_preserved": len(output_bytes) == len(executable),
    }


__all__ = [
    "WeaponCategoryLabelError",
    "apply_runtime_weapon_category_labels",
]
