import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from tools import build_zh_font_component as font_build
from srwz.font import decode_glyph


class FontRasterHandoffTests(unittest.TestCase):
    def test_proposal_drift_cannot_reuse_rasters(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rasters.json"
            proposal = b"locked proposal"
            path.write_text(json.dumps({"schema_version": 1,
                "proposal_sha256": hashlib.sha256(proposal).hexdigest(),
                "gray_by_character": {"中": "00"}}))
            self.assertEqual(font_build._load_raster_handoff(path, proposal), {"中": "00"})
            with self.assertRaisesRegex(ValueError, "proposal drift"):
                font_build._load_raster_handoff(path, b"changed proposal")

    def test_handoff_retains_gray_quantization_and_packed_pixels(self):
        gray = bytes(i % 256 for i in range(24 * 24))
        result_gray, pixels, packed = font_build._handoff_raster(
            gray.hex(), hashlib.sha256(gray).hexdigest())
        self.assertEqual(result_gray, gray)
        self.assertEqual(pixels, bytes(round(value * 15 / 255) for value in gray))
        self.assertEqual(decode_glyph(packed, 0), pixels)

    def test_corrupt_glyph_and_wrong_canvas_are_rejected(self):
        gray = bytes(24 * 24)
        digest = hashlib.sha256(gray).hexdigest()
        for damaged in (gray[:-1], bytes([1]) + gray[1:]):
            with self.assertRaisesRegex(ValueError, "glyph drift"):
                font_build._handoff_raster(damaged.hex(), digest)


if __name__ == "__main__":
    unittest.main()
