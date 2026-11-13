from __future__ import annotations

import itertools
import json
import struct
import unittest
from pathlib import Path

from tools.srwz.style_slot_scissor import (
    EDITION_SITES,
    NATIVE_BLOCK,
    PATCHED_BLOCK,
    StyleSlotScissorError,
    apply_style_slot_scissor,
    contract,
    validate_contract,
    verify_style_slot_scissor,
    write_ranges,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MASK64 = (1 << 64) - 1


def _elf(edition: str, block: bytes = NATIVE_BLOCK) -> bytes:
    """A minimal ELF with one PT_LOAD segment covering the edition's site."""
    _, offset, vaddr, builder = EDITION_SITES[edition]
    base_file, base_vaddr = 0x1000, vaddr - (offset - 0x1000)
    size = offset + 0x100
    data = bytearray(size)
    data[:4] = b"\x7fELF"
    struct.pack_into("<I", data, 28, 0x34)          # e_phoff
    struct.pack_into("<H", data, 44, 1)             # e_phnum
    struct.pack_into("<6I", data, 0x34, 1, base_file, base_vaddr, base_vaddr,
                     size - base_file, size - base_file)
    data[offset:offset + 72] = block
    struct.pack_into("<I", data, offset + 72, (0x03 << 26) | (builder >> 2))
    data[offset + 76:offset + 80] = bytes.fromhex("2d204002")
    return bytes(data)


def _sext(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def _run(block: bytes, regs: dict[int, int], memory: dict[int, int]) -> dict[int, int]:
    """Interpret the small EE subset both scissor blocks use (64-bit registers)."""
    r = dict(regs)
    get = lambda n: 0 if n == 0 else r.get(n, 0) & MASK64
    for (word,) in struct.iter_unpack("<I", block):
        op, rs, rt = word >> 26, (word >> 21) & 31, (word >> 16) & 31
        rd, sa, fn, imm = (word >> 11) & 31, (word >> 6) & 31, word & 63, word & 0xFFFF
        if word == 0:
            continue
        if op == 0 and fn == 0x21:            # addu (32-bit, sign-extended)
            r[rd] = _sext(get(rs) + get(rt), 32) & MASK64
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
        else:
            raise AssertionError(f"unexpected instruction {word:08X}")
        r[0] = 0
    return r


class StyleSlotScissorTest(unittest.TestCase):
    def test_config_section_is_the_canonical_contract(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["style_slot_scissor"], contract())
        validate_contract(config["style_slot_scissor"])

    def test_patched_block_adds_far_margin_only_on_stretched_axes(self) -> None:
        record = 0x01000000
        samples = [(-88, -6, 0, 12, 21, 28), (-313, 0, 0, 0, 56, 16),
                   (100, 40, -3, 7, 1, 1), (0, 0, 0, 0, 0, 0)]
        for (ox, oy, rx, ry, w, h), hmode, vmode in itertools.product(
            samples, range(4), range(4)
        ):
            mode = (hmode << 2) | (vmode << 4) | 0x03   # keep the other bits set
            regs = {2: ox & MASK64, 3: oy & MASK64, 7: rx & MASK64, 4: ry & MASK64,
                    8: w & MASK64, 5: h & MASK64, 17: record}
            memory = {record + 1: mode}
            native = _run(NATIVE_BLOCK, regs, memory)
            patched = _run(PATCHED_BLOCK, regs, memory)
            outs = lambda r: [_sext(r[n], 16) for n in (5, 6, 7, 8)]  # a1 a2 a3 t0
            left, top, right, bottom = outs(native)
            self.assertEqual([left, top], [ox + rx - 1, oy + ry - 1])
            self.assertEqual([right, bottom], [ox + w, oy + h])
            self.assertEqual(
                outs(patched),
                [left, top, right + (hmode == 2), bottom + (vmode == 2)],
                (ox, oy, rx, ry, w, h, hmode, vmode),
            )
            # Nothing the routine reads after the call may be clobbered.
            for reg in (2, 3, 4, 16, 17, 18, 19, 20, 21, 22, 23, 29, 30, 31):
                if reg in regs:
                    self.assertEqual(patched.get(reg, 0) & MASK64, regs[reg] & MASK64)

    def test_every_edition_patches_only_its_block(self) -> None:
        for edition in EDITION_SITES:
            source = _elf(edition)
            output, report = apply_style_slot_scissor(source, edition, contract())
            (lo, hi), = write_ranges(edition)
            self.assertEqual(output[:lo] + output[hi:], source[:lo] + source[hi:])
            self.assertEqual(output[lo:hi], PATCHED_BLOCK)
            self.assertFalse(report["already_patched"])
            self.assertEqual(report["changed_byte_count"], 63)
            self.assertTrue(verify_style_slot_scissor(output, edition)["builder_call_preserved"])
            again, report = apply_style_slot_scissor(output, edition)
            self.assertEqual(again, output)
            self.assertTrue(report["already_patched"])

    def test_drift_is_rejected(self) -> None:
        edition = "original"
        _, offset, _, _ = EDITION_SITES[edition]
        drifted = bytearray(_elf(edition))
        drifted[offset + 8] ^= 1
        with self.assertRaisesRegex(StyleSlotScissorError, "preimage drift"):
            apply_style_slot_scissor(bytes(drifted), edition)
        call = bytearray(_elf(edition))
        call[offset + 72] ^= 4
        with self.assertRaisesRegex(StyleSlotScissorError, "builder call drift"):
            apply_style_slot_scissor(bytes(call), edition)
        with self.assertRaisesRegex(StyleSlotScissorError, "block drift"):
            verify_style_slot_scissor(_elf(edition), edition)
        shifted = bytearray(_elf(edition))
        vaddr = struct.unpack_from("<I", shifted, 0x34 + 8)[0]
        struct.pack_into("<2I", shifted, 0x34 + 8, vaddr + 0x10, vaddr + 0x10)
        with self.assertRaisesRegex(StyleSlotScissorError, "mapping drift"):
            apply_style_slot_scissor(bytes(shifted), edition)
        bad = dict(contract(), policy="other")
        with self.assertRaisesRegex(StyleSlotScissorError, "policy"):
            apply_style_slot_scissor(_elf(edition), edition, bad)
        with self.assertRaisesRegex(StyleSlotScissorError, "unknown"):
            write_ranges("pal")


if __name__ == "__main__":
    unittest.main()
