"""Fail-closed audit and executable patch for the sound-select track list."""

from __future__ import annotations

import hashlib
import struct
from collections import Counter
from typing import Mapping, Sequence


class SoundSelectError(ValueError):
    """The sound-select unlock contract or its retail preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise SoundSelectError(f"{label} is not an integer") from error
    raise SoundSelectError(f"{label} must be an integer")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _instruction_bytes(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise SoundSelectError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise SoundSelectError(f"{label} is not hexadecimal") from error
    if len(raw) != 4:
        raise SoundSelectError(f"{label} must encode one MIPS instruction")
    return raw


def _branch_target(instruction: bytes, virtual_address: int) -> int:
    word = struct.unpack("<I", instruction)[0]
    opcode = word >> 26
    if opcode != 0x04:
        raise SoundSelectError("unlock instruction is not a MIPS beq branch")
    immediate = word & 0xFFFF
    if immediate & 0x8000:
        immediate -= 0x10000
    return virtual_address + 4 + immediate * 4


def apply_sound_select_default_unlock(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Bypass save-progress rules while retaining the empty-record guard."""

    if not isinstance(raw_contract, Mapping):
        raise SoundSelectError("sound-select unlock contract must be an object")
    if raw_contract.get("policy") != (
        "include_all_nonempty_tracks_without_save_progress"
    ):
        raise SoundSelectError("sound-select unlock policy drift")

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    virtual_address = _number(
        raw_contract.get("virtual_address"), "unlock virtual address"
    )
    file_offset = _number(raw_contract.get("file_offset"), "unlock file offset")
    if virtual_address - virtual_base + file_base != file_offset:
        raise SoundSelectError("unlock ELF virtual/file offset mapping drift")

    original = _instruction_bytes(
        raw_contract.get("original_instruction_hex"),
        "original unlock instruction",
    )
    replacement = _instruction_bytes(
        raw_contract.get("replacement_instruction_hex"),
        "replacement unlock instruction",
    )
    original_target = _number(
        raw_contract.get("original_branch_target"),
        "original branch target",
    )
    replacement_target = _number(
        raw_contract.get("replacement_branch_target"),
        "replacement branch target",
    )
    if _branch_target(original, virtual_address) != original_target:
        raise SoundSelectError("original sound-select branch target drift")
    if _branch_target(replacement, virtual_address) != replacement_target:
        raise SoundSelectError("replacement sound-select branch target drift")
    if file_offset < 0 or file_offset + 4 > len(executable):
        raise SoundSelectError("unlock instruction exceeds executable")

    source = bytes(executable)
    observed = source[file_offset : file_offset + 4]
    if observed not in (original, replacement):
        raise SoundSelectError(
            "sound-select unlock instruction preimage drift: "
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
        "original_instruction_hex": original.hex().upper(),
        "replacement_instruction_hex": replacement.hex().upper(),
        "original_branch_target": f"0x{original_target:X}",
        "replacement_branch_target": f"0x{replacement_target:X}",
        "source_instruction_hex": observed.hex().upper(),
        "output_instruction_hex": output[
            file_offset : file_offset + 4
        ].hex().upper(),
        "already_patched": already_patched,
        "changed_instruction_count": 0 if already_patched else 1,
        "changed_byte_count": changed_byte_count,
        "source_size": len(source),
        "output_size": len(output),
        "source_sha256": _sha256(source),
        "output_sha256": _sha256(output),
        "instruction_replacement_exact": (
            output[file_offset : file_offset + 4] == replacement
        ),
        "executable_size_preserved": len(output) == len(source),
    }


def audit_sound_select_track_metadata(
    decoded_compdata: bytes,
    titles: Sequence[object],
    raw_contract: Mapping[str, object],
) -> dict[str, object]:
    """Bind the 101 title strings to their 102-row selection metadata table."""

    metadata = raw_contract.get("metadata")
    if not isinstance(metadata, Mapping):
        raise SoundSelectError("sound-select metadata contract must be an object")
    table_start = _number(metadata.get("decoded_table_start"), "metadata start")
    record_size = _number(metadata.get("record_size"), "metadata record size")
    record_count = _number(metadata.get("record_count"), "metadata record count")
    title_count = _number(
        metadata.get("title_record_count"), "metadata title count"
    )
    sentinel_index = _number(
        metadata.get("empty_sentinel_record_index"), "metadata sentinel index"
    )
    flag_offset = _number(
        metadata.get("availability_flag_offset"), "availability flag offset"
    )
    flag_mask = _number(
        metadata.get("availability_flag_mask"), "availability flag mask"
    )
    runtime_base = _number(
        metadata.get("decoded_runtime_base"), "decoded COMPDATA runtime base"
    )
    if record_size != 12 or flag_offset != 8:
        raise SoundSelectError("unsupported sound-select metadata layout")
    if title_count != len(titles) or sentinel_index != title_count:
        raise SoundSelectError("sound-select title/sentinel count drift")
    if record_count != title_count + 1:
        raise SoundSelectError("sound-select metadata record count drift")
    table_end = table_start + record_size * record_count
    source = bytes(decoded_compdata)
    if table_start < 0 or table_end > len(source):
        raise SoundSelectError("sound-select metadata table exceeds COMPDATA")
    table = source[table_start:table_end]
    expected_hash = metadata.get("expected_table_sha256")
    if not isinstance(expected_hash, str) or _sha256(table) != expected_hash:
        raise SoundSelectError("sound-select metadata table SHA-256 drift")

    records = [
        struct.unpack_from("<IHHI", table, index * record_size)
        for index in range(record_count)
    ]
    pointer_mismatches = []
    track_id_mismatches = []
    for index, (title, record) in enumerate(zip(titles, records)):
        title_start = getattr(title, "start", None)
        if not isinstance(title_start, int):
            raise SoundSelectError("sound-select title row has no start offset")
        if record[0] != runtime_base + title_start:
            pointer_mismatches.append(index)
        if record[2] != index:
            track_id_mismatches.append(index)

    observed_rule_counts = Counter(record[3] & flag_mask for record in records)
    expected_rule_counts_raw = metadata.get("expected_rule_counts")
    if not isinstance(expected_rule_counts_raw, Mapping):
        raise SoundSelectError("sound-select expected rule counts are invalid")
    expected_rule_counts = {
        _number(key, "availability rule"): _number(value, "rule count")
        for key, value in expected_rule_counts_raw.items()
    }
    if dict(observed_rule_counts) != expected_rule_counts:
        raise SoundSelectError("sound-select availability rule counts drift")
    if pointer_mismatches or track_id_mismatches:
        raise SoundSelectError(
            "sound-select title metadata binding drift: "
            f"pointers={pointer_mismatches}, ids={track_id_mismatches}"
        )
    if any((record[3] & flag_mask) == 0 for record in records[:title_count]):
        raise SoundSelectError("a sound-select title record is marked empty")
    if records[sentinel_index][3] & flag_mask:
        raise SoundSelectError("sound-select sentinel is not marked empty")

    return {
        "decoded_table_start": f"0x{table_start:X}",
        "decoded_table_end": f"0x{table_end:X}",
        "record_size": record_size,
        "record_count": record_count,
        "title_record_count": title_count,
        "empty_sentinel_record_index": sentinel_index,
        "table_sha256": _sha256(table),
        "availability_rule_counts": {
            str(key): observed_rule_counts[key]
            for key in sorted(observed_rule_counts)
        },
        "all_title_pointers_exact": True,
        "all_track_ids_sequential": True,
        "all_title_records_nonempty": True,
        "empty_sentinel_excluded": True,
        "default_unlocked_track_count": title_count,
    }


__all__ = [
    "SoundSelectError",
    "apply_sound_select_default_unlock",
    "audit_sound_select_track_metadata",
]
