"""Fail-closed SLPS patch: stretched KVP style slots keep their far scissor edge.

The KVP style engine draws each window slot (title middle, body middle, bottom
edge, ...) through two sibling routines, one for 22-byte (kind 5) and one for
34-byte (kind 6) sprite records.  Before drawing a slot each pushes a GS
SCISSOR rectangle of ``[origin + record offset - 1, origin + slot size)``: the
near (left/top) edge gets a one-pixel margin, the far (right/bottom) edge lies
exactly on the stretched sprite's edge.  That is exact on the console and at
native or integer upscales.  PCSX2-family hardware renderers truncate the
scaled scissor, so at fractional upscales (1.5x, 2.5x, ...) the far edge loses
a sub-pixel strip and the neighbouring slot does not cover it: a one-pixel
seam shows the map behind the MAP DATA panel, the save/load command popup and
other windows.

The patch rewrites both routines' scissor computations in place (the ``jal``
to the scissor builder stays native).  It adds one pixel to the far edge only
on an axis whose record mode is "stretch" (record byte 1: bits 2-3 horizontal,
bits 4-5 vertical; native code treats 0 as none, 1 as tile and 2/3 as
stretch, and the shipped data only uses 0-2).  A stretched sprite never reaches
past its slot, so native output is unchanged; tiled and unscaled pieces, which
rely on the scissor to cut them, keep the exact native edge.

A third block fixes a different line that also appears at integer upscales.
The child-slot routine (0x3695C0 in Original) tiles a child vertically
``slot_h / tile_h + 1`` times, so a slot whose height is a multiple of the tile
pitch, or one row more, gets an extra tile with at most one row inside the
scissor.  In the command popups that tile is a button whose visible rows sample
only transparent texel rows at native resolution; upscaled, the sub-rows of the
last scissored row reach the button's outline and draw a half-row dark line
under the last button.  The patch counts ``(slot_h - 2) / tile_h + 1`` tiles:
a tile needs two rows inside the slot to be drawn.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping

POLICY = "stretched_style_slot_scissor_far_edge_margin"

# member, scissor builder, kind-5 block (file offset, vaddr), kind-6 block.
EDITION_SITES: dict[str, dict[str, object]] = {
    "original": {"member": "SLPS_258.87", "builder": 0x3699A0,
                 "kind5": (0x2698DC, 0x367E5C), "kind6": (0x269EC4, 0x368444),
                 "tile": (0x26B128, 0x3696A8)},
    "best": {"member": "SLPS_732.70", "builder": 0x369FA0,
             "kind5": (0x269EDC, 0x36845C), "kind6": (0x26A4C4, 0x368A44),
             "tile": (0x26B728, 0x369CA8)},
    "sp": {"member": "SLPS_259.20", "builder": 0x38F0F0,
           "kind5": (0x28DF2C, 0x38D5AC), "kind6": (0x28E514, 0x38DB94),
           "tile": (0x28F778, 0x38EDF8)},
}

# Kind 5 (routine 0x367B70 in Original): 18 instructions, then
# ``jal builder; move a0, s2``.  Native: sign-extend the inputs, then
# left = origin_x + rec_x0 - 1, top = origin_y + rec_y0 - 1,
# right = origin_x + slot_w, bottom = origin_y + slot_h.
NATIVE_BLOCK = bytes.fromhex(
    "3c3c07003c3404003f3c07003f340600213847002120480021106500ffffe724"
    "3c2c0700213066003c3c0400ffffc3243c3403003c4402003f2c05003f3c0700"
    "3f3406003f440800"
)
KIND5_DELAY = bytes.fromhex("2d204002")  # move a0, s2

# Kind 6 (routine 0x3680C0 in Original): the branch over the scissor push and
# its delay slot ``addu v1, s8, a0`` (v1 = origin_x + slot_w), then 15
# instructions, ``jal builder`` and a delay slot that finishes the top edge.
KIND6_PREFIX = bytes.fromhex("140060102118c403")
KIND6_NATIVE = bytes.fromhex(
    "2110e2023c3c03003c440200160023863f3c0700180022863f4408002d204002"
    "2118c3032110e202ffff6324ffff42243c2c03003c3402003f2c0500"
)
KIND6_NATIVE_DELAY = bytes.fromhex("3f340600")  # dsra32 a2, a2, 16
KIND6_PATCHED_DELAY = bytes(4)              # nop

# Child-slot routine (0x3695C0 in Original), vertical tile count.  Preceded by
# ``bne t0, a1`` (mode is not "tile") and its nop; followed by ``mflo a1``.
# v0 = slot height, a3 = tile height, a1 = scratch (overwritten by the mflo).
TILE_PREFIX = bytes.fromhex("0b00051500000000")
TILE_SUFFIX = bytes.fromhex("12280000")     # mflo a1
TILE_NATIVE = bytes.fromhex("1a0047000000000000000000")  # div v0, a3; nop; nop

_REG = {
    "zero": 0, "v0": 2, "v1": 3, "a0": 4, "a1": 5, "a2": 6, "a3": 7,
    "t0": 8, "t1": 9, "t2": 10, "t3": 11, "t4": 12, "t5": 13,
    "s1": 17, "s2": 18, "s7": 23, "s8": 30,
}
_RTYPE = {"addu": 0x21}
_ITYPE = {"addiu": 0x09, "andi": 0x0C, "xori": 0x0E, "sltiu": 0x0B}
_LOAD = {"lbu": 0x24, "lh": 0x21}

# Kind 5 inputs: v0 = origin_x, v1 = origin_y, a3 = record x0, a0 = record y0,
# t0 = slot width, a1 = slot height, s1 = record.  Builder arguments: a1 left,
# a2 top, a3 right (exclusive), t0 bottom (exclusive); a0 = s2 is set in the
# native delay slot.
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

# Kind 6 inputs: v1 = origin_x + slot_w (native delay slot), v0 = slot height,
# s8 = origin_x, s7 = origin_y, s1 = record (x0 at +22, y0 at +24), s2 =
# packet.  The stretch test is bit 3 / bit 5 (mode 2 or 3), as native decodes.
KIND6_ASSEMBLY: tuple[tuple, ...] = (
    ("lbu", "t3", 1, "s1"),
    ("srl", "t4", "t3", 3),
    ("andi", "t4", "t4", 1),        # t4 = horizontal mode is stretch
    ("addu", "a3", "v1", "t4"),     # right = origin_x + slot_w + t4
    ("srl", "t5", "t3", 5),
    ("andi", "t5", "t5", 1),        # t5 = vertical mode is stretch
    ("addu", "t0", "s7", "v0"),     # bottom = origin_y + slot_h
    ("addu", "t0", "t0", "t5"),     # bottom += t5
    ("lh", "t1", 22, "s1"),
    ("addu", "a1", "s8", "t1"),
    ("addiu", "a1", "a1", -1),      # left = origin_x + rec_x0 - 1 (native)
    ("lh", "t2", 24, "s1"),
    ("addu", "a2", "s7", "t2"),
    ("addiu", "a2", "a2", -1),      # top = origin_y + rec_y0 - 1 (native)
    ("move", "a0", "s2"),
)

TILE_ASSEMBLY: tuple[tuple, ...] = (
    ("addiu", "a1", "v0", -2),      # a tile needs two rows inside the slot
    ("div", "a1", "a3"),
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
    if name == "move":                       # daddu rd, rs, zero
        _, rd, rs = instruction
        return (_REG[rs] << 21) | (_REG[rd] << 11) | 0x2D
    if name == "div":
        _, rs, rt = instruction
        return (_REG[rs] << 21) | (_REG[rt] << 16) | 0x1A
    if name == "srl":
        _, rd, rt, shift = instruction
        return (_REG[rt] << 16) | (_REG[rd] << 11) | (shift << 6) | 0x02
    if name in _ITYPE:
        _, rt, rs, immediate = instruction
        return (_ITYPE[name] << 26) | (_REG[rs] << 21) | (_REG[rt] << 16) | (immediate & 0xFFFF)
    if name in _LOAD:
        _, rt, offset, base = instruction
        return (_LOAD[name] << 26) | (_REG[base] << 21) | (_REG[rt] << 16) | (offset & 0xFFFF)
    raise StyleSlotScissorError(f"unsupported instruction {name}")


def _assemble(program: tuple[tuple, ...]) -> bytes:
    return b"".join(struct.pack("<I", _encode(i)) for i in program)


PATCHED_BLOCK = _assemble(PATCH_ASSEMBLY)
KIND6_PATCHED = _assemble(KIND6_ASSEMBLY)
assert len(NATIVE_BLOCK) == len(PATCHED_BLOCK) == 72
TILE_PATCHED = _assemble(TILE_ASSEMBLY)
assert len(KIND6_NATIVE) == len(KIND6_PATCHED) == 60
assert len(TILE_NATIVE) == len(TILE_PATCHED) == 12


def _site(edition: str) -> dict[str, object]:
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


def _jal(target: int) -> bytes:
    return struct.pack("<I", (0x03 << 26) | (target >> 2))


def _blocks(executable: bytes, edition: str) -> dict[str, tuple[int, bytes, bytes]]:
    """Check the call frames and return {name: (offset, observed, delay)}."""
    site = _site(edition)
    builder = int(site["builder"])
    found = {}
    for name in ("kind5", "kind6"):
        offset, vaddr = site[name]
        if _virtual_to_file(executable, vaddr) != offset:
            raise StyleSlotScissorError(f"{edition} {name} ELF virtual/file mapping drift")
        size = 72 if name == "kind5" else 60
        if executable[offset + size : offset + size + 4] != _jal(builder):
            raise StyleSlotScissorError(f"{edition} {name} scissor builder call drift")
        delay = executable[offset + size + 4 : offset + size + 8]
        if name == "kind5" and delay != KIND5_DELAY:
            raise StyleSlotScissorError(f"{edition} kind5 scissor builder call drift")
        if name == "kind6" and executable[offset - 8 : offset] != KIND6_PREFIX:
            raise StyleSlotScissorError(f"{edition} kind6 branch/delay-slot drift")
        found[name] = (offset, executable[offset : offset + size], delay)
    offset, vaddr = site["tile"]
    if _virtual_to_file(executable, vaddr) != offset:
        raise StyleSlotScissorError(f"{edition} tile ELF virtual/file mapping drift")
    if (executable[offset - 8 : offset] != TILE_PREFIX
            or executable[offset + 12 : offset + 16] != TILE_SUFFIX):
        raise StyleSlotScissorError(f"{edition} tile-count frame drift")
    found["tile"] = (offset, executable[offset : offset + 12], b"")
    return found


def write_ranges(edition: str) -> list[tuple[int, int]]:
    """ELF file ranges this patch may change."""
    site = _site(edition)
    kind5, kind6 = site["kind5"][0], site["kind6"][0]
    tile = site["tile"][0]
    return [(kind5, kind5 + 72), (kind6, kind6 + 60), (kind6 + 64, kind6 + 68),
            (tile, tile + 12)]


def contract() -> dict[str, object]:
    """The canonical config section for this patch."""
    return {
        "enabled": True,
        "policy": POLICY,
        "surface": (
            "KVP style-engine stretched slots (kind-5 and kind-6 records) get a "
            "one-pixel far-edge scissor margin so fractional emulator upscales "
            "leave no seam (MAP DATA, save/load popup, ...); vertically tiled "
            "child slots skip a last tile with fewer than two rows inside the "
            "slot (line under the last command button when upscaled)"
        ),
        "sites": {
            edition: {
                "member": site["member"],
                "scissor_builder": f"0x{site['builder']:X}",
                "kind5_file_offset": f"0x{site['kind5'][0]:X}",
                "kind5_virtual_address": f"0x{site['kind5'][1]:X}",
                "kind6_file_offset": f"0x{site['kind6'][0]:X}",
                "kind6_virtual_address": f"0x{site['kind6'][1]:X}",
                "tile_file_offset": f"0x{site['tile'][0]:X}",
                "tile_virtual_address": f"0x{site['tile'][1]:X}",
            }
            for edition, site in EDITION_SITES.items()
        },
        "native_sha256": hashlib.sha256(
            NATIVE_BLOCK + KIND6_NATIVE + KIND6_NATIVE_DELAY + TILE_NATIVE).hexdigest(),
        "patched_sha256": hashlib.sha256(
            PATCHED_BLOCK + KIND6_PATCHED + KIND6_PATCHED_DELAY + TILE_PATCHED).hexdigest(),
    }


def validate_contract(raw_contract: Mapping[str, object]) -> None:
    if not isinstance(raw_contract, Mapping):
        raise StyleSlotScissorError("style-slot scissor contract must be an object")
    if raw_contract.get("enabled") is not True:
        raise StyleSlotScissorError("style-slot scissor contract must be enabled")
    if raw_contract.get("policy") != POLICY:
        raise StyleSlotScissorError("style-slot scissor policy drift")
    if dict(raw_contract) != contract():
        raise StyleSlotScissorError("style-slot scissor site table or block drift")


def verify_style_slot_scissor(executable: bytes, edition: str) -> dict[str, object]:
    """Verify the patched blocks (and the native calls) in an output ELF."""
    blocks = _blocks(bytes(executable), edition)
    offset5, observed5, _ = blocks["kind5"]
    offset6, observed6, delay6 = blocks["kind6"]
    if observed5 != PATCHED_BLOCK:
        raise StyleSlotScissorError(f"{edition} style-slot scissor block drift (kind5)")
    if observed6 != KIND6_PATCHED or delay6 != KIND6_PATCHED_DELAY:
        raise StyleSlotScissorError(f"{edition} style-slot scissor block drift (kind6)")
    offset_tile, observed_tile, _ = blocks["tile"]
    if observed_tile != TILE_PATCHED:
        raise StyleSlotScissorError(f"{edition} style-slot tile-count block drift")
    site = _site(edition)
    return {
        "policy": POLICY,
        "edition": edition,
        "member": site["member"],
        "kind5_file_offset": f"0x{offset5:X}",
        "kind6_file_offset": f"0x{offset6:X}",
        "tile_file_offset": f"0x{offset_tile:X}",
        "scissor_builder": f"0x{site['builder']:X}",
        "patched_sha256": contract()["patched_sha256"],
        "builder_call_preserved": True,
        "replacement_reread_exact": True,
    }


def apply_style_slot_scissor(
    executable: bytes,
    edition: str,
    raw_contract: Mapping[str, object] | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Apply all blocks; each accepts its native or patched bytes only.

    The kind-5 block shipped alone in 3a1f5ab2, so a partly patched ELF is
    also accepted and completed.
    """
    if raw_contract is not None:
        validate_contract(raw_contract)
    source = bytes(executable)
    blocks = _blocks(source, edition)
    offset5, observed5, _ = blocks["kind5"]
    offset6, observed6, delay6 = blocks["kind6"]
    if observed5 not in (NATIVE_BLOCK, PATCHED_BLOCK):
        raise StyleSlotScissorError(f"{edition} style-slot scissor preimage drift (kind5)")
    if (observed6, delay6) not in (
        (KIND6_NATIVE, KIND6_NATIVE_DELAY), (KIND6_PATCHED, KIND6_PATCHED_DELAY)
    ):
        raise StyleSlotScissorError(f"{edition} style-slot scissor preimage drift (kind6)")
    offset_tile, observed_tile, _ = blocks["tile"]
    if observed_tile not in (TILE_NATIVE, TILE_PATCHED):
        raise StyleSlotScissorError(f"{edition} style-slot tile-count preimage drift")
    output = bytearray(source)
    output[offset_tile : offset_tile + 12] = TILE_PATCHED
    output[offset5 : offset5 + 72] = PATCHED_BLOCK
    output[offset6 : offset6 + 60] = KIND6_PATCHED
    output[offset6 + 64 : offset6 + 68] = KIND6_PATCHED_DELAY
    output = bytes(output)
    changed = [i for i, (a, b) in enumerate(zip(source, output)) if a != b]
    allowed = write_ranges(edition)
    if any(not any(lo <= i < hi for lo, hi in allowed) for i in changed) or len(output) != len(source):
        raise StyleSlotScissorError("style-slot scissor patch escaped its blocks")
    report = verify_style_slot_scissor(output, edition)
    report.update({
        "native_sha256": contract()["native_sha256"],
        "already_patched": not changed,
        "kind5_was_patched": observed5 == PATCHED_BLOCK,
        "changed_byte_count": len(changed),
        "far_edge_margin_axes": "stretched axes only",
        "executable_size_preserved": True,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
    })
    return output, report


__all__ = [
    "EDITION_SITES",
    "KIND6_NATIVE",
    "KIND6_NATIVE_DELAY",
    "KIND6_PATCHED",
    "KIND6_PATCHED_DELAY",
    "KIND6_PREFIX",
    "NATIVE_BLOCK",
    "PATCHED_BLOCK",
    "POLICY",
    "StyleSlotScissorError",
    "TILE_NATIVE",
    "TILE_PATCHED",
    "TILE_PREFIX",
    "TILE_SUFFIX",
    "apply_style_slot_scissor",
    "contract",
    "validate_contract",
    "verify_style_slot_scissor",
    "write_ranges",
]
