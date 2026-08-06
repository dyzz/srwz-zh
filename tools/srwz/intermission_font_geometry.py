"""Use the standard font path in the intermission pilot and unit lists.

The original renderer can enable conditional widths for several double-byte
code ranges.  Chinese allocations may legitimately reuse codes in those
ranges, so list-local conditional classification must not change their visual
geometry.  The two dedicated list renderers call a locked executable-tail
trampoline that restores the native 22x11 geometry and clears the conditional
width enable flag.  No per-code metric emulation or list-local enlargement is
performed.  The global initializer, generic metric setter, and story-dialogue
renderers remain unchanged.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .writeback import PatchOperation, PatchPlan, WritebackError, sha256_bytes


SLPS_LOAD_FILE_OFFSET = 0x1A80
SLPS_LOAD_ADDRESS = 0x100000
SLPS_VA_FILE_DELTA = SLPS_LOAD_ADDRESS - SLPS_LOAD_FILE_OFFSET

DEFAULT_METRICS_VA = 0x139930
SET_METRICS_VA = 0x139E40
SET_CONDITIONAL_METRICS_VA = 0x139D50
SET_STYLE_FLAG_VA = 0x139AF0

CAVE_VA = 0x44BC30
CAVE_CAPACITY = 0x50
ENTRY_TRAMPOLINE_SIZE = 0x18
RESTORE_TRAMPOLINE_VA = CAVE_VA + ENTRY_TRAMPOLINE_SIZE
STORE_HELPER_VA = RESTORE_TRAMPOLINE_VA + 0x18
TRAMPOLINE_SIZE = CAVE_CAPACITY

FONT_STATE_BASE_HIGH = 0x47
MAIN_RENDER_PAIR_OFFSET = 0xE344
MAIN_ADVANCE_PAIR_OFFSET = 0xE348
CONDITIONAL_A_RENDER_PAIR_OFFSET = 0xE368
CONDITIONAL_A_ADVANCE_PAIR_OFFSET = 0xE36C
CONDITIONAL_B_RENDER_PAIR_OFFSET = 0xE370
CONDITIONAL_B_ADVANCE_PAIR_OFFSET = 0xE374
CONDITIONAL_MODE_OFFSET = 0xE378
STYLE_FLAG_OFFSET = 0xE380

PILOT_ENTRY_VA = 0x3DAC2C
PILOT_RESTORE_CALL_VA = 0x3DB09C
UNIT_ENTRY_VA = 0x3DDBFC
UNIT_RESTORE_CALL_VA = 0x3DE06C

ENTRY_PREIMAGE = bytes.fromhex(
    "2c00a386"  # lh v1, 44(s5)
    "3c8c1e00"  # dsll32 s1, s8, 16
)
RESTORE_CALL_PREIMAGE = bytes.fromhex("bce6040c")  # jal 0x139af0
DEFAULT_METRICS_PREIMAGE = bytes.fromhex(
    "4700013cff00033c42e320a4ffff6434"
    "4700013c1600062440e320a40b000524"
)
SET_METRICS_PREIMAGE = bytes.fromhex(
    "4700013c44e324a44700013c46e325a4"
    "4700013c48e326a44700013c0800e003"
    "4ae327a4"
)
SET_CONDITIONAL_METRICS_PREIMAGE = bytes.fromhex(
    "4700013c0100032468e324a44700013c"
    "1800a4836ae325a44700013c1000a583"
    "78e323a44700013c2000a3836ce326a4"
    "4700013c0800a6836ee327a44700013c"
    "0000a78370e328a44700013c72e329a4"
    "4700013c74e32aa44700013c76e32ba4"
    "4700013c7be327a04700013c7ce326a0"
    "4700013c7de325a04700013c7ee324a0"
    "4700013c0800e0037fe323a000000000"
)


class IntermissionFontGeometryError(ValueError):
    """The locked renderer, metric routine, or code cave has drifted."""


@dataclass(frozen=True)
class IntermissionFontGeometryMetrics:
    render_width: int = 22
    render_height: int = 11
    advance_width: int = 22
    advance_height: int = 11

    def validate(self) -> None:
        values = (
            self.render_width,
            self.render_height,
            self.advance_width,
            self.advance_height,
        )
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= 0x7FFF
            for value in values
        ):
            raise IntermissionFontGeometryError(
                "intermission font metrics must be non-negative 16-bit integers"
            )
        if (
            (self.render_width, self.render_height) != (22, 11)
            or (self.advance_width, self.advance_height) != (22, 11)
        ):
            raise IntermissionFontGeometryError(
                "intermission list geometry must remain the original 22x11"
            )


def va_to_file_offset(address: int) -> int:
    offset = address - SLPS_VA_FILE_DELTA
    if offset < SLPS_LOAD_FILE_OFFSET:
        raise IntermissionFontGeometryError(
            f"SLPS virtual address is outside the loaded file span: 0x{address:X}"
        )
    return offset


def _r(*, rs: int, rt: int, rd: int, function: int, shift: int = 0) -> int:
    return (
        ((rs & 0x1F) << 21)
        | ((rt & 0x1F) << 16)
        | ((rd & 0x1F) << 11)
        | ((shift & 0x1F) << 6)
        | (function & 0x3F)
    )


def _i(*, opcode: int, rs: int, rt: int, immediate: int) -> int:
    return (
        ((opcode & 0x3F) << 26)
        | ((rs & 0x1F) << 21)
        | ((rt & 0x1F) << 16)
        | (immediate & 0xFFFF)
    )


def _j(*, opcode: int, address: int) -> int:
    if address & 3:
        raise IntermissionFontGeometryError(
            f"MIPS jump target is not word aligned: 0x{address:X}"
        )
    return ((opcode & 0x3F) << 26) | ((address >> 2) & 0x03FFFFFF)


def _words(*values: int) -> bytes:
    return struct.pack(f"<{len(values)}I", *values)


def _move(destination: int, source: int) -> int:
    # The original executable uses DADDU for the move pseudo-instruction.
    return _r(rs=source, rt=0, rd=destination, function=0x2D)


def _lui(register: int, value: int) -> int:
    return _i(opcode=0x0F, rs=0, rt=register, immediate=value)


def _ori(destination: int, source: int, value: int) -> int:
    return _i(opcode=0x0D, rs=source, rt=destination, immediate=value)


def _sw(register: int, offset: int, base: int) -> int:
    return _i(opcode=0x2B, rs=base, rt=register, immediate=offset)


def _sb(register: int, offset: int, base: int) -> int:
    return _i(opcode=0x28, rs=base, rt=register, immediate=offset)


def _sh(register: int, offset: int, base: int) -> int:
    return _i(opcode=0x29, rs=base, rt=register, immediate=offset)


def _jal(address: int) -> int:
    return _j(opcode=0x03, address=address)


def _jump(address: int) -> int:
    return _j(opcode=0x02, address=address)


def _jr(register: int) -> int:
    return _r(rs=register, rt=0, rd=0, function=0x08)


def _entry_replacement() -> bytes:
    return _words(
        _jal(CAVE_VA),
        0x86A3002C,  # original lh v1, 44(s5), now in the call delay slot
    )


def build_trampoline(metrics: IntermissionFontGeometryMetrics) -> bytes:
    metrics.validate()
    render_pair = (metrics.render_height << 16) | metrics.render_width
    advance_pair = (metrics.advance_height << 16) | metrics.advance_width
    default_pair = (11 << 16) | 22

    entry = _words(
        _lui(4, render_pair >> 16),
        _ori(4, 4, render_pair),
        _lui(5, advance_pair >> 16),
        _ori(5, 5, advance_pair),
        _jump(STORE_HELPER_VA),
        _lui(15, FONT_STATE_BASE_HIGH),  # jump delay: t7 = 0x00470000
    )
    restore = _words(
        _lui(4, default_pair >> 16),
        _ori(4, 4, default_pair),
        _move(5, 4),
        _lui(15, FONT_STATE_BASE_HIGH),
        _jump(STORE_HELPER_VA),
        # Exact effect of the displaced jal 0x139AF0 with a0 = 0.
        _sb(0, STYLE_FLAG_OFFSET, 15),
    )
    store_helper = _words(
        _sw(4, MAIN_RENDER_PAIR_OFFSET, 15),
        _sw(5, MAIN_ADVANCE_PAIR_OFFSET, 15),
        _sh(0, CONDITIONAL_MODE_OFFSET, 15),
        0x00000000,
        0x00000000,
        0x00000000,
        _jr(31),
        # Displaced entry instruction.  The restore path also executes it just
        # before the renderer epilogue reloads s1, so no live state is changed.
        0x001E8C3C,  # dsll32 s1, s8, 16
    )
    trampoline = entry + restore + store_helper
    if (
        len(entry) != ENTRY_TRAMPOLINE_SIZE
        or len(restore) != 0x18
        or len(store_helper) != 0x20
        or len(trampoline) != TRAMPOLINE_SIZE
        or len(trampoline) != CAVE_CAPACITY
    ):
        raise IntermissionFontGeometryError("intermission trampoline size drift")
    return trampoline


def _require_preimage(source: bytes, address: int, expected: bytes, label: str) -> None:
    offset = va_to_file_offset(address)
    actual = source[offset : offset + len(expected)]
    if actual != expected:
        raise IntermissionFontGeometryError(
            f"{label} preimage mismatch at VA 0x{address:X} "
            f"(file 0x{offset:X})"
        )


def apply_intermission_font_geometry_patch(
    source: bytes,
    *,
    metrics: IntermissionFontGeometryMetrics | None = None,
) -> tuple[bytes, dict]:
    metrics = metrics or IntermissionFontGeometryMetrics()
    metrics.validate()
    _require_preimage(
        source,
        DEFAULT_METRICS_VA,
        DEFAULT_METRICS_PREIMAGE,
        "default font metrics",
    )
    _require_preimage(
        source,
        SET_METRICS_VA,
        SET_METRICS_PREIMAGE,
        "font metric setter",
    )
    _require_preimage(
        source,
        SET_CONDITIONAL_METRICS_VA,
        SET_CONDITIONAL_METRICS_PREIMAGE,
        "conditional double-byte metric setter",
    )

    trampoline = build_trampoline(metrics)
    entry_replacement = _entry_replacement()
    cave_offset = va_to_file_offset(CAVE_VA)
    cave_before = bytes(TRAMPOLINE_SIZE)
    operations = (
        PatchOperation(
            owner="intermission/pilot-list/metric-entry",
            offset=va_to_file_offset(PILOT_ENTRY_VA),
            before=ENTRY_PREIMAGE,
            after=entry_replacement,
        ),
        PatchOperation(
            owner="intermission/pilot-list/metric-restore",
            offset=va_to_file_offset(PILOT_RESTORE_CALL_VA),
            before=RESTORE_CALL_PREIMAGE,
            after=_words(_jal(RESTORE_TRAMPOLINE_VA)),
        ),
        PatchOperation(
            owner="intermission/unit-list/metric-entry",
            offset=va_to_file_offset(UNIT_ENTRY_VA),
            before=ENTRY_PREIMAGE,
            after=entry_replacement,
        ),
        PatchOperation(
            owner="intermission/unit-list/metric-restore",
            offset=va_to_file_offset(UNIT_RESTORE_CALL_VA),
            before=RESTORE_CALL_PREIMAGE,
            after=_words(_jal(RESTORE_TRAMPOLINE_VA)),
        ),
        PatchOperation(
            owner="intermission/pilot-unit-list/metric-trampoline",
            offset=cave_offset,
            before=cave_before,
            after=trampoline,
        ),
    )
    plan = PatchPlan(
        source_name="SLPS_258.87 intermission pilot/unit list geometry",
        source_size=len(source),
        source_sha256=sha256_bytes(source),
        operations=operations,
    )
    try:
        output = plan.apply(source)
    except WritebackError as error:
        raise IntermissionFontGeometryError(str(error)) from error

    changed_offsets = {
        offset
        for operation in operations
        for offset in range(operation.offset, operation.end)
        if source[offset] != output[offset]
    }
    allowed_offsets = {
        offset
        for operation in operations
        for offset in range(operation.offset, operation.end)
    }
    if not changed_offsets or not changed_offsets <= allowed_offsets:
        raise IntermissionFontGeometryError(
            "intermission font geometry changed bytes outside its patch plan"
        )
    if (
        output[
            va_to_file_offset(DEFAULT_METRICS_VA) :
            va_to_file_offset(DEFAULT_METRICS_VA) + len(DEFAULT_METRICS_PREIMAGE)
        ]
        != DEFAULT_METRICS_PREIMAGE
        or output[
            va_to_file_offset(SET_METRICS_VA) :
            va_to_file_offset(SET_METRICS_VA) + len(SET_METRICS_PREIMAGE)
        ]
        != SET_METRICS_PREIMAGE
        or output[
            va_to_file_offset(SET_CONDITIONAL_METRICS_VA) :
            va_to_file_offset(SET_CONDITIONAL_METRICS_VA)
            + len(SET_CONDITIONAL_METRICS_PREIMAGE)
        ]
        != SET_CONDITIONAL_METRICS_PREIMAGE
    ):
        raise IntermissionFontGeometryError(
            "global font metric routines changed unexpectedly"
        )

    return output, {
        "scope": "intermission pilot and unit list standard metrics only",
        "metrics": {
            "render_width": metrics.render_width,
            "render_height": metrics.render_height,
            "advance_width": metrics.advance_width,
            "advance_height": metrics.advance_height,
        },
        "virtual_addresses": {
            "pilot_entry": f"0x{PILOT_ENTRY_VA:X}",
            "pilot_restore_call": f"0x{PILOT_RESTORE_CALL_VA:X}",
            "unit_entry": f"0x{UNIT_ENTRY_VA:X}",
            "unit_restore_call": f"0x{UNIT_RESTORE_CALL_VA:X}",
            "set_metrics": f"0x{SET_METRICS_VA:X}",
            "set_conditional_metrics": f"0x{SET_CONDITIONAL_METRICS_VA:X}",
            "default_metrics": f"0x{DEFAULT_METRICS_VA:X}",
            "trampoline": f"0x{CAVE_VA:X}",
            "restore_trampoline": f"0x{RESTORE_TRAMPOLINE_VA:X}",
            "store_helper": f"0x{STORE_HELPER_VA:X}",
        },
        "cave": {
            "file_offset": cave_offset,
            "capacity": CAVE_CAPACITY,
            "used": len(trampoline),
            "preimage_all_zero": True,
            "inside_loaded_wax_segment": True,
        },
        "source_sha256": sha256_bytes(source),
        "output_sha256": sha256_bytes(output),
        "changed_byte_count": len(changed_offsets),
        "patch_plan": plan.to_metadata(),
        "global_default_metrics_unchanged": True,
        "generic_metric_setter_unchanged": True,
        "conditional_metric_setter_unchanged": True,
        "metric_groups": ["main"],
        "conditional_double_byte_range": "0x8140..0x889E",
        "conditional_width_mode_disabled": True,
        "conditional_metric_groups_ignored": True,
        "advance_unchanged": True,
        "style_cleanup_preserved_without_global_reset": True,
        "restores_geometry_after_each_renderer": True,
        "changed_bytes_confined_to_patch_plan": True,
    }


__all__ = [
    "CAVE_CAPACITY",
    "CAVE_VA",
    "DEFAULT_METRICS_VA",
    "IntermissionFontGeometryError",
    "IntermissionFontGeometryMetrics",
    "PILOT_ENTRY_VA",
    "PILOT_RESTORE_CALL_VA",
    "RESTORE_TRAMPOLINE_VA",
    "SET_CONDITIONAL_METRICS_PREIMAGE",
    "SET_METRICS_VA",
    "SET_CONDITIONAL_METRICS_VA",
    "STORE_HELPER_VA",
    "TRAMPOLINE_SIZE",
    "UNIT_ENTRY_VA",
    "UNIT_RESTORE_CALL_VA",
    "apply_intermission_font_geometry_patch",
    "build_trampoline",
    "va_to_file_offset",
]
