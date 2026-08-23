"""Patch and audit weapon special-effect-2 labels built inside SLPS code."""

from __future__ import annotations

import hashlib
import struct
from typing import Mapping, Sequence

from .text import TextTable, decode_text, encode_text, project_runtime_text_table


class WeaponSpecialEffectError(ValueError):
    """The inline weapon-effect contract or its executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise WeaponSpecialEffectError(f"{label} is not an integer") from error
    raise WeaponSpecialEffectError(f"{label} must be an integer")


def _instruction(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise WeaponSpecialEffectError(f"{label} must be hexadecimal text")
    try:
        data = bytes.fromhex(value)
    except ValueError as error:
        raise WeaponSpecialEffectError(f"{label} is not hexadecimal") from error
    if len(data) != 4:
        raise WeaponSpecialEffectError(f"{label} must encode one instruction")
    return data


def _word(data: bytes) -> int:
    return struct.unpack("<I", data)[0]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_builder(builder: Mapping[str, object], label: str) -> None:
    ori = _word(_instruction(builder.get("ori_original_hex"), f"{label} ORI"))
    if ori >> 26 != 0x0D:
        raise WeaponSpecialEffectError(f"{label} does not end in MIPS ORI")
    lui_hex = builder.get("lui_original_hex")
    if lui_hex is None:
        if (ori >> 21) & 0x1F:
            raise WeaponSpecialEffectError(f"{label} single ORI does not read $zero")
        return
    lui = _word(_instruction(lui_hex, f"{label} LUI"))
    if lui >> 26 != 0x0F or (lui >> 21) & 0x1F:
        raise WeaponSpecialEffectError(f"{label} does not start with MIPS LUI")
    if ((ori >> 21) & 0x1F) != ((lui >> 16) & 0x1F):
        raise WeaponSpecialEffectError(f"{label} LUI/ORI register flow drift")


def _replacement_instruction(original: bytes, immediate: int) -> bytes:
    if not 0 <= immediate <= 0xFFFF:
        raise WeaponSpecialEffectError("MIPS immediate does not fit 16 bits")
    return struct.pack("<I", (_word(original) & 0xFFFF0000) | immediate)


def _builder_instructions(
    builder: Mapping[str, object],
    *,
    chunk: bytes,
) -> tuple[tuple[int, bytes, bytes], ...]:
    if len(chunk) != 4:
        raise WeaponSpecialEffectError("inline string chunk is not four bytes")
    runtime_word = int.from_bytes(chunk, "little")
    ori_offset = _number(builder.get("ori_file_offset"), "ORI file offset")
    ori_original = _instruction(builder.get("ori_original_hex"), "original ORI")
    lui_hex = builder.get("lui_original_hex")
    if lui_hex is None:
        if runtime_word >> 16:
            raise WeaponSpecialEffectError(
                "single-ORI string chunk has a nonzero upper halfword"
            )
        return (
            (
                ori_offset,
                ori_original,
                _replacement_instruction(ori_original, runtime_word),
            ),
        )
    lui_offset = _number(builder.get("lui_file_offset"), "LUI file offset")
    lui_original = _instruction(lui_hex, "original LUI")
    return (
        (
            lui_offset,
            lui_original,
            _replacement_instruction(lui_original, runtime_word >> 16),
        ),
        (
            ori_offset,
            ori_original,
            _replacement_instruction(ori_original, runtime_word & 0xFFFF),
        ),
    )


def _read_builder_chunk(
    executable: bytes, builder: Mapping[str, object]
) -> bytes:
    ori_offset = _number(builder.get("ori_file_offset"), "ORI file offset")
    if ori_offset < 0 or ori_offset + 4 > len(executable):
        raise WeaponSpecialEffectError("ORI instruction exceeds executable")
    ori = _word(executable[ori_offset : ori_offset + 4])
    low = ori & 0xFFFF
    if builder.get("lui_original_hex") is None:
        runtime_word = low
    else:
        lui_offset = _number(builder.get("lui_file_offset"), "LUI file offset")
        if lui_offset < 0 or lui_offset + 4 > len(executable):
            raise WeaponSpecialEffectError("LUI instruction exceeds executable")
        runtime_word = ((_word(executable[lui_offset : lui_offset + 4]) & 0xFFFF) << 16) | low
    return runtime_word.to_bytes(4, "little")


def _decode_slot(data: bytes, table: TextTable) -> tuple[str, int]:
    decoded = decode_text(data, 0, table, end=len(data))
    if decoded.terminator != "nul" or any(data[decoded.consumed :]):
        raise WeaponSpecialEffectError("inline effect string padding is not zero")
    return decoded.text, decoded.consumed


def apply_weapon_special_effect_2(
    executable: bytes,
    raw_contract: Mapping[str, object],
    corpus: Mapping[str, object],
    *,
    source_table: TextTable,
    encoding_overrides: Mapping[str, int],
) -> tuple[bytes, dict[str, object]]:
    """Translate both effect-2 names without changing control flow or layout."""

    if raw_contract.get("strategy") != "slps-inline-mips-immediate-strings":
        raise WeaponSpecialEffectError("weapon effect-2 strategy drift")
    raw_fields = raw_contract.get("fields")
    raw_entries = corpus.get("entries")
    expected = raw_contract.get("expected")
    if (
        not isinstance(raw_fields, Sequence)
        or isinstance(raw_fields, (str, bytes))
        or not isinstance(raw_entries, Sequence)
        or isinstance(raw_entries, (str, bytes))
        or not isinstance(expected, Mapping)
    ):
        raise WeaponSpecialEffectError("weapon effect-2 contract is incomplete")
    if (
        len(raw_fields) != expected.get("entry_count")
        or len(raw_entries) != expected.get("entry_count")
    ):
        raise WeaponSpecialEffectError("weapon effect-2 entry count drift")
    entries = {
        row.get("id"): row
        for row in raw_entries
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    if len(entries) != len(raw_entries):
        raise WeaponSpecialEffectError("weapon effect-2 corpus IDs are invalid")

    output_table = project_runtime_text_table(source_table, encoding_overrides)
    source = bytes(executable)
    output = bytearray(source)
    reports = []
    all_instruction_offsets: set[int] = set()
    for raw_field in raw_fields:
        if not isinstance(raw_field, Mapping):
            raise WeaponSpecialEffectError("weapon effect-2 field is invalid")
        field_id = raw_field.get("id")
        entry = entries.get(field_id)
        if entry is None:
            raise WeaponSpecialEffectError(f"missing weapon effect-2 corpus row: {field_id}")
        source_text = entry.get("source")
        translation = entry.get("translation")
        builders = raw_field.get("word_builders")
        capacity = _number(raw_field.get("capacity_bytes"), "effect capacity")
        if (
            not isinstance(source_text, str)
            or not source_text
            or not isinstance(translation, str)
            or not translation
            or not isinstance(builders, Sequence)
            or isinstance(builders, (str, bytes))
            or capacity != len(builders) * 4
        ):
            raise WeaponSpecialEffectError(f"weapon effect-2 field drift: {field_id}")
        for index, builder in enumerate(builders):
            if not isinstance(builder, Mapping):
                raise WeaponSpecialEffectError("weapon effect-2 builder is invalid")
            _validate_builder(builder, f"{field_id} builder {index}")

        source_slot = b"".join(
            _read_builder_chunk(source, builder) for builder in builders
        )
        encoded_source = encode_text(source_text, source_table, terminate=True)
        if len(encoded_source) > capacity:
            raise WeaponSpecialEffectError(f"source effect exceeds slot: {field_id}")
        padded_source = encoded_source.ljust(capacity, b"\0")
        encoded_translation = encode_text(
            translation,
            source_table,
            overrides=encoding_overrides,
            terminate=True,
        )
        if len(encoded_translation) > capacity:
            raise WeaponSpecialEffectError(
                f"translated effect exceeds slot: {field_id}"
            )
        padded_translation = encoded_translation.ljust(capacity, b"\0")

        original_instructions: list[tuple[int, bytes]] = []
        replacement_instructions: list[tuple[int, bytes]] = []
        for builder, chunk in zip(
            builders,
            (
                padded_translation[index : index + 4]
                for index in range(0, capacity, 4)
            ),
        ):
            for offset, original, replacement in _builder_instructions(
                builder, chunk=chunk
            ):
                if offset in all_instruction_offsets:
                    raise WeaponSpecialEffectError(
                        "weapon effect-2 instruction offset is shared"
                    )
                all_instruction_offsets.add(offset)
                original_instructions.append((offset, original))
                replacement_instructions.append((offset, replacement))

        observed_original = all(
            source[offset : offset + 4] == instruction
            for offset, instruction in original_instructions
        )
        observed_replacement = all(
            source[offset : offset + 4] == instruction
            for offset, instruction in replacement_instructions
        )
        if not observed_original and not observed_replacement:
            raise WeaponSpecialEffectError(
                f"weapon effect-2 instruction preimage drift: {field_id}"
            )
        expected_slot = padded_source if observed_original else padded_translation
        if source_slot != expected_slot:
            raise WeaponSpecialEffectError(
                f"weapon effect-2 assembled string drift: {field_id}"
            )
        for offset, replacement in replacement_instructions:
            output[offset : offset + 4] = replacement

        output_slot = b"".join(
            _read_builder_chunk(bytes(output), builder) for builder in builders
        )
        output_text, output_consumed = _decode_slot(output_slot, output_table)
        if output_slot != padded_translation or output_text != translation:
            raise WeaponSpecialEffectError(
                f"weapon effect-2 translated readback drift: {field_id}"
            )
        reports.append(
            {
                "id": field_id,
                "condition_flag_mask": f"0x{_number(raw_field.get('condition_flag_mask'), 'condition mask'):X}",
                "source": source_text,
                "translation": translation,
                "capacity_bytes": capacity,
                "encoded_translation_size": len(encoded_translation),
                "output_consumed": output_consumed,
                "headroom": capacity - len(encoded_translation),
                "instruction_count": len(replacement_instructions),
                "changed_instruction_count": sum(
                    original != replacement
                    for (_offset, original), (_same_offset, replacement) in zip(
                        original_instructions,
                        replacement_instructions,
                    )
                ),
                "already_patched": observed_replacement,
                "translated_reread_exact": True,
                "zero_padding_preserved": True,
            }
        )

    output_bytes = bytes(output)
    changed_offsets = [
        index for index, (before, after) in enumerate(zip(source, output_bytes))
        if before != after
    ]
    allowed_offsets = {
        offset + byte_index
        for raw_field in raw_fields
        for builder in raw_field["word_builders"]
        for key in ("lui_file_offset", "ori_file_offset")
        if builder.get(key) is not None
        for offset in [_number(builder[key], key)]
        for byte_index in range(4)
    }
    if any(offset not in allowed_offsets for offset in changed_offsets):
        raise WeaponSpecialEffectError("weapon effect-2 changed bytes outside instructions")
    if (
        sum(row["instruction_count"] for row in reports)
        != expected.get("instruction_count")
        or [row["source"] for row in reports] != expected.get("source_labels")
        or [row["translation"] for row in reports]
        != expected.get("translated_labels")
    ):
        raise WeaponSpecialEffectError("weapon effect-2 expected inventory drift")
    return output_bytes, {
        "strategy": raw_contract["strategy"],
        "entry_count": len(reports),
        "entries": reports,
        "changed_byte_count": len(changed_offsets),
        "changed_instruction_count": sum(
            row["changed_instruction_count"]
            for row in reports
            if not row["already_patched"]
        ),
        "source_size": len(source),
        "output_size": len(output_bytes),
        "source_sha256": _sha256(source),
        "output_sha256": _sha256(output_bytes),
        "instruction_offsets": [f"0x{offset:X}" for offset in sorted(all_instruction_offsets)],
        "all_translated_reread_exact": True,
        "control_flow_preserved": True,
        "executable_size_preserved": len(output_bytes) == len(source),
    }


__all__ = [
    "WeaponSpecialEffectError",
    "apply_weapon_special_effect_2",
]
