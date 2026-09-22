"""Exercise SP keyword relocation, protected data, and fail-closed preimages."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback')]
from special_disc.writeback import keyword_list_names as names
from srwz.codec import decode_production


class SpecialDiscKeywordNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from migrate_slps_text import encoding_tables
        from build_text_candidate import read_member
        from special_disc.source import CURRENT_ISO
        from srwz.iso9660 import member_map, scan_iso9660
        proposal = ROOT/'work/build/special-disc/text-candidate/font/proposal.json'
        if not CURRENT_ISO.exists() or not proposal.exists():
            raise unittest.SkipTest('requires local SP ISO and font proposal')
        cls.table, _, cls.overrides, cls.readback = encoding_tables(proposal)
        backup = ROOT/'work/verification/sp-current-keyword-list-names/previous-COMPDATA.BN'
        cls.before = backup.read_bytes() if backup.exists() else read_member(
            CURRENT_ISO, member_map(scan_iso9660(CURRENT_ISO)), names.MEMBER)
        cls.raw = decode_production(cls.before).output
        cls.output, cls.report = names.apply_keyword_names(cls.before, cls.table, cls.overrides, cls.readback)

    def test_roundtrip_preserves_all_nonowned_bytes_and_member_size(self):
        self.assertEqual(len(self.before), len(self.output))
        actual = bytearray(decode_production(self.output).output)
        for r in self.report['owned_ranges']:
            at, size = r['offset'], r['size']
            actual[at:at+size] = self.raw[at:at+size]
        self.assertEqual(actual, self.raw)
        self.assertEqual(len(names.verify_keyword_names(self.output, self.readback)), 52)

    def test_idempotence(self):
        output, report = names.apply_keyword_names(self.output, self.table, self.overrides, self.readback)
        self.assertEqual(output, self.output)
        self.assertFalse(report['changed'])

    def test_two_byte_spaces_and_empty_label(self):
        data = decode_production(self.output).output
        for at in (0x88980, 0x88B78):
            text = data[at:data.index(0, at)]
            self.assertIn(b'\x81\x40', text)
            self.assertNotIn(b'\x20', text)
        target = struct.unpack_from('<I', data, names.EMPTY['pointer_offset'])[0] - names.BASE
        self.assertEqual(data[target], 0)

    def test_rejects_unknown_preimage(self):
        raw = bytearray(self.raw)
        raw[0x88980] ^= 1
        with self.assertRaisesRegex(ValueError, 'preimage drift'):
            names.patch_decoded(bytes(raw), self.table, self.overrides)

    def test_rejects_unexpected_reference(self):
        raw = bytearray(self.raw)
        struct.pack_into('<I', raw, 0x100, names.BASE+0x889E8)
        with self.assertRaisesRegex(ValueError, 'unexpected reference'):
            names.patch_decoded(bytes(raw), self.table, self.overrides)

    def test_rejects_pointer_drift(self):
        raw = bytearray(self.raw)
        struct.pack_into('<I', raw, names.TABLE+19*4, names.BASE+0x88900)
        with self.assertRaisesRegex(ValueError, 'pointer drift'):
            names.patch_decoded(bytes(raw), self.table, self.overrides)

    def test_rejects_menu_codes_missing_from_library_font(self):
        from migrate_slps_text import encoding_tables
        _, menu, _, _ = encoding_tables(ROOT/'work/build/special-disc/text-candidate/font/proposal.json')
        with self.assertRaisesRegex(ValueError, 'library stored-text encoding'):
            names.patch_decoded(self.raw, self.table, menu)


if __name__ == '__main__':
    unittest.main()
