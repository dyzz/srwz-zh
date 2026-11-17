import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from srwz.font import (  # noqa: E402
    GLYPH_COUNT,
    LINEAR_GLYPH_START,
    ExtendedGlyphEntry,
    FontCapacity,
    font_capacity,
    glyph_index_for_code,
    linear_area_codes,
    linear_glyph_index,
)


def entry(code, index):
    return ExtendedGlyphEntry(code=code, row=index // 224, packed_position=index % 224, glyph_index=index, table_offset=0)


class FontLinearAreaTests(unittest.TestCase):
    def test_absent_capacity_is_the_stock_store(self):
        self.assertEqual(font_capacity({}), FontCapacity(GLYPH_COUNT, False))

    def test_capacity_must_be_whole_linear_rows(self):
        self.assertEqual(font_capacity({"font_capacity": {"glyph_count": 4800, "linear_area": True}}), FontCapacity(4800, True))
        for bad in ({"glyph_count": 4700, "linear_area": True}, {"glyph_count": 4608, "linear_area": True},
                    {"glyph_count": 4800, "linear_area": False}, {"glyph_count": 4800}, {"glyph_count": 4800, "linear_area": True, "x": 1}):
            with self.assertRaises(ValueError):
                font_capacity({"font_capacity": bad})

    def test_linear_formula_and_bounds(self):
        self.assertEqual(LINEAR_GLYPH_START, 4608)
        self.assertEqual(linear_glyph_index(0x9940, glyph_count=4800), 4608)
        self.assertEqual(linear_glyph_index(0x99FF, glyph_count=4800), 4799)
        for code in (0x9A40, 0x9840, 0x993F):
            with self.assertRaises(ValueError):
                linear_glyph_index(code, glyph_count=4800)

    def test_table_wins_and_linear_needs_the_flag(self):
        table = [entry(0x9941, 100)]
        self.assertEqual(glyph_index_for_code(0x9941, table, glyph_count=4800, linear=True), 100)
        self.assertEqual(glyph_index_for_code(0x9942, table, glyph_count=4800, linear=True), 4610)
        with self.assertRaises(ValueError):
            glyph_index_for_code(0x9942, table, glyph_count=4800)

    def test_linear_area_codes_skip_shadowed_codes(self):
        rows = linear_area_codes([entry(0x9941, 100)], glyph_count=4800)
        self.assertEqual(len(rows), 191)
        self.assertNotIn(0x9941, {code for code, _ in rows})
        self.assertEqual(rows[0], (0x9940, 4608))


if __name__ == "__main__":
    unittest.main()
