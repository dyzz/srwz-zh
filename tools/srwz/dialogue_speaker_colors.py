"""Fail-closed SLPS patch restoring Chinese dialogue speaker colors."""

from __future__ import annotations

from collections.abc import Mapping

NATIVE_BLOCK = bytes.fromhex("81750000000000008169000000000000")
SPOKEN_ONLY_BLOCK = bytes.fromhex("91410000000000008169000000000000")
LOCALIZED_BLOCK = bytes.fromhex("91410000000000008FE8000000000000")
EDITION_SITES = {
    "original": ("SLPS_258.87", 0x33E258),
    "best": ("SLPS_732.70", 0x33EA48),
    "sp": ("SLPS_259.20", 0x3B0ED8),
}


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
    *,
    encoded_prefixes: Mapping[str, bytes],
) -> tuple[bytes, dict[str, object]]:
    """Apply the locked Original contract using production-encoded prefixes."""

    if not isinstance(raw_contract, Mapping):
        raise DialogueSpeakerColorError(
            "dialogue speaker-color contract must be an object"
        )
    if raw_contract.get("member") != "SLPS_258.87":
        raise DialogueSpeakerColorError("dialogue speaker-color member drift")
    if raw_contract.get("policy") != (
        "replace_dialogue_prefix_recognizer_constants"
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
        "parenthetical_quote": "（",
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
    if original != NATIVE_BLOCK:
        raise DialogueSpeakerColorError("original quote constant block drift")
    if replacement != LOCALIZED_BLOCK:
        raise DialogueSpeakerColorError("replacement quote constant block drift")
    if file_offset != EDITION_SITES["original"][1] or virtual_address != 0x43C7D8:
        raise DialogueSpeakerColorError("dialogue speaker-color site drift")
    output, report = apply_dialogue_speaker_prefixes(
        executable, "original", encoded_prefixes=encoded_prefixes
    )
    report.update({
        "policy": raw_contract["policy"],
        "virtual_address": virtual_address,
        "source_quote": expected_semantics["source_quote"],
        "output_quote": expected_semantics["output_quote"],
        "parenthetical_quote": expected_semantics["parenthetical_quote"],
        "ordinary_dialogue_caller": expected_semantics[
            "ordinary_dialogue_caller"
        ],
        "back_log_caller": expected_semantics["back_log_caller"],
        "ordinary_dialogue_and_back_log_share_recognizer": True,
    })
    return output, report


def _site(edition: str) -> tuple[str, int]:
    try:
        return EDITION_SITES[edition]
    except KeyError as error:
        raise DialogueSpeakerColorError("unknown dialogue speaker-color edition") from error


def _verify_encoding(encoded_prefixes: Mapping[str, bytes]) -> dict[str, str]:
    expected = {"“": LOCALIZED_BLOCK[:2], "（": LOCALIZED_BLOCK[8:10]}
    if not isinstance(encoded_prefixes, Mapping) or dict(encoded_prefixes) != expected:
        raise DialogueSpeakerColorError(
            "dialogue recognizer prefixes disagree with production encoding"
        )
    return {text: raw.hex().upper() for text, raw in expected.items()}


def verify_dialogue_speaker_prefixes(
    executable: bytes, edition: str, *, encoded_prefixes: Mapping[str, bytes]
) -> dict[str, object]:
    """Verify the entire edition-native block against the production encoder."""
    prefix_hex = _verify_encoding(encoded_prefixes)
    member, offset = _site(edition)
    observed = executable[offset:offset + 16]
    if observed != LOCALIZED_BLOCK:
        raise DialogueSpeakerColorError(
            f"{edition} dialogue prefix constant block drift: {observed.hex().upper()}"
        )
    return {
        "edition": edition,
        "member": member,
        "file_offset": offset,
        "replacement_block_hex": LOCALIZED_BLOCK.hex().upper(),
        "encoded_prefix_hex": prefix_hex,
        "prefixes_match_production_encoding": True,
        "replacement_reread_exact": True,
    }


def apply_dialogue_speaker_prefixes(
    executable: bytes, edition: str, *, encoded_prefixes: Mapping[str, bytes]
) -> tuple[bytes, dict[str, object]]:
    """Restore both prefixes, accepting only native, old partial, or fixed blocks."""
    _verify_encoding(encoded_prefixes)
    _, offset = _site(edition)
    observed = executable[offset:offset + 16]
    if observed not in (NATIVE_BLOCK, SPOKEN_ONLY_BLOCK, LOCALIZED_BLOCK):
        raise DialogueSpeakerColorError(
            "dialogue quote constant block preimage drift: " + observed.hex().upper()
        )
    output = executable[:offset] + LOCALIZED_BLOCK + executable[offset + 16:]
    changed = [i for i, (a, b) in enumerate(zip(observed, LOCALIZED_BLOCK)) if a != b]
    if any(i not in (0, 1, 8, 9) for i in changed) or len(output) != len(executable):
        raise DialogueSpeakerColorError("dialogue prefix patch escaped locked bytes")
    report = verify_dialogue_speaker_prefixes(output, edition, encoded_prefixes=encoded_prefixes)
    report.update({
        "original_block_hex": NATIVE_BLOCK.hex().upper(),
        "observed_block_hex": observed.hex().upper(),
        "changed_offsets": [f"0x{offset+i:X}" for i in changed],
        "changed_byte_count": len(changed),
        "already_patched": observed == LOCALIZED_BLOCK,
        "migrated_spoken_quote_only_patch": observed == SPOKEN_ONLY_BLOCK,
        "executable_size_preserved": True,
    })
    return output, report


__all__ = [
    "DialogueSpeakerColorError",
    "apply_dialogue_speaker_quote_constant",
    "apply_dialogue_speaker_prefixes",
    "verify_dialogue_speaker_prefixes",
]
