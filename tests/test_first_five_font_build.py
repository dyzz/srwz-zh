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
            "HarmonyOS Sans SC",
        )
        self.assertEqual(
            self.report["font_source"]["license_spdx"],
            "LicenseRef-HarmonyOS-Sans-Fonts-License",
        )
        self.assertEqual(
            self.report["font_flavor"]["font_flavor_id"],
            "srwz-zh-harmonyos-sans-sc-regular-v1",
        )
        self.assertEqual(self.report["allocation_assignment_count"], 627)
        self.assertEqual(
            self.report["reraster_existing_assignment_count"],
            807,
        )
        self.assertEqual(self.report["assignment_count"], 1434)
        self.assertEqual(self.report["changed_glyph_count"], 1433)
        self.assertEqual(self.report["unchanged_assignment_count"], 1)
        registry = self.report["allocation_registry"]
        self.assertEqual(registry["id"], "srwz-first-five-v1")
        self.assertEqual(registry["registered_character_count"], 638)
        self.assertEqual(registry["active_character_count"], 627)
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

    def test_cjk_glyphs_use_one_fixed_canvas_without_exceptions(self):
        rasterizer = self.report["rasterizer"]
        self.assertNotIn("optical_corrections", rasterizer)
        self.assertNotIn("cjk_bbox_normalization", rasterizer)
        fixed_canvas = rasterizer["cjk_fixed_canvas"]
        self.assertEqual(fixed_canvas["x_offset"], 0)
        self.assertEqual(fixed_canvas["y_offset"], 1)
        self.assertEqual(rasterizer["point_size"], 22)
        glyphs = {
            glyph["character"]: glyph
            for glyph in self.report["glyphs"]
        }
        for character in "一口研究班任坠您尔":
            self.assertEqual(glyphs[character]["point_size"], 22)
        self.assertEqual(
            glyphs["班"]["packed_glyph_sha256"],
            "06742f8fda770e42c06d9a8df25b80c3891ff7ff9df2a3a4625934e1d789c56a",
        )
        self.assertEqual(
            glyphs["任"]["packed_glyph_sha256"],
            "3c22f17abfccf5d32b333b92fc72bfe34b541333a3aa8147a30e5ccf3e299691",
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
        self.assertEqual(archive["padding_size"], 3)
        self.assertGreater(
            archive["borrowed_preceding_zero_slack"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
