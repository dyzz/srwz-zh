import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz.font import GLYPH_COUNT, GLYPH_SIZE, encode_glyph, standard_glyph_index
from srwz.font_rasterizer import quantize_gray_4bpp
from srwz.native_period import PERIOD_CHARACTERS, native_period_metadata, native_period_raster, replace_period_slots


class NativePeriodTests(unittest.TestCase):
    def test_native_indexes_survive_without_rerasterizing_or_requantizing(self):
        font = bytearray(GLYPH_COUNT * GLYPH_SIZE)
        pixels = bytes(i % 16 for i in range(576))
        start = standard_glyph_index(0x8144) * GLYPH_SIZE
        font[start:start + GLYPH_SIZE] = encode_glyph(pixels)
        gray, actual, packed = native_period_raster(bytes(font))
        self.assertEqual(actual, pixels)
        self.assertEqual(packed, font[start:start + GLYPH_SIZE])
        self.assertEqual(quantize_gray_4bpp(gray), pixels)
        self.assertEqual(native_period_metadata(bytes(font))["source_code"], "8144")

    def test_blank_source_is_rejected_and_other_punctuation_is_excluded(self):
        with self.assertRaisesRegex(ValueError, "blank"):
            native_period_raster(bytes(GLYPH_COUNT * GLYPH_SIZE))
        self.assertEqual(PERIOD_CHARACTERS, {".", "．"})
        self.assertFalse(PERIOD_CHARACTERS.intersection("。…·，"))

    def test_existing_font_changes_only_owned_period_slots_and_is_idempotent(self):
        source = bytearray(GLYPH_COUNT * GLYPH_SIZE)
        source[4 * GLYPH_SIZE:5 * GLYPH_SIZE] = bytes([0x79]) * GLYPH_SIZE
        before = bytes([0x36]) * len(source)
        rows = [dict(character='．', glyph_index=2836), dict(character='.', glyph_index=4467)]
        after, changed = replace_period_slots(before, bytes(source), rows)
        self.assertEqual(changed, [2836, 4467])
        for index in range(GLYPH_COUNT):
            span = slice(index * GLYPH_SIZE, (index + 1) * GLYPH_SIZE)
            self.assertEqual(after[span], bytes([0x79]) * GLYPH_SIZE if index in changed else before[span])
        self.assertEqual(replace_period_slots(after, bytes(source), rows), (after, []))
        with self.assertRaisesRegex(ValueError, 'shared non-period'):
            replace_period_slots(before, bytes(source), rows + [dict(character='。', glyph_index=2836)])


if __name__ == "__main__":
    unittest.main()
