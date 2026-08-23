import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.srwz.imagemagick import (
    _box_downsample_grayscale,
    _pixel_aligned_horizontal_shear,
    render_grayscale_text_mask,
    render_tim2_png8,
)


class ImageMagickAdapterTests(unittest.TestCase):
    def test_box_downsample_averages_exact_coverage_blocks(self):
        self.assertEqual(
            _box_downsample_grayscale(
                bytes((0, 64, 128, 255, 255, 128, 64, 0)),
                width=2,
                height=1,
                factor=2,
            ),
            bytes((112, 112)),
        )

    def test_pixel_aligned_shear_shifts_rows_without_interpolation(self):
        source = bytes(range(1, 16))
        self.assertEqual(
            _pixel_aligned_horizontal_shear(
                source,
                width=5,
                height=3,
                degrees=45,
            ),
            bytes(
                (
                    0, 1, 2, 3, 4,
                    6, 7, 8, 9, 10,
                    12, 13, 14, 15, 0,
                )
            ),
        )

    def test_tim2_png8_render_disables_palette_dithering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tm2"
            output = root / "output.png"
            source.write_bytes(b"fixture")

            def create_output(command, context):
                self.assertEqual(
                    command,
                    [
                        "magick",
                        str(source),
                        "+dither",
                        f"png8:{output}",
                    ],
                )
                self.assertEqual(
                    context,
                    f"ImageMagick TIM2 render for {source}",
                )
                output.write_bytes(b"png")
                return b""

            with patch(
                "tools.srwz.imagemagick._run",
                side_effect=create_output,
            ):
                render_tim2_png8("magick", source, output)

            self.assertEqual(output.read_bytes(), b"png")

    def test_text_mask_passes_integer_vertical_offset_to_both_layers(self):
        with tempfile.TemporaryDirectory() as directory:
            font = Path(directory) / "font.ttf"
            font.write_bytes(b"fixture")

            def render(command, context):
                self.assertEqual(
                    [
                        command[index + 1]
                        for index, value in enumerate(command)
                        if value == "-annotate"
                    ],
                    ["+0+3", "+0+3"],
                )
                self.assertEqual(context, "ImageMagick text mask for '攻略Q&A'")
                return bytes(118 * 32)

            with patch(
                "tools.srwz.imagemagick._run",
                side_effect=render,
            ):
                mask = render_grayscale_text_mask(
                    "magick",
                    font,
                    "攻略Q&A",
                    width=118,
                    height=32,
                    point_size=24,
                    stroke_gray="#303030",
                    stroke_width=1.25,
                    vertical_offset=3,
                )
            self.assertEqual(mask, bytes(118 * 32))


if __name__ == "__main__":
    unittest.main()
