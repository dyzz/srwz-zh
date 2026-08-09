import unittest

from tools.srwz.stage_title_graphics import (
    GLYPH_SIZE,
    TITLE_HEIGHT,
    TITLE_IMAGE_SIZE,
    TITLE_WIDTH,
    StageTitleGraphicError,
    pack_linear_4bpp,
    render_stage_title,
    unpack_linear_4bpp,
)


class StageTitleGraphicTests(unittest.TestCase):
    def test_linear_4bpp_round_trip(self):
        indexes = bytes(index % 16 for index in range(TITLE_WIDTH * TITLE_HEIGHT))
        packed = pack_linear_4bpp(indexes)
        self.assertEqual(len(packed), TITLE_IMAGE_SIZE)
        self.assertEqual(unpack_linear_4bpp(packed), indexes)

    def test_four_glyph_title_uses_stock_geometry(self):
        glyph = bytes([15]) * GLYPH_SIZE
        raster = render_stage_title("标题测试", {c: glyph for c in "标题测试"})
        self.assertEqual(raster.natural_width, 198)
        self.assertEqual(raster.width, 198)
        self.assertEqual(raster.x, 157)
        self.assertEqual(raster.y, 4)
        self.assertEqual(sum(bool(value) for value in raster.indexes), 48 * 24 * 4)

    def test_long_title_is_fit_inside_texture(self):
        glyph = bytes([15]) * GLYPH_SIZE
        text = "一二三四五六七八九十甲乙"
        raster = render_stage_title(text, {c: glyph for c in text})
        self.assertGreater(raster.natural_width, TITLE_WIDTH)
        self.assertEqual(raster.width, TITLE_WIDTH)
        self.assertEqual(raster.x, 0)

    def test_quantization_reduces_index_levels(self):
        glyph = bytes(index % 16 for index in range(GLYPH_SIZE))
        raster = render_stage_title("题", {"题": glyph}, quantization_levels=8)
        self.assertLessEqual(len(set(raster.indexes)), 8)

    def test_missing_glyph_is_rejected(self):
        with self.assertRaises(StageTitleGraphicError):
            render_stage_title("缺", {})


if __name__ == "__main__":
    unittest.main()
