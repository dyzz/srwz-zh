import unittest

from tools.build_full_story_components import _render_title_glyph
from tools.srwz.psmt4 import (
    PACKED_SIZE,
    PIXEL_COUNT,
    Psmt4Error,
    supports_psmt4_geometry,
    swizzle_psmt4,
    unswizzle_psmt4,
)


class Psmt4Tests(unittest.TestCase):
    def test_native_title_crop_preserves_height_and_4bpp_values(self):
        glyph = bytes((x + y) & 0x0F for y in range(24) for x in range(24))
        rendered = _render_title_glyph(glyph, output_width=20)
        self.assertEqual(len(rendered), 24 * 20)
        for y in range(24):
            self.assertEqual(
                rendered[y * 20 : (y + 1) * 20],
                glyph[y * 24 + 2 : y * 24 + 22],
            )
        self.assertTrue(any(0 < pixel < 15 for pixel in rendered))

    def test_round_trip_covers_every_nibble(self):
        logical = bytes((x * 3 + y * 5) & 0x0F for y in range(256) for x in range(256))
        stored = swizzle_psmt4(logical)
        self.assertEqual(len(stored), PACKED_SIZE)
        self.assertEqual(unswizzle_psmt4(stored), logical)

    def test_round_trip_covers_observed_veff_geometries(self):
        for width, height in (
            (32, 32),
            (64, 64),
            (128, 128),
            (256, 128),
            (256, 256),
            (512, 256),
            (512, 512),
        ):
            with self.subTest(width=width, height=height):
                logical = bytes(
                    (x * 3 + y * 5) & 0x0F
                    for y in range(height)
                    for x in range(width)
                )
                stored = swizzle_psmt4(logical, width, height)
                self.assertEqual(len(stored), width * height // 2)
                self.assertEqual(
                    unswizzle_psmt4(stored, width, height),
                    logical,
                )

    def test_rejects_non_power_of_two_geometry_without_buffer_width(self):
        self.assertFalse(supports_psmt4_geometry(640, 448))
        with self.assertRaises(Psmt4Error):
            unswizzle_psmt4(bytes(640 * 448 // 2), 640, 448)

    def test_rejects_invalid_sizes_and_pixels(self):
        with self.assertRaises(Psmt4Error):
            unswizzle_psmt4(bytes(PACKED_SIZE - 1))
        with self.assertRaises(Psmt4Error):
            swizzle_psmt4(bytes(PIXEL_COUNT - 1))
        with self.assertRaises(Psmt4Error):
            swizzle_psmt4(bytes([16]) + bytes(PIXEL_COUNT - 1))


if __name__ == "__main__":
    unittest.main()
