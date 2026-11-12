"""Batched glyph rendering returns the bytes of the single-glyph pipeline."""
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz import font_rasterizer

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf"
RASTERIZER = {"executable": "magick", "density": 72, "point_size": 22, "hinting": False,
              "antialias": True, "gravity": "center",
              "cjk_fixed_canvas": {"x_offset": 0, "y_offset": 1, "reason": "test"}}


@unittest.skipUnless(shutil.which("magick") and FONT.is_file(), "requires ImageMagick and the release font")
class BatchedRasterTests(unittest.TestCase):
    def test_batches_match_single_glyph_pipeline(self):
        characters = ["机", "器", "人", " ", "战", "Ａ"]
        batched = font_rasterizer.rasterize_characters("magick", lambda c: FONT, characters, RASTERIZER,
                                                       batch_size=2, workers=2)
        for character in characters:
            self.assertEqual(batched[character],
                             font_rasterizer.rasterize_character("magick", FONT, character, RASTERIZER), character)
        self.assertTrue(any(batched["机"][0]))
        self.assertFalse(any(batched[" "][0]))

    def test_glyph_arguments_end_without_an_output(self):
        arguments = font_rasterizer._glyph_arguments(FONT, "机", RASTERIZER)
        self.assertEqual(arguments[-4:], ["-colorspace", "Gray", "-depth", "8"])
        self.assertNotIn("gray:-", arguments)


if __name__ == "__main__":
    unittest.main()


class BottomRowDropTests(unittest.TestCase):
    POLICY = {**RASTERIZER, "cjk_bottom_row_drop": {"ink_bottom_row": 20, "ink_threshold": 8, "rows": 1, "reason": "test"}}

    @staticmethod
    def canvas(top, bottom, faint_row=None):
        gray = bytearray(24 * 24)
        for row in range(top, bottom + 1):
            gray[row * 24 + 5:row * 24 + 19] = bytes([255]) * 14
        if faint_row is not None:
            gray[faint_row * 24 + 5:faint_row * 24 + 19] = bytes([34]) * 14  # quantizes to 2, below the threshold
        return bytes(gray)

    def rows(self, gray):
        pixels = font_rasterizer.quantize_gray_4bpp(gray)
        inked = [row for row in range(24) if any(value >= 8 for value in pixels[row * 24:(row + 1) * 24])]
        return inked[0], inked[-1]

    def test_only_ideographs_ending_on_the_configured_row_move(self):
        drop = font_rasterizer.apply_bottom_row_drop
        self.assertEqual(self.rows(drop(self.canvas(2, 20, faint_row=21), "说", self.POLICY)), (3, 21))
        self.assertEqual(self.rows(drop(self.canvas(3, 20), "距", self.POLICY)), (4, 21))
        for top, bottom in ((1, 21), (2, 19), (2, 22)):
            gray = self.canvas(top, bottom)
            self.assertEqual(drop(gray, "离", self.POLICY), gray)
        for character in "A0，。あ":
            gray = self.canvas(2, 20)
            self.assertEqual(drop(gray, character, self.POLICY), gray)
        self.assertEqual(drop(self.canvas(2, 20), "说", RASTERIZER), self.canvas(2, 20))

    def test_policy_is_validated(self):
        bad = {**RASTERIZER, "cjk_bottom_row_drop": {"ink_bottom_row": 23, "ink_threshold": 8, "rows": 1, "reason": "x"}}
        with self.assertRaises(font_rasterizer.FontRasterizerError):
            font_rasterizer.apply_bottom_row_drop(self.canvas(2, 20), "说", bad)
        without_canvas = {k: v for k, v in self.POLICY.items() if k != "cjk_fixed_canvas"}
        with self.assertRaises(font_rasterizer.FontRasterizerError):
            font_rasterizer.apply_bottom_row_drop(self.canvas(2, 20), "说", without_canvas)
