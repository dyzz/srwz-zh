from __future__ import annotations

import itertools
import json
import struct
import unittest
from pathlib import Path

from tools.srwz.style_slot_scissor import (
    EDITION_SITES,
    KIND6_NATIVE,
    KIND6_NATIVE_DELAY,
    KIND6_PATCHED,
    KIND6_PATCHED_DELAY,
    KIND6_PREFIX,
    NATIVE_BLOCK,
    PATCHED_BLOCK,
    StyleSlotScissorError,
    TILE_NATIVE,
    TILE_PATCHED,
    TILE_PREFIX,
    TILE_SUFFIX,
    apply_style_slot_scissor,
    contract,
    validate_contract,
    verify_style_slot_scissor,
    write_ranges,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MASK64 = (1 << 64) - 1
KIND5_DELAY = bytes.fromhex("2d204002")


def native_fixture(edition: str, size: int | None = None, data: bytes | None = None) -> bytes:
    """An ELF image (one PT_LOAD) holding the native blocks and their frames."""
    site = EDITION_SITES[edition]
    off5, vaddr5 = site["kind5"]
    off6, _ = site["kind6"]
    off_tile, _ = site["tile"]
    jal = struct.pack("<I", (0x03 << 26) | (site["builder"] >> 2))
    result = bytearray(data if data is not None else bytes(size or off_tile + 0x100))
    result[:4] = b"\x7fELF"
    struct.pack_into("<I", result, 28, 0x34)
    struct.pack_into("<H", result, 44, 1)
    base = vaddr5 - off5
    struct.pack_into("<6I", result, 0x34, 1, 0x1000, base + 0x1000, base + 0x1000,
                     len(result) - 0x1000, len(result) - 0x1000)
    result[off5:off5 + 72] = NATIVE_BLOCK
    result[off5 + 72:off5 + 80] = jal + KIND5_DELAY
    result[off6 - 8:off6] = KIND6_PREFIX
    result[off6:off6 + 60] = KIND6_NATIVE
    result[off6 + 60:off6 + 68] = jal + KIND6_NATIVE_DELAY
    result[off_tile - 8:off_tile] = TILE_PREFIX
    result[off_tile:off_tile + 12] = TILE_NATIVE
    result[off_tile + 12:off_tile + 16] = TILE_SUFFIX
    return bytes(result)


def _sext(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def _run(code: bytes, regs: dict[int, int], memory: dict[int, int]) -> dict[int, int]:
    """Interpret the small EE subset these blocks use (64-bit registers)."""
    r = dict(regs)
    get = lambda n: 0 if n == 0 else r.get(n, 0) & MASK64
    for (word,) in struct.iter_unpack("<I", code):
        op, rs, rt = word >> 26, (word >> 21) & 31, (word >> 16) & 31
        rd, sa, fn, imm = (word >> 11) & 31, (word >> 6) & 31, word & 63, word & 0xFFFF
        if word == 0:
            continue
        if op == 0 and fn == 0x21:            # addu (32-bit, sign-extended)
            r[rd] = _sext(get(rs) + get(rt), 32) & MASK64
        elif op == 0 and fn == 0x2D:          # daddu
            r[rd] = (get(rs) + get(rt)) & MASK64
        elif op == 0 and fn == 0x02:          # srl
            r[rd] = _sext((get(rt) & 0xFFFFFFFF) >> sa, 32) & MASK64
        elif op == 0 and fn == 0x3C:          # dsll32
            r[rd] = (get(rt) << (sa + 32)) & MASK64
        elif op == 0 and fn == 0x3F:          # dsra32
            r[rd] = (_sext(get(rt), 64) >> (sa + 32)) & MASK64
        elif op == 0x09:                      # addiu
            r[rt] = _sext(get(rs) + _sext(imm, 16), 32) & MASK64
        elif op == 0x0C:                      # andi
            r[rt] = get(rs) & imm
        elif op == 0x0E:                      # xori
            r[rt] = get(rs) ^ imm
        elif op == 0x0B:                      # sltiu
            r[rt] = int(get(rs) < (_sext(imm, 16) & MASK64))
        elif op == 0x24:                      # lbu
            r[rt] = memory[(get(rs) + _sext(imm, 16)) & 0xFFFFFFFF]
        elif op == 0x21:                      # lh
            address = (get(rs) + _sext(imm, 16)) & 0xFFFFFFFF
            r[rt] = _sext(memory[address] | memory[address + 1] << 8, 16) & MASK64
        else:
            raise AssertionError(f"unexpected instruction {word:08X}")
        r[0] = 0
    return r


SAMPLES = [(-88, -6, 0, 12, 21, 28), (-313, 0, 0, 0, 56, 16),
           (100, 40, -3, 7, 1, 1), (0, 0, 0, 0, 0, 0), (-44, -38, 0, 0, 120, 19)]
RECORD = 0x01000000
OUTPUTS = (5, 6, 7, 8)  # a1 left, a2 top, a3 right, t0 bottom


def _outs(regs: dict[int, int]) -> list[int]:
    return [_sext(regs[n], 16) for n in OUTPUTS]


class StyleSlotScissorTest(unittest.TestCase):
    def test_config_section_is_the_canonical_contract(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["style_slot_scissor"], contract())
        validate_contract(config["style_slot_scissor"])

    def _check(self, native_left_top_right_bottom, patched, hmode, vmode) -> None:
        left, top, right, bottom = native_left_top_right_bottom
        self.assertEqual(patched, [left, top, right + (hmode >= 2), bottom + (vmode >= 2)])

    def test_kind5_block_adds_far_margin_only_on_stretched_axes(self) -> None:
        for (ox, oy, rx, ry, w, h), hmode, vmode in itertools.product(SAMPLES, range(4), range(4)):
            regs = {2: ox & MASK64, 3: oy & MASK64, 7: rx & MASK64, 4: ry & MASK64,
                    8: w & MASK64, 5: h & MASK64, 17: RECORD}
            memory = {RECORD + 1: (hmode << 2) | (vmode << 4) | 0x03}
            native = _outs(_run(NATIVE_BLOCK, regs, memory))
            self.assertEqual(native, [ox + rx - 1, oy + ry - 1, ox + w, oy + h])
            patched = _run(PATCHED_BLOCK, regs, memory)
            # Shipped data only uses modes 0-2; mode 3 is checked as == 2 here.
            if hmode != 3 and vmode != 3:
                self._check(native, _outs(patched), hmode, vmode)
            for reg in (2, 3, 4, 17):
                self.assertEqual(patched[reg] & MASK64, regs[reg] & MASK64)

    def test_kind6_block_adds_far_margin_only_on_stretched_axes(self) -> None:
        packet = 0x00480000
        for (ox, oy, rx, ry, w, h), hmode, vmode in itertools.product(SAMPLES, range(4), range(4)):
            # Entry state after the native delay slot ``addu v1, s8, a0``.
            regs = {30: ox & MASK64, 23: oy & MASK64, 3: (ox + w) & MASK64, 2: h & MASK64,
                    17: RECORD, 18: packet, 4: w & MASK64}
            memory = {RECORD + 1: (hmode << 2) | (vmode << 4) | 0x03,
                      RECORD + 22: rx & 0xFF, RECORD + 23: (rx >> 8) & 0xFF,
                      RECORD + 24: ry & 0xFF, RECORD + 25: (ry >> 8) & 0xFF}
            native = _run(KIND6_NATIVE + KIND6_NATIVE_DELAY, regs, memory)
            patched = _run(KIND6_PATCHED + KIND6_PATCHED_DELAY, regs, memory)
            self.assertEqual(_outs(native), [ox + rx - 1, oy + ry - 1, ox + w, oy + h])
            self._check(_outs(native), _outs(patched), hmode, vmode)
            self.assertEqual(patched[4], packet)                 # a0 = packet
            for reg in (17, 18, 23, 30):
                self.assertEqual(patched[reg] & MASK64, regs[reg] & MASK64)

    def test_every_edition_patches_only_its_blocks(self) -> None:
        for edition in EDITION_SITES:
            source = native_fixture(edition)
            output, report = apply_style_slot_scissor(source, edition, contract())
            ranges = write_ranges(edition)
            for index, (a, b) in enumerate(zip(source, output)):
                if a != b:
                    self.assertTrue(any(lo <= index < hi for lo, hi in ranges))
            self.assertFalse(report["already_patched"])
            self.assertTrue(verify_style_slot_scissor(output, edition)["builder_call_preserved"])
            again, report = apply_style_slot_scissor(output, edition)
            self.assertEqual(again, output)
            self.assertTrue(report["already_patched"])

    def test_tile_block_requires_two_rows_inside_the_slot(self) -> None:
        # addiu a1, v0, -2; div a1, a3; nop -- then the native mflo a1.
        self.assertEqual(TILE_PATCHED.hex(), "feff45241a00a70000000000")
        self.assertEqual(TILE_NATIVE.hex(), "1a004700" + "00" * 8)

        def count(height: int, pitch: int, margin: int) -> int:
            return int((height - margin) / pitch) + 1       # C division truncates

        for pitch in (15, 18):
            for height in range(0, 6 * pitch + 2):
                native, patched = count(height, pitch, 0), count(height, pitch, 2)
                dropped = height >= pitch and height % pitch < 2
                self.assertEqual(native - patched, 1 if dropped else 0, (height, pitch))
        # The save/load command popup: 37 rows at an 18-row pitch draws two buttons.
        self.assertEqual((count(37, 18, 0), count(37, 18, 2)), (3, 2))

    def test_kind5_only_build_is_completed(self) -> None:
        edition = "original"
        off5, _ = EDITION_SITES[edition]["kind5"]
        partial = bytearray(native_fixture(edition))
        partial[off5:off5 + 72] = PATCHED_BLOCK
        output, report = apply_style_slot_scissor(bytes(partial), edition)
        self.assertTrue(report["kind5_was_patched"])
        verify_style_slot_scissor(output, edition)

    def test_drift_is_rejected(self) -> None:
        edition = "original"
        off5, _ = EDITION_SITES[edition]["kind5"]
        off6, _ = EDITION_SITES[edition]["kind6"]
        off_tile, _ = EDITION_SITES[edition]["tile"]
        for offset, message in ((off5 + 8, "preimage drift \\(kind5\\)"),
                                (off_tile, "tile-count preimage drift"),
                                (off_tile - 8, "tile-count frame drift"),
                                (off_tile + 12, "tile-count frame drift"),
                                (off6 + 8, "preimage drift \\(kind6\\)"),
                                (off5 + 72, "builder call drift"),
                                (off6 + 60, "builder call drift"),
                                (off6 - 4, "branch/delay-slot drift")):
            drifted = bytearray(native_fixture(edition))
            drifted[offset] ^= 4
            with self.assertRaisesRegex(StyleSlotScissorError, message):
                apply_style_slot_scissor(bytes(drifted), edition)
        with self.assertRaisesRegex(StyleSlotScissorError, "block drift"):
            verify_style_slot_scissor(native_fixture(edition), edition)
        shifted = bytearray(native_fixture(edition))
        vaddr = struct.unpack_from("<I", shifted, 0x34 + 8)[0]
        struct.pack_into("<2I", shifted, 0x34 + 8, vaddr + 0x10, vaddr + 0x10)
        with self.assertRaisesRegex(StyleSlotScissorError, "mapping drift"):
            apply_style_slot_scissor(bytes(shifted), edition)
        with self.assertRaisesRegex(StyleSlotScissorError, "policy"):
            apply_style_slot_scissor(native_fixture(edition), edition, dict(contract(), policy="x"))
        with self.assertRaisesRegex(StyleSlotScissorError, "unknown"):
            write_ranges("pal")


if __name__ == "__main__":
    unittest.main()
