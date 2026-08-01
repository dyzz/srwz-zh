import unittest

from tools.audit_first_five_font_coverage import (
    _control_positions,
    audit_first_five_font_coverage,
)


class FirstFiveFontCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.findings = audit_first_five_font_coverage()
        cls.findings_by_character = {
            finding["character"]: finding
            for finding in cls.report["findings"]
        }

    def test_unified_font_build_has_no_renderer_gap(self):
        self.assertEqual(self.report["status"], "passed")
        self.assertEqual(
            self.report["hard_failures"]["character_count"],
            0,
        )
        self.assertEqual(
            self.report["hard_failures"]["occurrence_count"],
            0,
        )
        self.assertEqual(
            self.report["hard_failures"]["entry_count"],
            0,
        )
        self.assertEqual(
            self.report["hard_failures"]["finding_type_counts"],
            {},
        )
        self.assertNotIn("杰", self.findings_by_character)
        self.assertNotIn("个", self.findings_by_character)
        self.assertNotIn("价", self.findings_by_character)
        self.assertNotIn("奋", self.findings_by_character)
        self.assertNotIn("\u3000", self.findings_by_character)

    def test_allocations_and_existing_han_reraster_are_separate(self):
        self.assertNotIn("测", self.findings_by_character)
        self.assertNotIn("试", self.findings_by_character)
        self.assertEqual(
            self.report["base_codebook_writeback"][
                "blank_built_glyph_count"
            ],
            0,
        )
        self.assertEqual(
            self.report["base_codebook_writeback"][
                "built_effective_raster_hash_exact_count"
            ],
            2,
        )
        self.assertEqual(
            self.report["proposal_slot_safety"][
                "nonblank_source_preimage_count"
            ],
            95,
        )
        self.assertEqual(
            self.report["proposal_slot_safety"][
                "built_raster_hash_exact_count"
            ],
            630,
        )
        self.assertEqual(
            self.report["reraster_existing_han"]["assignment_count"],
            807,
        )
        self.assertEqual(
            self.report["reraster_existing_han"][
                "built_raster_hash_exact_count"
            ],
            807,
        )
        self.assertEqual(
            self.report["used_glyph_slot_collision_count"],
            0,
        )
        self.assertEqual(
            self.report["root_cause_breakdown"][
                "encode_only_false_positive_character_count"
            ],
            0,
        )

    def test_ascii_and_unresolved_han_impact_are_eliminated(self):
        self.assertEqual(
            self.report["ascii_runtime"]["status"],
            "not_required_selected_corpus",
        )
        self.assertEqual(
            self.report["ascii_runtime"]["literal_ascii"][
                "character_count"
            ],
            0,
        )
        self.assertEqual(
            self.report["ascii_runtime"]["literal_ascii"][
                "occurrence_count"
            ],
            0,
        )
        self.assertEqual(
            self.report["ascii_runtime"]["literal_ascii"]["entry_count"],
            0,
        )
        self.assertEqual(
            self.report["font_provenance"]["entry_counts"].get(
                "selected_font_han_with_unresolved_han",
                0,
            ),
            0,
        )
        self.assertEqual(
            self.report["root_cause_breakdown"][
                "mixed_selected_and_original_han_entry_count"
            ],
            0,
        )
        self.assertEqual(
            self.report["combined_current_impact"][
                "hard_failure_or_ascii_risk_entry_count"
            ],
            0,
        )
        self.assertEqual(
            self.report["text_table_semantics"]["cp932_exact_count"],
            6849,
        )
        self.assertEqual(
            self.report["text_table_semantics"]["cp932_invalid_count"],
            1,
        )
        self.assertEqual(
            self.report["text_table_semantics"]["cp932_mismatch_count"],
            10,
        )

    def test_runtime_name_tokens_are_not_literal_ascii(self):
        positions = _control_positions("“$n与$F，82.3%”")
        self.assertTrue({1, 2, 4, 5} <= positions)
        self.assertNotIn(7, positions)


if __name__ == "__main__":
    unittest.main()
