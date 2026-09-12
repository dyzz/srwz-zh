from __future__ import annotations

import unittest

from tools.srwz.stage_title_graphics import (
    GLYPH_HEIGHT,
    GLYPH_WIDTH,
    LatinLayout,
    StageTitleGraphicError,
    TITLE_WIDTH,
    glyph_ink_columns,
    layout_title_cells,
    render_stage_title,
)


def _glyph(x0: int, x1: int, value: int = 15) -> bytes:
    """Return a 24x24 glyph whose ink fills columns x0..x1 on every row."""

    glyph = bytearray(GLYPH_WIDTH * GLYPH_HEIGHT)
    for y in range(GLYPH_HEIGHT):
        for x in range(x0, x1 + 1):
            glyph[y * GLYPH_WIDTH + x] = value
    return bytes(glyph)


GLYPHS = {
    "汉": _glyph(0, 23),
    "字": _glyph(1, 22),
    "B": _glyph(6, 17),  # 12 px ink
    "l": _glyph(10, 12),  # 3 px ink
    "u": _glyph(6, 17),
    "e": _glyph(6, 17),
    "S": _glyph(6, 17),
    "k": _glyph(6, 16),
    "y": _glyph(6, 17),
    "F": _glyph(7, 16),
    "i": _glyph(11, 13),
    "s": _glyph(7, 16),
    "h": _glyph(6, 17),
    " ": bytes(GLYPH_WIDTH * GLYPH_HEIGHT),
}


class StageTitleLayoutTest(unittest.TestCase):
    def test_fixed_cells_reproduce_stock_geometry(self) -> None:
        cells, natural = layout_title_cells("汉字B", GLYPHS)
        self.assertEqual(natural, 2 * 50 + 48)
        self.assertEqual([cell.doubled_width for cell in cells], [48, 48, 48])
        raster = render_stage_title("汉字B", GLYPHS)
        self.assertEqual(raster.natural_width, 148)
        self.assertEqual(raster.layout_mode, "fixed_cells")
        self.assertEqual(raster.latin_cell_count, 0)
        self.assertEqual(raster.x, (TITLE_WIDTH - 148) // 2)

    def test_proportional_latin_uses_ink_width(self) -> None:
        layout = LatinLayout(letter_gap=2, space_width=8)
        cells, natural = layout_title_cells("Blue Sky", GLYPHS, latin_layout=layout)
        widths = [cell.doubled_width for cell in cells]
        self.assertEqual(widths, [24, 6, 24, 24, 16, 24, 22, 24])
        gaps = [cell.trailing_gap for cell in cells]
        self.assertEqual(gaps, [4, 4, 4, 4, 0, 4, 4, 4])
        self.assertEqual(natural, sum(widths) + sum(gaps[:-1]))
        self.assertLess(natural, 512)
        raster = render_stage_title("Blue Sky", GLYPHS, latin_layout=layout)
        self.assertEqual(raster.latin_cell_count, 8)
        self.assertEqual(raster.layout_mode, "proportional_stock_glyphs")
        # The rendered ink must start exactly at the centered origin and the
        # first Latin cell must be the glyph's ink columns, not the empty cell.
        row = raster.indexes[raster.y * TITLE_WIDTH : (raster.y + 1) * TITLE_WIDTH]
        first = next(x for x, value in enumerate(row) if value)
        self.assertEqual(first, raster.x)
        self.assertEqual(row[raster.x : raster.x + 24], bytes([15]) * 24)
        self.assertEqual(row[raster.x + 24 : raster.x + 28], bytes(4))

    def test_thirteen_cell_latin_title_no_longer_squeezes(self) -> None:
        layout = LatinLayout()
        fixed = render_stage_title("Blue Sky Fish", GLYPHS)
        proportional = render_stage_title("Blue Sky Fish", GLYPHS, latin_layout=layout)
        self.assertGreater(fixed.natural_width, TITLE_WIDTH)
        self.assertEqual(fixed.width, TITLE_WIDTH)
        self.assertLessEqual(proportional.natural_width, TITLE_WIDTH)
        self.assertEqual(proportional.width, proportional.natural_width)

    def test_mixed_title_keeps_cjk_cells(self) -> None:
        layout = LatinLayout()
        cells, natural = layout_title_cells("汉Bl字", GLYPHS, latin_layout=layout)
        self.assertEqual([cell.latin for cell in cells], [False, True, True, False])
        self.assertEqual([cell.doubled_width for cell in cells], [48, 24, 6, 48])
        self.assertEqual([cell.trailing_gap for cell in cells], [2, 4, 4, 2])
        self.assertEqual(natural, 48 + 2 + 24 + 4 + 6 + 4 + 48)

    def test_blank_latin_glyph_and_bad_policy_fail_closed(self) -> None:
        glyphs = dict(GLYPHS)
        glyphs["B"] = bytes(GLYPH_WIDTH * GLYPH_HEIGHT)
        with self.assertRaisesRegex(StageTitleGraphicError, "Latin glyph is blank"):
            layout_title_cells("B", glyphs, latin_layout=LatinLayout())
        with self.assertRaisesRegex(StageTitleGraphicError, "letter_gap"):
            LatinLayout(letter_gap=9).validate()
        with self.assertRaisesRegex(StageTitleGraphicError, "layout mode"):
            LatinLayout(mode="other").validate()
        self.assertIsNone(glyph_ink_columns(bytes(GLYPH_WIDTH * GLYPH_HEIGHT)))
        self.assertEqual(glyph_ink_columns(GLYPHS["l"]), (10, 12))


if __name__ == "__main__":
    unittest.main()
