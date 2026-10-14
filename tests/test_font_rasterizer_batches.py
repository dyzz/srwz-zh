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
