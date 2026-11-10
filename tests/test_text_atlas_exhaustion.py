"""Guarded patch tests using the independently archived native disassemblies."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.text_atlas_exhaustion import AFTER, BEFORE, SITES, install


def fixture(edition):
    site, target = SITES[edition]
    start, size = site - 20, target + 216 - (site - 20)
    result = bytearray(0x100 + size)
    result[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<I', result, 28, 52)
    struct.pack_into('<HH', result, 42, 32, 1)
    struct.pack_into('<8I', result, 52, 1, 0x100, start, start, size, size, 5, 16)
    source = ROOT / f'docs/issue-assets/native-text-rendering-20261021/{edition}.asm'
    for line in source.read_text().splitlines():
        fields = line.split()
        if len(fields) < 2 or len(fields[0]) != 8:
            continue
        address = int(fields[0], 16)
        if start <= address < start + size:
            struct.pack_into('<I', result, 0x100 + address - start, int(fields[1], 16))
    return bytes(result)


class TextAtlasExhaustionTests(unittest.TestCase):
    def test_three_editions_branch_to_normal_epilogue_and_only_change_one_word(self):
        for edition, (site, target) in SITES.items():
            with self.subTest(edition=edition):
                before = fixture(edition)
                after, receipt = install(before, edition)
                at = receipt['file_offset']
                self.assertEqual(before[at:at + 4], BEFORE)
                self.assertEqual(after[at:at + 4], AFTER)
                self.assertEqual(after[:at] + after[at + 4:], before[:at] + before[at + 4:])
                word = struct.unpack_from('<I', after, at)[0]
                self.assertEqual(word >> 16, 0x1000)  # beq zero,zero
                self.assertEqual(site + 4 + 4 * (word & 65535), target)
                self.assertEqual(after[at + 4:at + 8], bytes.fromhex('2c002384'))
                self.assertFalse(receipt['capacity_changed'])
                with self.assertRaisesRegex(ValueError, 'preimage drift'):
                    install(after, edition)

    def test_guard_rejects_capacity_delay_slot_and_epilogue_drift(self):
        for edition, (site, target) in SITES.items():
            for address in (site - 12, site, site + 4, target, target + 44,
                            target + 112, target + 180):
                with self.subTest(edition=edition, address=hex(address)):
                    data = bytearray(fixture(edition))
                    data[0x100 + address - (site - 20)] ^= 1
                    with self.assertRaisesRegex(ValueError, 'preimage drift'):
                        install(bytes(data), edition)

    def test_rejects_unsupported_or_invalid_elf(self):
        for data, edition in [(fixture('original'), 'unknown'), (b'', 'original'),
                              (fixture('original')[:-16], 'original')]:
            with self.assertRaises(ValueError):
                install(data, edition)


if __name__ == '__main__':
    unittest.main()
