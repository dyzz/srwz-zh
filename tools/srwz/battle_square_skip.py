"""Fail-closed executable patch: square button skips to the next battle action.

The default-enabled native-tail-r5 hook preserves real resource waits, runs
one world step per frame, and reuses a recognized native cleanup suffix before
ending an animation. Unknown queues use native fast mode. Disabling the build
option restores the retail square-button behavior, with no replacement hook.

The hook is a pre-assembled MIPS blob (source: tools/native/battle-square-skip/
skip_hook.s) placed in an all-zero code cave, plus a handful of retargeted
call/prologue instructions.  Every edition carries its own blob and sites.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping, Sequence

POLICY = "square_skips_battle_animation_via_native_tail"
SITE_IDS = (
    "battle_step_world_call",
    "queue_append_prologue_0",
    "queue_append_prologue_1",
)
STATE_BLOCK_OFFSET = 0x600
STATE_MARKER = 0x4E540005


class BattleSquareSkipError(ValueError):
    """The square-skip contract or the executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise BattleSquareSkipError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise BattleSquareSkipError(f"{label} is not an integer") from error
    raise BattleSquareSkipError(f"{label} must be an integer")


def _hex_bytes(value: object, label: str, length: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise BattleSquareSkipError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise BattleSquareSkipError(f"{label} is not hexadecimal") from error
    if length is not None and len(raw) != length:
        raise BattleSquareSkipError(f"{label} must be {length} bytes")
    return raw


def _jump_word(opcode: int, target: int) -> int:
    if target & 3 or target >> 28:
        raise BattleSquareSkipError(f"jump target 0x{target:X} is not encodable")
    return (opcode << 26) | ((target >> 2) & 0x03FFFFFF)


def edition_contract(raw_contract: Mapping[str, object], edition: str) -> Mapping[str, object]:
    if not isinstance(raw_contract, Mapping):
        raise BattleSquareSkipError("square-skip contract must be an object")
    if raw_contract.get("policy") != POLICY:
        raise BattleSquareSkipError("square-skip policy drift")
    if not isinstance(raw_contract.get("enabled", True), bool):
        raise BattleSquareSkipError("square-skip enabled must be a boolean")
    editions = raw_contract.get("editions")
    if not isinstance(editions, Mapping) or edition not in editions:
        raise BattleSquareSkipError(f"square-skip contract lacks edition {edition!r}")
    contract = editions[edition]
    if not isinstance(contract, Mapping):
        raise BattleSquareSkipError("square-skip edition contract must be an object")
    return contract


def executable_write_ranges(
    raw_contract: Mapping[str, object], edition: str
) -> list[tuple[int, int]]:
    """File-offset ranges [start, end) the patch writes for one edition."""

    contract = edition_contract(raw_contract, edition)
    file_base = _number(contract.get("elf_file_offset_base"), "ELF file offset base")
    virtual_base = _number(contract.get("elf_virtual_address_base"), "ELF virtual base")
    cave = contract.get("cave")
    if not isinstance(cave, Mapping):
        raise BattleSquareSkipError("square-skip cave must be an object")
    cave_address = _number(cave.get("virtual_address"), "cave address")
    cave_size = _number(cave.get("size"), "cave size")
    ranges = [(file_base + cave_address - virtual_base, file_base + cave_address - virtual_base + cave_size)]
    patches = contract.get("patches")
    if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes)):
        raise BattleSquareSkipError("square-skip patches must be a list")
    for site in patches:
        if not isinstance(site, Mapping):
            raise BattleSquareSkipError("square-skip patch site must be an object")
        offset = file_base + _number(site.get("virtual_address"), "site address") - virtual_base
        ranges.append((offset, offset + 4))
    return ranges


def apply_battle_square_skip(
    executable: bytes,
    raw_contract: Mapping[str, object],
    edition: str = "original",
) -> tuple[bytes, dict[str, object]]:
    """Set or verify the configured hook state in ``executable``.

    A pristine executable must show all-zero cave bytes and the retail
    instruction at every site; an already patched executable must show the
    exact blob and replacement instructions.  Anything else fails closed.
    """

    contract = edition_contract(raw_contract, edition)
    enabled = raw_contract.get("enabled", True)
    member = contract.get("member")
    if not isinstance(member, str) or not member.startswith("SLPS_"):
        raise BattleSquareSkipError("square-skip executable member drift")
    file_base = _number(contract.get("elf_file_offset_base"), "ELF file offset base")
    virtual_base = _number(contract.get("elf_virtual_address_base"), "ELF virtual base")
    cave = contract.get("cave")
    if not isinstance(cave, Mapping):
        raise BattleSquareSkipError("square-skip cave must be an object")
    cave_address = _number(cave.get("virtual_address"), "cave address")
    cave_size = _number(cave.get("size"), "cave size")
    blob = _hex_bytes(contract.get("hook_hex"), "hook bytes")
    expected_cave = 0x450780 if edition == 'sp' else 0x3F6000
    if cave_address != expected_cave or cave_size != 0x800:
        raise BattleSquareSkipError("native-tail cave layout drift")
    if len(blob) != STATE_BLOCK_OFFSET + 0xC0:
        raise BattleSquareSkipError("hook blob does not fit the declared cave")
    if hashlib.sha256(blob).hexdigest() != contract.get("hook_sha256"):
        raise BattleSquareSkipError("hook blob hash drift")
    if struct.unpack_from("<I", blob, STATE_BLOCK_OFFSET + 0x1C)[0] != STATE_MARKER:
        raise BattleSquareSkipError("hook state marker drift")
    stubs = contract.get("stub_offsets")
    if not isinstance(stubs, Mapping):
        raise BattleSquareSkipError("square-skip stub offsets must be an object")
    patches = contract.get("patches")
    if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes)):
        raise BattleSquareSkipError("square-skip patches must be a list")
    if [site.get("id") if isinstance(site, Mapping) else None for site in patches] != list(SITE_IDS):
        raise BattleSquareSkipError("square-skip site inventory drift")

    source = bytes(executable)
    output = bytearray(source)
    cave_offset = file_base + cave_address - virtual_base
    if cave_offset < 0 or cave_offset + cave_size > len(source):
        raise BattleSquareSkipError("square-skip cave is outside the executable")
    observed_cave = source[cave_offset : cave_offset + cave_size]
    cave_pristine = not any(observed_cave)
    cave_applied = observed_cave[: len(blob)] == blob and not any(observed_cave[len(blob) :])
    if not (cave_pristine or cave_applied):
        raise BattleSquareSkipError("square-skip cave preimage drift")

    site_reports: list[dict[str, object]] = []
    site_states: list[str] = []
    for site in patches:
        assert isinstance(site, Mapping)
        address = _number(site.get("virtual_address"), "site address")
        offset = file_base + address - virtual_base
        if offset < 0 or offset + 4 > len(source):
            raise BattleSquareSkipError("square-skip site is outside the executable")
        original = _hex_bytes(site.get("original_instruction_hex"), "original instruction", 4)
        kind = site.get("kind")
        if kind in ("jal", "j"):
            target = cave_address + _number(stubs.get(site.get("stub")), "stub offset")
            replacement = struct.pack("<I", _jump_word(3 if kind == "jal" else 2, target))
        elif kind == "nop":
            replacement = b"\0\0\0\0"
        else:
            raise BattleSquareSkipError(f"unsupported square-skip site kind {kind!r}")
        declared = _hex_bytes(site.get("replacement_instruction_hex"), "replacement instruction", 4)
        if declared != replacement:
            raise BattleSquareSkipError(f"square-skip site {site.get('id')} replacement drift")
        observed = source[offset : offset + 4]
        if observed == original:
            state = "pristine"
        elif observed == replacement:
            state = "applied"
        else:
            raise BattleSquareSkipError(f"square-skip site {site.get('id')} preimage drift")
        site_states.append(state)
        output[offset : offset + 4] = replacement if enabled else original
        site_reports.append(
            {
                "id": site.get("id"),
                "surface": site.get("surface"),
                "kind": kind,
                "virtual_address": f"0x{address:06X}",
                "file_offset": f"0x{offset:06X}",
                "original_instruction_hex": original.hex(),
                "replacement_instruction_hex": replacement.hex(),
                "state_before": state,
            }
        )
    if len(set(site_states)) != 1 or (site_states[0] == "applied") != cave_applied:
        raise BattleSquareSkipError("square-skip executable is partially patched")
    already_applied = cave_applied
    output[cave_offset : cave_offset + cave_size] = (
        blob + bytes(cave_size - len(blob)) if enabled else bytes(cave_size)
    )

    changed = sum(1 for a, b in zip(source, output) if a != b)
    report = {
        "policy": POLICY,
        "enabled": enabled,
        "configuration_matches_before": cave_applied == enabled,
        "edition": edition,
        "member": member,
        "cave_virtual_address": f"0x{cave_address:06X}",
        "cave_file_offset": f"0x{cave_offset:06X}",
        "cave_size": cave_size,
        "cave_preimage_all_zero": cave_pristine,
        "hook_size": len(blob),
        "hook_sha256": contract.get("hook_sha256"),
        "state_marker": f"0x{STATE_MARKER:08X}",
        "world_steps_per_frame": 1,
        "native_resource_waits_preserved": True,
        "native_result_processing_preserved": True,
        "site_count": len(site_reports),
        "patches": site_reports,
        "already_applied": already_applied,
        "changed_byte_count": changed,
        "executable_size_preserved": len(output) == len(source),
        "all_replacements_exact": all(
            output[int(site["file_offset"], 0) : int(site["file_offset"], 0) + 4].hex()
            == site["replacement_instruction_hex" if enabled else "original_instruction_hex"]
            for site in site_reports
        ),
    }
    return bytes(output), report


def verify_battle_square_skip(
    executable: bytes,
    raw_contract: Mapping[str, object],
    edition: str = "original",
    component_receipt: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Read-only verification of enabled AND disabled output and its receipt."""
    output, report = apply_battle_square_skip(executable, raw_contract, edition)
    if output != executable or not report["configuration_matches_before"]:
        raise BattleSquareSkipError("square-skip output does not match enabled setting")
    if component_receipt is not None:
        for field in ("policy", "enabled", "edition", "member", "hook_sha256", "site_count",
                      "cave_virtual_address", "cave_size", "state_marker"):
            if component_receipt.get(field) != report[field]:
                raise BattleSquareSkipError(f"square-skip receipt drift: {field}")
        def sites(value):
            return [{k: v for k, v in site.items() if k != "state_before"}
                    for site in value.get("patches", [])]
        if sites(component_receipt) != sites(report):
            raise BattleSquareSkipError("square-skip receipt site drift")
        report["component_receipt_exact"] = True
    return report
