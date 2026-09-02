"""Fail-closed SLPS patch restoring Chinese dialogue speaker colors."""

from __future__ import annotations

from collections.abc import Mapping


class DialogueSpeakerColorError(ValueError):
    """The dialogue quote-recognizer contract or executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise DialogueSpeakerColorError(
                f"{label} is not an integer"
            ) from error
    raise DialogueSpeakerColorError(f"{label} must be an integer")


def _hex_bytes(value: object, label: str, *, size: int) -> bytes:
    if not isinstance(value, str):
        raise DialogueSpeakerColorError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise DialogueSpeakerColorError(
            f"{label} is not hexadecimal"
        ) from error
    if len(raw) != size:
        raise DialogueSpeakerColorError(
            f"{label} must contain exactly {size} bytes"
        )
    return raw


def apply_dialogue_speaker_quote_constant(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Replace the localized build's Japanese spoken-quote recognizer constant."""

    if not isinstance(raw_contract, Mapping):
        raise DialogueSpeakerColorError(
            "dialogue speaker-color contract must be an object"
        )
    if raw_contract.get("member") != "SLPS_258.87":
        raise DialogueSpeakerColorError("dialogue speaker-color member drift")
    if raw_contract.get("policy") != (
        "replace_japanese_spoken_quote_recognizer_constant"
    ):
        raise DialogueSpeakerColorError("dialogue speaker-color policy drift")

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    file_offset = _number(raw_contract.get("file_offset"), "file offset")
    virtual_address = _number(
        raw_contract.get("virtual_address"), "virtual address"
    )
    if virtual_address - virtual_base + file_base != file_offset:
        raise DialogueSpeakerColorError(
            "dialogue speaker-color ELF virtual/file mapping drift"
        )

    expected_semantics = {
        "source_quote": "「",
        "output_quote": "“",
        "preserved_parenthetical_quote": "（",
        "ordinary_dialogue_caller": "0x22135C",
        "back_log_caller": "0x1D84AC->0x220F60",
    }
    if any(
        raw_contract.get(key) != value
        for key, value in expected_semantics.items()
    ):
        raise DialogueSpeakerColorError(
            "dialogue speaker-color semantic contract drift"
        )

    block_size = 16
    original = _hex_bytes(
        raw_contract.get("original_block_hex"),
        "original quote constant block",
        size=block_size,
    )
    replacement = _hex_bytes(
        raw_contract.get("replacement_block_hex"),
        "replacement quote constant block",
        size=block_size,
    )
    if original != bytes.fromhex("81750000000000008169000000000000"):
        raise DialogueSpeakerColorError("original quote constant block drift")
    if replacement != bytes.fromhex("91410000000000008169000000000000"):
        raise DialogueSpeakerColorError("replacement quote constant block drift")

    changed_indexes = [
        index
        for index, (before, after) in enumerate(zip(original, replacement))
        if before != after
    ]
    if changed_indexes != [0, 1]:
        raise DialogueSpeakerColorError(
            "dialogue quote patch must change exactly the first two bytes"
        )
    if original[8:] != replacement[8:] or replacement[8:12] != bytes.fromhex(
        "81690000"
    ):
        raise DialogueSpeakerColorError(
            "parenthetical dialogue recognizer constant drift"
        )
    if file_offset < 0 or file_offset + block_size > len(executable):
        raise DialogueSpeakerColorError(
            "dialogue quote constant block exceeds executable"
        )

    observed = executable[file_offset : file_offset + block_size]
    if observed not in (original, replacement):
        raise DialogueSpeakerColorError(
            "dialogue quote constant block preimage drift: "
            + observed.hex().upper()
        )
    already_patched = observed == replacement
    output = bytearray(executable)
    if not already_patched:
        output[file_offset : file_offset + block_size] = replacement
    output_bytes = bytes(output)

    changed_offsets = [
        offset
        for offset, (before, after) in enumerate(zip(executable, output_bytes))
        if before != after
    ]
    expected_changed_offsets = (
        []
        if already_patched
        else [file_offset + index for index in changed_indexes]
    )
    if changed_offsets != expected_changed_offsets:
        raise DialogueSpeakerColorError(
            "dialogue quote patch changed bytes outside the locked constant"
        )
    if output_bytes[file_offset : file_offset + block_size] != replacement:
        raise DialogueSpeakerColorError(
            "dialogue quote replacement reread mismatch"
        )

    return output_bytes, {
        "policy": raw_contract["policy"],
        "virtual_address": virtual_address,
        "file_offset": file_offset,
        "source_quote": expected_semantics["source_quote"],
        "output_quote": expected_semantics["output_quote"],
        "preserved_parenthetical_quote": expected_semantics[
            "preserved_parenthetical_quote"
        ],
        "ordinary_dialogue_caller": expected_semantics[
            "ordinary_dialogue_caller"
        ],
        "back_log_caller": expected_semantics["back_log_caller"],
        "original_block_hex": original.hex().upper(),
        "replacement_block_hex": replacement.hex().upper(),
        "changed_offsets": [f"0x{offset:X}" for offset in changed_offsets],
        "changed_byte_count": len(changed_offsets),
        "already_patched": already_patched,
        "parenthetical_quote_preserved_byte_exact": (
            output_bytes[file_offset + 8 : file_offset + 12]
            == original[8:12]
        ),
        "replacement_reread_exact": True,
        "ordinary_dialogue_and_back_log_share_recognizer": True,
        "executable_size_preserved": len(output_bytes) == len(executable),
    }


__all__ = [
    "DialogueSpeakerColorError",
    "apply_dialogue_speaker_quote_constant",
]
