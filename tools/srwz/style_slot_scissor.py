"""Fail-closed SLPS patch: stretched KVP style slots keep their far scissor edge.

The KVP style engine draws each window slot (title middle, body middle, bottom
edge, ...) through one routine.  Before drawing a slot it pushes a GS SCISSOR
rectangle of ``[origin + record offset - 1, origin + slot size)``: the near
(left/top) edge gets a one-pixel margin, the far (right/bottom) edge lies
exactly on the stretched sprite's edge.  That is exact on the console and at
native or integer upscales.  PCSX2-family hardware renderers truncate the
scaled scissor, so at fractional upscales (1.5x, 2.5x, ...) the far edge loses
a sub-pixel strip and the neighbouring slot does not cover it: a one-pixel
seam shows the map behind the MAP DATA panel and other windows.

The patch rewrites the routine's 18-instruction scissor computation in place
(the following ``jal`` to the scissor builder and its delay slot stay native).
It adds one pixel to the far edge only on an axis whose record mode is
"stretch".  A stretched sprite never reaches past its slot, so native output is
unchanged; tiled and unscaled pieces, which rely on the scissor to cut them,
keep the exact native edge.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping

POLICY = "stretched_style_slot_scissor_far_edge_margin"

# member, ELF file offset, virtual address, scissor builder called right after.
EDITION_SITES: dict[str, tuple[str, int, int, int]] = {
    "original": ("SLPS_258.87", 0x2698DC, 0x367E5C, 0x3699A0),
    "best": ("SLPS_732.70", 0x269EDC, 0x36845C, 0x369FA0),
    "sp": ("SLPS_259.20", 0x28DF2C, 0x38D5AC, 0x38F0F0),
}

# Native: sign-extend the inputs, then left = origin_x + rec_x0 - 1,
# top = origin_y + rec_y0 - 1, right = origin_x + slot_w,
# bottom = origin_y + slot_h (identical bytes in all three editions).
NATIVE_BLOCK = bytes.fromhex(
    "3c3c07003c3404003f3c07003f340600213847002120480021106500ffffe724"
    "3c2c070021306600 3c3c0400ffffc3243c3403003c4402003f2c05003f3c0700"
    "3f3406003f440800".replace(" ", "")
)
DELAY_SLOT = bytes.fromhex("2d204002")  # move a0, s2

_REG = {
    "zero": 0, "v0": 2, "v1": 3, "a0": 4, "a1": 5, "a2": 6, "a3": 7,
    "t0": 8, "t1": 9, "t2": 10, "t3": 11, "t4": 12, "t5": 13, "s1": 17,
}
_RTYPE = {"addu": 0x21}
_ITYPE = {"addiu": 0x09, "andi": 0x0C, "xori": 0x0E, "sltiu": 0x0B}

# Inputs at the block: v0 = origin_x, v1 = origin_y, a3 = record x0,
# a0 = record y0, t0 = slot width, a1 = slot height, s1 = record.
# Outputs for the builder: a1 left, a2 top, a3 right (exclusive),
# t0 bottom (exclusive).  Record byte 1: bits 2-3 horizontal mode,
# bits 4-5 vertical mode (1 tile, 2 stretch).
PATCH_ASSEMBLY: tuple[tuple, ...] = (
    ("addu", "t1", "v0", "a3"),
    ("addiu", "t1", "t1", -1),      # left = origin_x + rec_x0 - 1 (native)
    ("addu", "t2", "v1", "a0"),
    ("addiu", "t2", "t2", -1),      # top = origin_y + rec_y0 - 1 (native)
    ("addu", "a3", "v0", "t0"),     # right = origin_x + slot_w
    ("addu", "t0", "v1", "a1"),     # bottom = origin_y + slot_h
    ("lbu", "t3", 1, "s1"),         # record mode byte
    ("andi", "t4", "t3", 0x0C),
    ("xori", "t4", "t4", 0x08),
    ("sltiu", "t4", "t4", 1),       # t4 = horizontal mode is stretch
    ("addu", "a3", "a3", "t4"),     # right += t4
    ("andi", "t5", "t3", 0x30),
    ("xori", "t5", "t5", 0x20),
    ("sltiu", "t5", "t5", 1),       # t5 = vertical mode is stretch
    ("addu", "t0", "t0", "t5"),     # bottom += t5
    ("addu", "a1", "t1", "zero"),
    ("addu", "a2", "t2", "zero"),
    ("nop",),
)


class StyleSlotScissorError(ValueError):
    """The scissor-margin contract or executable preimage drifted."""


def _encode(instruction: tuple) -> int:
    name = instruction[0]
    if name == "nop":
        return 0
    if name in _RTYPE:
        _, rd, rs, rt = instruction
        return (_REG[rs] << 21) | (_REG[rt] << 16) | (_REG[rd] << 11) | _RTYPE[name]
    if name in _ITYPE:
        _, rt, rs, immediate = instruction
        return (_ITYPE[name] << 26) | (_REG[rs] << 21) | (_REG[rt] << 16) | (immediate & 0xFFFF)
    if name == "lbu":
        _, rt, offset, base = instruction
        return (0x24 << 26) | (_REG[base] << 21) | (_REG[rt] << 16) | (offset & 0xFFFF)
    raise StyleSlotScissorError(f"unsupported instruction {name}")


PATCHED_BLOCK = b"".join(struct.pack("<I", _encode(i)) for i in PATCH_ASSEMBLY)
assert len(NATIVE_BLOCK) == len(PATCHED_BLOCK) == 72


def _site(edition: str) -> tuple[str, int, int, int]:
    try:
        return EDITION_SITES[edition]
    except KeyError as error:
        raise StyleSlotScissorError(f"unknown style-slot scissor edition {edition!r}") from error


def _virtual_to_file(executable: bytes, virtual_address: int) -> int:
    if executable[:4] != b"\x7fELF":
        raise StyleSlotScissorError("executable is not an ELF image")
    phoff, = struct.unpack_from("<I", executable, 28)
    count, = struct.unpack_from("<H", executable, 44)
    for index in range(count):
        kind, offset, vaddr, _, filesz, _ = struct.unpack_from(
            "<6I", executable, phoff + 32 * index
        )
        if kind == 1 and vaddr <= virtual_address < vaddr + filesz:
            return offset + virtual_address - vaddr
    raise StyleSlotScissorError("site is outside every loadable ELF segment")


def _check_frame(executable: bytes, edition: str) -> tuple[int, bytes]:
    _, offset, virtual_address, builder = _site(edition)
    if _virtual_to_file(executable, virtual_address) != offset:
        raise StyleSlotScissorError(f"{edition} ELF virtual/file mapping drift")
    tail = executable[offset + 72 : offset + 80]
    jal = struct.pack("<I", (0x03 << 26) | (builder >> 2))
    if tail != jal + DELAY_SLOT:
        raise StyleSlotScissorError(
            f"{edition} scissor builder call drift: {tail.hex().upper()}"
        )
    return offset, executable[offset : offset + 72]


def write_ranges(edition: str) -> list[tuple[int, int]]:
    """ELF file ranges this patch may change."""
    _, offset, _, _ = _site(edition)
    return [(offset, offset + 72)]


def validate_contract(raw_contract: Mapping[str, object]) -> None:
    if not isinstance(raw_contract, Mapping):
        raise StyleSlotScissorError("style-slot scissor contract must be an object")
    if raw_contract.get("enabled") is not True:
        raise StyleSlotScissorError("style-slot scissor contract must be enabled")
    if raw_contract.get("policy") != POLICY:
        raise StyleSlotScissorError("style-slot scissor policy drift")
    sites = raw_contract.get("sites")
    expected = {
        edition: {
            "member": member,
            "file_offset": f"0x{offset:X}",
            "virtual_address": f"0x{vaddr:X}",
            "scissor_builder": f"0x{builder:X}",
        }
        for edition, (member, offset, vaddr, builder) in EDITION_SITES.items()
    }
    if sites != expected:
        raise StyleSlotScissorError("style-slot scissor site table drift")
    if raw_contract.get("native_block_sha256") != hashlib.sha256(NATIVE_BLOCK).hexdigest():
        raise StyleSlotScissorError("style-slot scissor native block drift")
    if raw_contract.get("patched_block_sha256") != hashlib.sha256(PATCHED_BLOCK).hexdigest():
        raise StyleSlotScissorError("style-slot scissor patched block drift")


def verify_style_slot_scissor(executable: bytes, edition: str) -> dict[str, object]:
    """Verify the patched block (and the native call after it) in an output ELF."""
    member, _, virtual_address, builder = _site(edition)
    offset, observed = _check_frame(bytes(executable), edition)
    if observed != PATCHED_BLOCK:
        raise StyleSlotScissorError(
            f"{edition} style-slot scissor block drift: {observed.hex().upper()}"
        )
    return {
        "policy": POLICY,
        "edition": edition,
        "member": member,
        "file_offset": f"0x{offset:X}",
        "virtual_address": f"0x{virtual_address:X}",
        "scissor_builder": f"0x{builder:X}",
        "patched_block_sha256": hashlib.sha256(PATCHED_BLOCK).hexdigest(),
        "builder_call_preserved": True,
        "replacement_reread_exact": True,
    }


def apply_style_slot_scissor(
    executable: bytes,
    edition: str,
    raw_contract: Mapping[str, object] | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Apply the margin; accepts only the native or already-patched block."""
    if raw_contract is not None:
        validate_contract(raw_contract)
    source = bytes(executable)
    offset, observed = _check_frame(source, edition)
    if observed not in (NATIVE_BLOCK, PATCHED_BLOCK):
        raise StyleSlotScissorError(
            f"{edition} style-slot scissor preimage drift: {observed.hex().upper()}"
        )
    output = source[:offset] + PATCHED_BLOCK + source[offset + 72 :]
    changed = [i for i, (a, b) in enumerate(zip(source, output)) if a != b]
    if any(not (offset <= i < offset + 72) for i in changed) or len(output) != len(source):
        raise StyleSlotScissorError("style-slot scissor patch escaped its block")
    report = verify_style_slot_scissor(output, edition)
    report.update({
        "native_block_sha256": hashlib.sha256(NATIVE_BLOCK).hexdigest(),
        "already_patched": observed == PATCHED_BLOCK,
        "changed_byte_count": len(changed),
        "far_edge_margin_axes": "stretched axes only",
        "executable_size_preserved": True,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
    })
    return output, report


def contract() -> dict[str, object]:
    """The canonical config section for this patch."""
    return {
        "enabled": True,
        "policy": POLICY,
        "surface": (
            "KVP style-engine stretched slots get a one-pixel far-edge scissor "
            "margin so fractional emulator upscales leave no seam (MAP DATA etc.)"
        ),
        "sites": {
            edition: {
                "member": member,
                "file_offset": f"0x{offset:X}",
                "virtual_address": f"0x{vaddr:X}",
                "scissor_builder": f"0x{builder:X}",
            }
            for edition, (member, offset, vaddr, builder) in EDITION_SITES.items()
        },
        "native_block_sha256": hashlib.sha256(NATIVE_BLOCK).hexdigest(),
        "patched_block_sha256": hashlib.sha256(PATCHED_BLOCK).hexdigest(),
    }


__all__ = [
    "EDITION_SITES",
    "NATIVE_BLOCK",
    "PATCHED_BLOCK",
    "POLICY",
    "StyleSlotScissorError",
    "apply_style_slot_scissor",
    "contract",
    "validate_contract",
    "verify_style_slot_scissor",
    "write_ranges",
]
