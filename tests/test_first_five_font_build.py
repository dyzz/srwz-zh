import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    PROJECT_ROOT / "work/build/first-five/components/font-validation.json"
)


class FirstFiveFontBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))

    def test_selected_font_and_scope_are_bound_to_the_build(self):
        self.assertEqual(
            self.report["font_source"]["family"],
            "LXGW Neo XiHei Screen",
        )
        self.assertEqual(
            self.report["font_source"]["license_spdx"],
            "IPA",
        )
        self.assertEqual(self.report["allocation_assignment_count"], 630)
        self.assertEqual(
            self.report["reraster_existing_assignment_count"],
            807,
        )
        self.assertEqual(self.report["assignment_count"], 1437)
        self.assertEqual(self.report["changed_glyph_count"], 1436)
        self.assertEqual(self.report["unchanged_assignment_count"], 1)
        registry = self.report["allocation_registry"]
        self.assertEqual(registry["id"], "srwz-first-five-v1")
        self.assertEqual(registry["registered_character_count"], 638)
        self.assertEqual(registry["active_character_count"], 630)
        self.assertEqual(
            registry["retired_characters"],
            ["冈", "娅", "挖", "杰", "艾", "贯", "贾", "镥"],
        )

    def test_screenshot_failures_use_explicit_standard_branch_glyphs(self):
        glyphs = {
            glyph["character"]: glyph
            for glyph in self.report["glyphs"]
        }
        self.assertEqual(glyphs["0"]["code"], "9874")
        self.assertEqual(glyphs["仗"]["code"], "8560")
        self.assertEqual(glyphs["估"]["code"], "8562")
        self.assertEqual(glyphs["儿"]["code"], "8568")
        self.assertEqual(glyphs["隶"]["code"], "86E9")

    def test_runtime_small_glyphs_use_the_audited_optical_point_size(self):
        corrections = self.report["rasterizer"]["optical_corrections"]
        self.assertEqual(corrections["班"]["point_size"], 23.5)
        self.assertEqual(corrections["任"]["point_size"], 23.5)
        glyphs = {
            glyph["character"]: glyph
            for glyph in self.report["glyphs"]
        }
        self.assertEqual(glyphs["研"]["point_size"], 22)
        self.assertEqual(glyphs["究"]["point_size"], 22)
        self.assertEqual(glyphs["班"]["point_size"], 23.5)
        self.assertEqual(glyphs["任"]["point_size"], 23.5)
        self.assertEqual(
            glyphs["班"]["packed_glyph_sha256"],
            "d8050db8133cc5ebd615469557c34ec9866e45dbcc02b75ddbe081b0d2b11330",
        )
        self.assertEqual(
            glyphs["任"]["packed_glyph_sha256"],
            "990dc72dd95742f85ca82a4926615c61e05fbf63f808c6e083dd04fef9ee3d2d",
        )

    def test_rust_maximum_font_fits_without_growing_vt1(self):
        font = self.report["font"]
        archive = self.report["archive"]
        self.assertEqual(
            font["selected_encoder_strategy"],
            "rust-maximum",
        )
        self.assertEqual(font["min_match_length"], 2)
        self.assertEqual(font["max_match_chain"], 65535)
        self.assertTrue(font["lazy_matching"])
        self.assertTrue(font["codec_round_trip_exact"])
        self.assertEqual(archive["source_size"], archive["output_size"])
        self.assertTrue(archive["offset_reread_exact"])
        self.assertEqual(archive["padding_size"], 9)
        self.assertGreater(
            archive["borrowed_preceding_zero_slack"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
