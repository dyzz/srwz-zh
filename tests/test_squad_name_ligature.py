import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.font import encode_glyph, standard_glyph_index
from tools.srwz.squad_name_ligature import (
    CHARACTER, CODE, GLYPH_INDEX, stored_squad_name, logical_squad_name,
    ligature_raster, validate_ligature_assignment,
)

ROOT = Path(__file__).resolve().parents[1]


class SquadNameLigatureTests(unittest.TestCase):
    def test_only_source_bound_squad_name_uses_private_storage_character(self):
        stored = stored_squad_name('ザ・ヒート', 'THE HEAT')
        self.assertEqual(stored, 'TH' + CHARACTER + 'HEAT')
        self.assertEqual(logical_squad_name(stored), 'THE\u3000HEAT')
        for source, text in [('別働隊', 'THE HEAT'), ('ザ・ヒート', 'THE CRUSHER'),
                             ('ザ・ビッグ', 'The Big')]:
            self.assertNotIn(CHARACTER, stored_squad_name(source, text))

    def test_allocation_is_unique_and_removed_from_future_candidates(self):
        snapshot = json.loads((ROOT/'config/encoding/zh-release-font-assignments.json').read_text())
        rows = [r for r in snapshot['primary_assignments'] if r['character'] == CHARACTER]
        self.assertEqual(len(rows), 1)
        validate_ligature_assignment(rows[0])
        self.assertEqual((int(rows[0]['code'], 16), rows[0]['glyph_index']), (CODE, GLYPH_INDEX))
        self.assertNotIn('97F0', [r['code'] for r in snapshot['remaining_allocation_candidates']])
        invalid = dict(rows[0], code='97F8')
        with self.assertRaisesRegex(ValueError, 'allocation drift'):
            validate_ligature_assignment(invalid)

    def test_stock_letter_sampling_keeps_baseline_and_word_blank(self):
        # A deterministic stock-shaped fixture detects axis/stride mistakes and
        # proves the new glyph leaves all rows and non-letter columns blank.
        pixels = bytes(15 if 4 <= y <= 19 and 5 <= x <= 19 else 0
                       for y in range(24) for x in range(24))
        source = bytearray((standard_glyph_index(0x8264)+1)*288)
        source[-288:] = encode_glyph(pixels)
        gray, actual, packed = ligature_raster(bytes(source))
        expected = bytes(15 if 4 <= y <= 19 and 3 <= x <= 12 else 0
                         for y in range(24) for x in range(24))
        self.assertEqual(actual, expected)
        self.assertEqual(gray, bytes(x*17 for x in expected))
        self.assertEqual(packed, encode_glyph(expected))
        with self.assertRaisesRegex(ValueError, 'geometry drift'):
            ligature_raster(bytes(len(source)))


if __name__ == '__main__':
    unittest.main()
