import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.font import GLYPH_COUNT, GLYPH_SIZE, standard_glyph_index
from srwz.native_parentheses import replace_parenthesis_slots


class NativeParenthesesTests(unittest.TestCase):
    def setUp(self):
        self.source = bytearray(GLYPH_COUNT * GLYPH_SIZE)
        for code, value in ((0x8169, 0x79), (0x816A, 0xA4)):
            start = standard_glyph_index(code) * GLYPH_SIZE
            self.source[start:start+GLYPH_SIZE] = bytes([value]) * GLYPH_SIZE
        self.rows = [dict(character='（', glyph_index=2856),
                     dict(character='）', glyph_index=2859)]

    def test_preserves_all_other_glyphs_and_is_idempotent(self):
        before = bytes([0x36]) * len(self.source)
        after, report = replace_parenthesis_slots(before, bytes(self.source), self.rows)
        self.assertEqual(report['changed_glyphs'], [2856, 2859])
        for index in range(GLYPH_COUNT):
            span = slice(index*GLYPH_SIZE, (index+1)*GLYPH_SIZE)
            expected = (bytes([0x79])*GLYPH_SIZE if index == 2856 else
                        bytes([0xA4])*GLYPH_SIZE if index == 2859 else before[span])
            self.assertEqual(after[span], expected)
        again, proof = replace_parenthesis_slots(after, bytes(self.source), self.rows)
        self.assertEqual(again, after)
        self.assertEqual(proof['changed_glyphs'], [])
        self.assertEqual(proof['copies'], report['copies'])

    def test_rejects_blank_source_and_missing_or_shared_slots(self):
        before = bytes(self.source)
        with self.assertRaisesRegex(ValueError, 'blank'):
            replace_parenthesis_slots(before, bytes(len(before)), self.rows)
        with self.assertRaisesRegex(ValueError, 'missing'):
            replace_parenthesis_slots(before, before, self.rows[:1])
        with self.assertRaisesRegex(ValueError, 'shared non-parenthesis'):
            replace_parenthesis_slots(before, before, self.rows+[dict(character='。', glyph_index=2856)])
        with self.assertRaisesRegex(ValueError, 'outside'):
            replace_parenthesis_slots(before, before,
                                      [self.rows[0],dict(character='）', glyph_index=GLYPH_COUNT)])


if __name__ == '__main__':
    unittest.main()
