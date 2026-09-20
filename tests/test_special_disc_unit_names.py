"""SP-native unit name coverage, codec preservation and failure guards."""
import json
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from special_disc.writeback import unit_names as names
from srwz.codec import decode_production
from srwz.font import standard_glyph_index, glyph_offset
from srwz.iso9660 import member_map, scan_iso9660


class SpecialDiscUnitNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from build_text_candidate import read_member
        from migrate_slps_text import encoding_tables
        cls.iso = ROOT / 'build/iso/special-disc/full-text/sp-zh-full-text.iso'
        proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
        if not cls.iso.exists() or not proposal.exists():
            raise unittest.SkipTest('requires local SP candidate ISO and verified font proposal')
        cls.proposal = json.loads(proposal.read_text())
        cls.table, cls.overrides, _, cls.readback = encoding_tables(proposal)
        members = member_map(scan_iso9660(cls.iso))
        cls.before = read_member(cls.iso, members, names.MEMBER)
        exe = read_member(cls.iso, members, 'SLPS_259.20')
        a, b = struct.unpack_from('<2I', exe, 0x353790 + 12)
        with cls.iso.open('rb') as stream:
            stream.seek(members['DATA/VT1.BIN'].extent_lba * 2048 + a)
            cls.font = decode_production(stream.read(b - a)).output
        cls.contract, cls.rows, cls.corpus_path = names.inputs()
        cls.output, cls.report = cls.apply(cls.before)

    @classmethod
    def apply(cls, archive):
        return names.apply_unit_names(archive, cls.table, cls.overrides, cls.readback,
                                      cls.font, cls.proposal)

    def test_all_five_names_and_nine_pointers(self):
        labels = names.verify_unit_names(self.output, self.readback)
        self.assertEqual([r['translation'] for r in labels],
                         ['XAN-斩-', '出云舰', '巴尔戈拉（Ⅰ号机）',
                          '巴尔戈拉（Ⅱ号机）', '雷姆雷斯试作型'])
        self.assertEqual(self.report['entries'], 5)
        self.assertEqual(self.report['pointer_count'], 9)
        self.assertLessEqual(self.report['compressed_bytes'], len(self.before))

    def test_only_name_spans_change_and_archive_size_is_fixed(self):
        old = decode_production(self.before).output
        restored = bytearray(decode_production(self.output).output)
        for slot in self.contract['entries']:
            at, size = slot['offset'], slot['capacity']
            restored[at:at+size] = old[at:at+size]
        self.assertEqual(bytes(restored), old)
        self.assertEqual(len(self.output), len(self.before))

    def test_idempotent(self):
        output, report = self.apply(self.output)
        self.assertEqual(output, self.output)
        self.assertEqual(report['changed_ids'], [])

    def test_rejects_missing_duplicate_and_redirected_pointers(self):
        original = decode_production(self.output).output
        slot = self.contract['entries'][1]
        for at, value in [(slot['pointer_sites'][0], 0),
                          (slot['pointer_sites'][0], self.contract['base_address'] + slot['offset'] + 2),
                          (self.contract['unit_table']['start'], self.contract['base_address'] + slot['offset'])]:
            with self.subTest(offset=at, value=value):
                data = bytearray(original)
                struct.pack_into('<I', data, at, value)
                with self.assertRaisesRegex(ValueError, 'pointer drift'):
                    names.check_pointers(data, self.contract)

    def test_rejects_damaged_preserved_roman_numeral(self):
        font = bytearray(self.font)
        font[glyph_offset(standard_glyph_index(0x8754))] ^= 1
        with self.assertRaisesRegex(ValueError, 'glyph pixels drift'):
            names.verify_unit_name_glyphs(bytes(font), self.proposal, self.table, self.overrides)

    def test_rejects_overflow_without_truncation(self):
        rows = {key: dict(row) for key, row in self.rows.items()}
        rows['sd/compdata/85198']['translation'] = '出云舰' * 5
        with patch.object(names, 'inputs', return_value=(self.contract, rows, self.corpus_path)):
            with self.assertRaisesRegex(ValueError, 'overflow'):
                self.apply(self.before)

    def test_rejects_unknown_preimage(self):
        # A source record from an unexpected build must not be blindly overwritten.
        from dataclasses import replace
        decoded = decode_production(self.before)
        data = bytearray(decoded.output)
        data[0x85198] ^= 1
        with patch.object(names, 'decode_production', return_value=replace(decoded, output=bytes(data))):
            with self.assertRaisesRegex(ValueError, 'preimage drift'):
                self.apply(self.before)


if __name__ == '__main__':
    unittest.main()
