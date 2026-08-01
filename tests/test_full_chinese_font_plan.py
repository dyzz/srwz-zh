import json
import unittest
from pathlib import Path

from tools.srwz.full_font_plan import audit_full_chinese_font_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/fonts/full-chinese-font-plan.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/full-chinese-font-plan.json"


class FullChineseFontPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit_full_chinese_font_plan(PROJECT_ROOT, CONFIG_PATH)
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_committed_plan_matches_all_current_chinese_corpus(self):
        self.assertEqual(self.report, self.manifest)
        inventory = self.report["translation_inventory"]
        self.assertEqual(inventory["unique_double_byte_character_count"], 1899)
        self.assertEqual(inventory["unique_cjk_ideograph_count"], 1847)
        self.assertEqual(
            inventory["unique_non_cjk_double_byte_character_count"],
            52,
        )

    def test_renderer_has_one_sequential_code_for_every_glyph(self):
        geometry = self.report["renderer_geometry"]
        self.assertEqual(geometry["glyph_count"], 4480)
        self.assertEqual(geometry["first_code"], "8140")
        self.assertEqual(geometry["first_row_last_code"], "81FF")
        self.assertEqual(geometry["second_row_first_code"], "8240")
        self.assertEqual(geometry["last_code"], "987F")
        self.assertTrue(geometry["code_to_glyph_round_trip_exact"])

    def test_only_ascii_is_reserved_and_current_corpus_fits(self):
        self.assertEqual(
            self.report["reserved_slots"]["printable_ascii_glyph_count"],
            95,
        )
        self.assertEqual(
            self.report["reserved_slots"]["original_japanese_glyph_count"],
            0,
        )
        capacity = self.report["capacity"]
        self.assertEqual(capacity["sequential_translation_slot_count"], 4193)
        self.assertEqual(capacity["current_required_slot_count"], 1899)
        self.assertEqual(capacity["current_remaining_slot_count"], 2294)
        self.assertEqual(capacity["first_translation_glyph_index"], 287)
        self.assertEqual(capacity["first_translation_code"], "829F")
        self.assertEqual(capacity["last_seeded_translation_glyph_index"], 2185)
        self.assertTrue(capacity["current_corpus_fits"])

    def test_plan_does_not_promote_without_runtime_rows_and_raw_trails(self):
        self.assertEqual(
            self.report["runtime"]["status"],
            "static_plan_runtime_pending",
        )
        self.assertTrue(
            self.report["acceptance"]["runtime_promotion_remains_pending"]
        )


if __name__ == "__main__":
    unittest.main()
