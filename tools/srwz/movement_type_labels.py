"""Fail-closed patches for runtime-materialized movement-type labels."""

from __future__ import annotations

import struct
from collections.abc import Mapping


class MovementTypeLabelError(ValueError):
    """The movement-type label contract or executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise MovementTypeLabelError(f"{label} is not an integer") from error
    raise MovementTypeLabelError(f"{label} must be an integer")


def _hex_bytes(value: object, label: str, *, size: int) -> bytes:
    if not isinstance(value, str):
        raise MovementTypeLabelError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise MovementTypeLabelError(f"{label} is not hexadecimal") from error
    if len(raw) != size:
        raise MovementTypeLabelError(
            f"{label} must contain exactly {size} bytes"
        )
    return raw


def _instruction_fields(word: int) -> tuple[int, int, int, int]:
    return word >> 26, (word >> 21) & 0x1F, (word >> 16) & 0x1F, word & 0xFFFF


def _materialized_text(block: bytes, *, label: str) -> bytes:
    """Decode the six bytes written by the locked eight-instruction sequence."""

    if len(block) != 32:
        raise MovementTypeLabelError(f"{label} block must contain 8 instructions")
    words = struct.unpack("<8I", block)
    expected_fields = (
        (0x0F, 0, 2, None),   # lui   $v0, suffix-high
        (0x0D, 2, 3, None),   # ori   $v1, $v0, terrain-code
        (0x2E, 16, 3, 19),    # swr   $v1, 19($s0)
        (0x09, 0, 2, None),   # addiu $v0, $zero, use-code
        (0x2A, 16, 3, 22),    # swl   $v1, 22($s0)
        (0x2E, 16, 2, 23),    # swr   $v0, 23($s0)
        (0x04, 0, 0, None),   # b     join
        (0x2A, 16, 2, 26),    # swl   $v0, 26($s0)
    )
    for index, (word, expected) in enumerate(zip(words, expected_fields)):
        opcode, source, target, immediate = _instruction_fields(word)
        expected_opcode, expected_source, expected_target, expected_immediate = (
            expected
        )
        if (
            opcode != expected_opcode
            or source != expected_source
            or target != expected_target
            or (
                expected_immediate is not None
                and immediate != expected_immediate
            )
        ):
            raise MovementTypeLabelError(
                f"{label} instruction {index} no longer matches the runtime "
                "materialization sequence"
            )

    combined_word = ((words[0] & 0xFFFF) << 16) | (words[1] & 0xFFFF)
    use_code = words[3] & 0xFFFF
    return struct.pack("<IH", combined_word, use_code)


def apply_runtime_movement_type_labels(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Replace the stock ``専`` code inside two runtime-built labels."""

    if not isinstance(raw_contract, Mapping):
        raise MovementTypeLabelError("movement-type label contract must be an object")
    if raw_contract.get("member") != "SLPS_258.87":
        raise MovementTypeLabelError("movement-type executable member drift")
    if raw_contract.get("policy") != (
        "replace_runtime_materialized_stock_dedicated_marker"
    ):
        raise MovementTypeLabelError("movement-type label policy drift")

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"), "ELF virtual address base"
    )
    sites = raw_contract.get("sites")
    if not isinstance(sites, list) or len(sites) != 2:
        raise MovementTypeLabelError("movement-type label site inventory drift")

    expected_semantics = {
        "air_only": ("空専用", "空专用"),
        "land_only": ("陸専用", "陆专用"),
    }
    if {site.get("id") for site in sites if isinstance(site, Mapping)} != set(
        expected_semantics
    ):
        raise MovementTypeLabelError("movement-type label site IDs drift")

    output = executable
    reports: list[dict[str, object]] = []
    ranges: list[tuple[int, int]] = []
    total_changed = 0
    for raw_site in sites:
        if not isinstance(raw_site, Mapping):
            raise MovementTypeLabelError("movement-type label site must be an object")
        site_id = raw_site.get("id")
        assert isinstance(site_id, str)
        source_text, translation = expected_semantics[site_id]
        if (
            raw_site.get("source_text") != source_text
            or raw_site.get("translation") != translation
        ):
            raise MovementTypeLabelError(f"{site_id} semantic contract drift")

        file_offset = _number(raw_site.get("file_offset"), f"{site_id} file offset")
        virtual_address = _number(
            raw_site.get("virtual_address"), f"{site_id} virtual address"
        )
        if virtual_address - virtual_base + file_base != file_offset:
            raise MovementTypeLabelError(f"{site_id} ELF virtual/file mapping drift")
        original = _hex_bytes(
            raw_site.get("original_block_hex"),
            f"{site_id} original block",
            size=32,
        )
        replacement = _hex_bytes(
            raw_site.get("replacement_block_hex"),
            f"{site_id} replacement block",
            size=32,
        )
        source_bytes = _hex_bytes(
            raw_site.get("source_materialized_hex"),
            f"{site_id} source materialized text",
            size=6,
        )
        translated_bytes = _hex_bytes(
            raw_site.get("output_materialized_hex"),
            f"{site_id} output materialized text",
            size=6,
        )
        if (
            original == replacement
            or _materialized_text(original, label=f"{site_id} original")
            != source_bytes
            or _materialized_text(replacement, label=f"{site_id} replacement")
            != translated_bytes
        ):
            raise MovementTypeLabelError(f"{site_id} materialized text drift")
        changed_indexes = [
            index
            for index, (before, after) in enumerate(zip(original, replacement))
            if before != after
        ]
        if changed_indexes != [1]:
            raise MovementTypeLabelError(
                f"{site_id} must change only the LUI immediate high byte"
            )
        if file_offset < 0 or file_offset + len(original) > len(output):
            raise MovementTypeLabelError(f"{site_id} block exceeds executable")
        observed = output[file_offset : file_offset + len(original)]
        if observed not in (original, replacement):
            raise MovementTypeLabelError(
                f"{site_id} block preimage drift: {observed.hex().upper()}"
            )
        changed = observed == original
        if changed:
            output = (
                output[:file_offset]
                + replacement
                + output[file_offset + len(replacement) :]
            )
            total_changed += 1
        ranges.append((file_offset, file_offset + len(original)))
        reports.append(
            {
                "id": site_id,
                "source_text": source_text,
                "translation": translation,
                "virtual_address": virtual_address,
                "file_offset": file_offset,
                "source_materialized_hex": source_bytes.hex().upper(),
                "output_materialized_hex": translated_bytes.hex().upper(),
                "original_instruction_hex": original[:4].hex().upper(),
                "replacement_instruction_hex": replacement[:4].hex().upper(),
                "output_instruction_hex": replacement[:4].hex().upper(),
                "changed_byte_count": int(changed),
                "full_materialization_sequence_exact": True,
            }
        )

    changed_offsets = [
        offset
        for offset, (before, after) in enumerate(zip(executable, output))
        if before != after
    ]
    if len(output) != len(executable) or any(
        not any(start <= offset < end for start, end in ranges)
        for offset in changed_offsets
    ):
        raise MovementTypeLabelError("movement-type patch changed bytes outside sites")
    if len(changed_offsets) != total_changed:
        raise MovementTypeLabelError("movement-type changed-byte count drift")

    parallel = raw_contract.get("preserved_parallel_type")
    if not isinstance(parallel, Mapping):
        raise MovementTypeLabelError("parallel movement-type contract is missing")
    parallel_virtual_address = _number(
        parallel.get("virtual_address"), "parallel type virtual address"
    )
    parallel_file_offset = _number(
        parallel.get("file_offset"), "parallel type file offset"
    )
    parallel_encoded = _hex_bytes(
        parallel.get("encoded_hex"), "parallel type encoded text", size=7
    )
    if (
        parallel.get("id") != "air_water"
        or parallel.get("text") != "空水用"
        or parallel_virtual_address - virtual_base + file_base
        != parallel_file_offset
        or output[
            parallel_file_offset : parallel_file_offset + len(parallel_encoded)
        ]
        != parallel_encoded
    ):
        raise MovementTypeLabelError("parallel air-water type drift")

    return output, {
        "policy": raw_contract["policy"],
        "site_count": len(reports),
        "sites": reports,
        "source_suffix": "専用",
        "output_suffix": "专用",
        "preserved_parallel_type": {
            "id": "air_water",
            "text": "空水用",
            "virtual_address": parallel_virtual_address,
            "file_offset": parallel_file_offset,
            "encoded_hex": parallel_encoded.hex().upper(),
            "preserved_byte_exact": True,
        },
        "changed_byte_count": len(changed_offsets),
        "all_materialization_sequences_exact": True,
        "executable_size_preserved": True,
        "all_replacements_exact": True,
    }
