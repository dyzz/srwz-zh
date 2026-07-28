import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.srwz.imagemagick import render_tim2_png8


class ImageMagickAdapterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
