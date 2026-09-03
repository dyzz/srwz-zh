"""Fail-closed executable patches for the post-game mode selector."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping, Sequence


class GameModeUnlockError(ValueError):
    """The mode-unlock contract or retail executable preimage drifted."""


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise GameModeUnlockError(f"{label} is not an integer") from error
    raise GameModeUnlockError(f"{label} must be an integer")


def _instruction(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise GameModeUnlockError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise GameModeUnlockError(f"{label} is not hexadecimal") from error
    if len(raw) != 4:
        raise GameModeUnlockError(f"{label} must encode one instruction")
    return raw


def _signed_halfword(value: object, label: str) -> int:
    number = _number(value, label)
    if not -0x8000 <= number <= 0x7FFF:
        raise GameModeUnlockError(f"{label} is outside signed 16-bit range")
    return number


def _is_beq_to_unconditional_branch(original: bytes, replacement: bytes) -> bool:
    original_word = struct.unpack("<I", original)[0]
    replacement_word = struct.unpack("<I", replacement)[0]
    original_opcode = original_word >> 26
    replacement_opcode = replacement_word >> 26
    original_registers = (original_word >> 16) & 0x3FF
    replacement_registers = (replacement_word >> 16) & 0x3FF
    return (
        original_opcode == 0x04
        and replacement_opcode == 0x04
        and original_registers != 0
        and replacement_registers == 0
        and (original_word & 0xFFFF) == (replacement_word & 0xFFFF)
    )


def _is_immediate_retarget(
    original: bytes,
    replacement: bytes,
    *,
    kind: object,
) -> bool:
    """Validate a color-site instruction without changing its operation."""

    original_word = struct.unpack("<I", original)[0]
    replacement_word = struct.unpack("<I", replacement)[0]
    opcode = original_word >> 26
    expected_opcode = {
        "store_offset": 0x28,  # sb rt, immediate(base)
        "immediate_value": 0x09,  # addiu rt, rs, immediate
        "preserved_immediate_value": 0x09,
    }.get(kind)
    opcode_and_registers_match = (
        expected_opcode is not None
        and opcode == expected_opcode
        and replacement_word >> 26 == expected_opcode
        and (original_word & 0xFFFF0000) == (replacement_word & 0xFFFF0000)
    )
    if kind == "preserved_immediate_value":
        return opcode_and_registers_match and original_word == replacement_word
    return opcode_and_registers_match and (
        (original_word & 0xFFFF) != (replacement_word & 0xFFFF)
    )


def apply_postgame_mode_unlock(
    executable: bytes,
    raw_contract: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    """Unlock SP and retarget the selector's localized color writes.

    EX is already selectable whenever the retail post-game mode selector is
    reached.  The six locked branches are all SP surfaces: row styling, help
    text layout/content, and confirm-button acceptance.  The retail selector
    also mutates color-control parameters at byte offsets tied to the Japanese
    string lengths; those stores must follow the localized controls instead of
    overwriting visible double-byte glyphs.
    """

    if not isinstance(raw_contract, Mapping):
        raise GameModeUnlockError("post-game mode unlock contract must be an object")
    if raw_contract.get("member") != "SLPS_258.87":
        raise GameModeUnlockError("post-game mode executable member drift")
    if raw_contract.get("policy") != (
        "unlock_mode_selector_rows_without_save_flag_writeback"
    ):
        raise GameModeUnlockError("post-game mode unlock policy drift")

    file_base = _number(
        raw_contract.get("elf_file_offset_base"), "ELF file offset base"
    )
    virtual_base = _number(
        raw_contract.get("elf_virtual_address_base"),
        "ELF virtual address base",
    )
    patches = raw_contract.get("patches")
    if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes)):
        raise GameModeUnlockError("post-game mode unlock patches must be a list")

    required_sites = {
        "sp_row_enable_on_enter",
        "sp_row_enable_on_refresh",
        "sp_row_selected_style",
        "sp_help_text",
        "sp_help_text_layout",
        "sp_confirm_acceptance",
    }
    if len(patches) != len(required_sites):
        raise GameModeUnlockError("post-game mode unlock site inventory drift")

    source = bytes(executable)
    output = bytearray(source)
    reports: list[dict[str, object]] = []
    seen_sites: set[str] = set()
    seen_offsets: set[int] = set()
    for raw_patch in patches:
        if not isinstance(raw_patch, Mapping):
            raise GameModeUnlockError("post-game mode unlock patch must be an object")
        site = raw_patch.get("id")
        if not isinstance(site, str) or not site:
            raise GameModeUnlockError("post-game mode unlock ID must be non-empty")
        if site in seen_sites:
            raise GameModeUnlockError(f"duplicate post-game mode unlock site: {site}")
        seen_sites.add(site)

        virtual_address = _number(
            raw_patch.get("virtual_address"), f"{site} virtual address"
        )
        file_offset = _number(raw_patch.get("file_offset"), f"{site} file offset")
        if virtual_address - virtual_base + file_base != file_offset:
            raise GameModeUnlockError(f"{site} ELF virtual/file mapping drift")
        if file_offset in seen_offsets:
            raise GameModeUnlockError(
                f"duplicate post-game mode unlock offset: 0x{file_offset:X}"
            )
        seen_offsets.add(file_offset)
        if file_offset < 0 or file_offset + 4 > len(output):
            raise GameModeUnlockError(f"{site} instruction exceeds executable")

        original = _instruction(
            raw_patch.get("original_instruction_hex"),
            f"{site} original instruction",
        )
        replacement = _instruction(
            raw_patch.get("replacement_instruction_hex"),
            f"{site} replacement instruction",
        )
        if not _is_beq_to_unconditional_branch(original, replacement):
            raise GameModeUnlockError(
                f"{site} is not a BEQ-to-unconditional-branch replacement"
            )
        observed = bytes(output[file_offset : file_offset + 4])
        if observed not in (original, replacement):
            raise GameModeUnlockError(
                f"{site} instruction preimage drift: expected "
                f"{original.hex().upper()}, got {observed.hex().upper()}"
            )
        already_patched = observed == replacement
        output[file_offset : file_offset + 4] = replacement
        reports.append(
            {
                "id": site,
                "surface": raw_patch.get("surface"),
                "virtual_address": f"0x{virtual_address:X}",
                "file_offset": f"0x{file_offset:X}",
                "original_instruction_hex": original.hex().upper(),
                "replacement_instruction_hex": replacement.hex().upper(),
                "source_instruction_hex": observed.hex().upper(),
                "output_instruction_hex": bytes(
                    output[file_offset : file_offset + 4]
                ).hex().upper(),
                "already_patched": already_patched,
                "changed": not already_patched,
                "branch_target_preserved": True,
            }
        )

    if seen_sites != required_sites:
        raise GameModeUnlockError(
            "post-game mode unlock site set drift: "
            f"missing={sorted(required_sites - seen_sites)}, "
            f"extra={sorted(seen_sites - required_sites)}"
        )

    color_patches = raw_contract.get("runtime_color_patches")
    if not isinstance(color_patches, Sequence) or isinstance(
        color_patches, (str, bytes)
    ):
        raise GameModeUnlockError("mode runtime color patches must be a list")
    required_color_sites = {
        "ex_selected_line1_base_end",
        "ex_selected_line1_base_after_parts",
        "ex_selected_line1_base_after_upgrade",
        "ex_selected_line1_red_no_purchase",
        "ex_selected_line1_red_no_training",
        "ex_selected_line1_red_no_upgrade",
        "ex_selected_line2_base_after_upgraded",
        "ex_selected_line2_red_hard",
        "ex_selected_line2_red_upgraded",
        "ex_unselected_line1_base_end",
        "ex_unselected_line1_special_no_purchase",
        "ex_unselected_line1_base_after_parts",
        "ex_unselected_line1_special_no_training",
        "ex_unselected_line1_base_after_upgrade",
        "ex_unselected_line1_special_no_upgrade",
        "ex_unselected_line2_special_hard",
        "ex_unselected_line2_base_after_upgraded",
        "ex_unselected_line2_special_upgraded",
        "sp_selected_special_color",
        "sp_selected_line1_green_upgrade_limit",
        "sp_selected_line2_green_all_parts",
        "sp_unselected_line1_special",
        "sp_unselected_line2_special",
    }
    if len(color_patches) != len(required_color_sites):
        raise GameModeUnlockError("mode runtime color site inventory drift")

    color_reports: list[dict[str, object]] = []
    seen_color_sites: set[str] = set()
    for raw_patch in color_patches:
        if not isinstance(raw_patch, Mapping):
            raise GameModeUnlockError("mode runtime color patch must be an object")
        site = raw_patch.get("id")
        if not isinstance(site, str) or not site:
            raise GameModeUnlockError("mode runtime color ID must be non-empty")
        if site in seen_color_sites:
            raise GameModeUnlockError(f"duplicate mode runtime color site: {site}")
        seen_color_sites.add(site)

        virtual_address = _number(
            raw_patch.get("virtual_address"), f"{site} virtual address"
        )
        file_offset = _number(raw_patch.get("file_offset"), f"{site} file offset")
        if virtual_address - virtual_base + file_base != file_offset:
            raise GameModeUnlockError(f"{site} ELF virtual/file mapping drift")
        if file_offset in seen_offsets:
            raise GameModeUnlockError(
                f"duplicate post-game mode patch offset: 0x{file_offset:X}"
            )
        seen_offsets.add(file_offset)
        if file_offset < 0 or file_offset + 4 > len(output):
            raise GameModeUnlockError(f"{site} instruction exceeds executable")

        original = _instruction(
            raw_patch.get("original_instruction_hex"),
            f"{site} original instruction",
        )
        replacement = _instruction(
            raw_patch.get("replacement_instruction_hex"),
            f"{site} replacement instruction",
        )
        kind = raw_patch.get("kind")
        if not _is_immediate_retarget(original, replacement, kind=kind):
            raise GameModeUnlockError(
                f"{site} is not a supported MIPS immediate retarget"
            )
        observed = bytes(output[file_offset : file_offset + 4])
        if observed not in (original, replacement):
            raise GameModeUnlockError(
                f"{site} instruction preimage drift: expected "
                f"{original.hex().upper()}, got {observed.hex().upper()}"
            )
        already_patched = observed == replacement
        output[file_offset : file_offset + 4] = replacement
        color_reports.append(
            {
                "id": site,
                "surface": raw_patch.get("surface"),
                "kind": kind,
                "virtual_address": f"0x{virtual_address:X}",
                "file_offset": f"0x{file_offset:X}",
                "original_instruction_hex": original.hex().upper(),
                "replacement_instruction_hex": replacement.hex().upper(),
                "source_instruction_hex": observed.hex().upper(),
                "output_instruction_hex": bytes(
                    output[file_offset : file_offset + 4]
                ).hex().upper(),
                "source_immediate": struct.unpack("<I", observed)[0] & 0xFFFF,
                "replacement_immediate": (
                    struct.unpack("<I", replacement)[0] & 0xFFFF
                ),
                "already_patched": already_patched,
                "changed": not already_patched,
                "opcode_and_registers_preserved": True,
            }
        )

    if seen_color_sites != required_color_sites:
        raise GameModeUnlockError(
            "mode runtime color site set drift: "
            f"missing={sorted(required_color_sites - seen_color_sites)}, "
            f"extra={sorted(seen_color_sites - required_color_sites)}"
        )

    layout_patches = raw_contract.get("text_layout_patches")
    if not isinstance(layout_patches, Sequence) or isinstance(
        layout_patches, (str, bytes)
    ):
        raise GameModeUnlockError("mode text layout patches must be a list")
    required_layout_sites = {
        "ex_rule_line_1_centering",
        "ex_rule_line_2_centering",
        "sp_rule_line_1_centering",
        "sp_rule_line_2_centering",
    }
    if len(layout_patches) != len(required_layout_sites):
        raise GameModeUnlockError("mode text layout site inventory drift")

    layout_reports: list[dict[str, object]] = []
    seen_layout_sites: set[str] = set()
    seen_layout_records: set[int] = set()
    for raw_patch in layout_patches:
        if not isinstance(raw_patch, Mapping):
            raise GameModeUnlockError("mode text layout patch must be an object")
        site = raw_patch.get("id")
        if not isinstance(site, str) or not site:
            raise GameModeUnlockError("mode text layout ID must be non-empty")
        if site in seen_layout_sites:
            raise GameModeUnlockError(f"duplicate mode text layout site: {site}")
        seen_layout_sites.add(site)

        record_offset = _number(
            raw_patch.get("record_file_offset"), f"{site} record file offset"
        )
        text_offset = _number(
            raw_patch.get("text_file_offset"), f"{site} text file offset"
        )
        text_address = _number(
            raw_patch.get("text_virtual_address"),
            f"{site} text virtual address",
        )
        if text_offset - file_base + virtual_base != text_address:
            raise GameModeUnlockError(f"{site} text virtual/file mapping drift")
        if record_offset in seen_layout_records:
            raise GameModeUnlockError(
                f"duplicate mode text layout record: 0x{record_offset:X}"
            )
        seen_layout_records.add(record_offset)
        if record_offset < 0 or record_offset + 8 > len(output):
            raise GameModeUnlockError(f"{site} text record exceeds executable")

        original_x = _signed_halfword(raw_patch.get("original_x"), f"{site} x")
        replacement_x = _signed_halfword(
            raw_patch.get("replacement_x"), f"{site} replacement x"
        )
        expected_y = _signed_halfword(raw_patch.get("y"), f"{site} y")
        observed_address, observed_x, observed_y = struct.unpack_from(
            "<Ihh", output, record_offset
        )
        if observed_address != text_address:
            raise GameModeUnlockError(
                f"{site} text pointer drift: expected 0x{text_address:X}, "
                f"got 0x{observed_address:X}"
            )
        if observed_y != expected_y:
            raise GameModeUnlockError(
                f"{site} y drift: expected {expected_y}, got {observed_y}"
            )
        if observed_x not in (original_x, replacement_x):
            raise GameModeUnlockError(
                f"{site} x preimage drift: expected {original_x}, "
                f"got {observed_x}"
            )
        already_patched = observed_x == replacement_x
        struct.pack_into("<h", output, record_offset + 4, replacement_x)
        layout_reports.append(
            {
                "id": site,
                "surface": raw_patch.get("surface"),
                "record_file_offset": f"0x{record_offset:X}",
                "text_file_offset": f"0x{text_offset:X}",
                "text_virtual_address": f"0x{text_address:X}",
                "source_x": observed_x,
                "original_x": original_x,
                "replacement_x": replacement_x,
                "output_x": struct.unpack_from("<h", output, record_offset + 4)[0],
                "y": observed_y,
                "already_patched": already_patched,
                "changed": not already_patched,
            }
        )

    if seen_layout_sites != required_layout_sites:
        raise GameModeUnlockError(
            "mode text layout site set drift: "
            f"missing={sorted(required_layout_sites - seen_layout_sites)}, "
            f"extra={sorted(seen_layout_sites - required_layout_sites)}"
        )

    result = bytes(output)
    return result, {
        "policy": raw_contract["policy"],
        "member": raw_contract["member"],
        "menu_modes": ["NORMAL", "EX-HARD", "SP"],
        "ex_row_retail_selectable": True,
        "sp_dual_route_gate_removed": True,
        "patches": reports,
        "site_count": len(reports),
        "text_layout_patches": layout_reports,
        "text_layout_patch_count": len(layout_reports),
        "runtime_color_patches": color_reports,
        "runtime_color_patch_count": len(color_reports),
        "changed_instruction_count": sum(item["changed"] for item in reports),
        "changed_runtime_color_instruction_count": sum(
            item["changed"] for item in color_reports
        ),
        "changed_text_layout_count": sum(
            item["changed"] for item in layout_reports
        ),
        "changed_byte_count": sum(
            before != after for before, after in zip(source, result)
        ),
        "source_size": len(source),
        "output_size": len(result),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
        "all_instruction_replacements_exact": all(
            item["output_instruction_hex"]
            == item["replacement_instruction_hex"]
            for item in reports
        ),
        "all_text_layout_replacements_exact": all(
            item["output_x"] == item["replacement_x"]
            for item in layout_reports
        ),
        "all_runtime_color_retargets_exact": all(
            item["output_instruction_hex"]
            == item["replacement_instruction_hex"]
            for item in color_reports
        ),
        "localized_color_parameter_writes_retargeted": True,
        "selected_ex_special_color": "0x01",
        "selected_sp_special_color": "0x04",
        "text_descriptor_y_preserved": all(
            item["y"] == _signed_halfword(
                raw_patch["y"], f"{item['id']} y"
            )
            for item, raw_patch in zip(layout_reports, layout_patches)
        ),
        "save_flag_reads_bypassed": True,
        "save_writeback_functions_unchanged": True,
        "executable_size_preserved": len(result) == len(source),
    }


__all__ = [
    "GameModeUnlockError",
    "apply_postgame_mode_unlock",
]
