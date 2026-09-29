"""Full SP roster coverage must detect omissions beyond Japanese kana residue."""
import json
import struct
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from special_disc.verification import name_tables as audit
from special_disc.writeback.unit_names import apply_unit_names
from special_disc.writeback.pilot_names import apply_pilot_names
from special_disc.writeback.migrate_slps_text import encoding_tables
from special_disc.source import CURRENT_ISO, SOURCE_ISO
from srwz.codec import decode_production
from srwz.iso9660 import member_map, scan_iso9660
from srwz.text import encode_text
from srwz.font import glyph_offset, standard_glyph_index


class SpecialDiscNameTablesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
        if not CURRENT_ISO.exists() or not SOURCE_ISO.exists() or not proposal.exists():
            raise unittest.SkipTest('requires local SP sources and shared font')
        from build_text_candidate import read_member
        members = member_map(scan_iso9660(CURRENT_ISO))
        cls.before = read_member(CURRENT_ISO, members, 'DATA/COMPDATA.BN')
        cls.source = read_member(SOURCE_ISO, member_map(scan_iso9660(SOURCE_ISO)), 'DATA/COMPDATA.BN')
        cls.exe = read_member(CURRENT_ISO, members, 'SLPS_259.20')
        a, b = struct.unpack_from('<II', cls.exe, 0x353790 + 12)
        with CURRENT_ISO.open('rb') as f:
            f.seek(members['DATA/VT1.BIN'].extent_lba * 2048 + a)
            cls.font = decode_production(f.read(b-a)).output
        cls.proposal = json.loads(proposal.read_text())
        cls.table, _, cls.overrides, cls.readback = encoding_tables(proposal)
        units, _ = apply_unit_names(cls.before, cls.table, cls.overrides, cls.readback, cls.font, cls.proposal)
        cls.output, _ = apply_pilot_names(units, cls.table, cls.overrides, cls.readback)

    def verify(self, font=None):
        return audit.verify_name_tables(self.output, self.source, font or self.font,
            self.proposal, self.readback, self.table, self.exe)

    def test_every_unit_and_pilot_name_has_a_verified_translation_and_glyph(self):
        result = self.verify()
        self.assertEqual((result['unit_records'], result['pilot_records'], result['pilot_fields']), (854, 969, 2907))
        self.assertEqual(result['pilot_nonempty_fields'], 2552)
        for key in ('kana_residue', 'unknown_codes', 'blank_nonspace_glyphs', 'unbound_names', 'translation_mismatches'):
            self.assertEqual(result[key], 0)

    def test_chinese_garbage_is_rejected_even_without_kana(self):
        decoded = decode_production(self.output)
        broken = bytearray(decoded.output)
        at = 0x2B50 + 770 * 178 + 2
        raw = encode_text('亲徜', self.table, overrides=self.overrides, terminate=True)
        broken[at:at+21] = raw + bytes(21-len(raw))
        with patch.object(audit, 'decode_production', side_effect=[replace(decoded, output=bytes(broken)), decode_production(self.source)]):
            with self.assertRaisesRegex(ValueError, 'translation mismatch'):
                self.verify()

    def test_blank_canonical_glyph_cannot_pass_text_readback(self):
        broken = bytearray(self.font)
        at = glyph_offset(standard_glyph_index(0x9247))
        broken[at:at+288] = bytes(288)
        with self.assertRaisesRegex(ValueError, 'blank glyph'):
            self.verify(bytes(broken))

    def test_unknown_shared_name_cannot_silently_pass(self):
        reference = json.loads(audit.REFERENCE.read_text())
        del reference['units']['マジンガーＺ']
        original = Path.read_text
        def read(path, *args, **kwargs):
            return json.dumps(reference) if path == audit.REFERENCE else original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            with self.assertRaisesRegex(ValueError, 'no translation binding'):
                self.verify()


if __name__ == '__main__':
    unittest.main()
