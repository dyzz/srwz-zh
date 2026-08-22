import unittest

from tools.srwz.release_font_policy import (
    CONDITIONAL_WIDTH_CLASS,
    DEFAULT_WIDTH_CLASS,
    RAW_TRAIL_GAP_CLASS,
    ReleaseFontPolicyError,
    allocation_candidate_priority,
    allocation_width_class,
    validate_new_character_allocations,
)


def _config() -> dict:
    return {
        "new_character_allocation_policy": {
            "required_width_class": "renderer_addressable_double_byte",
            "reclaim_unused_japanese_positions": True,
            "conditional_width_positions_allowed": True,
            "preferred_width_class": "default_width",
            "conditional_width_fallback": "long_text_surface_only_with_audit",
            "raw_trail_positions_allowed": False,
            "policy_effective_primary_assignment_count": 1,
            "conditional_width_exception": {
                "allowed_surfaces": [
                    "story_dialogue",
                    "battle_dialogue",
                    "story_system_dialogue",
                    "library",
                ],
                "forbidden_compact_name_surfaces": [
                    "unit_name",
                    "pilot_or_speaker_name",
                    "part_name",
                ],
                "runtime_reference_character": "喂",
                "requires_explicit_assignment_metadata": True,
            },
        }
    }


def _snapshot() -> dict:
    return {
        "migration": {
            "preserved_historical_primary_assignment_count": 0,
        },
        "extensions": [],
    }


class ReleaseFontAllocationPolicyTests(unittest.TestCase):
    def test_width_classes_put_default_before_conditional_and_raw(self):
        self.assertEqual(allocation_width_class(0x889F), DEFAULT_WIDTH_CLASS)
        self.assertEqual(
            allocation_width_class(0x8361), CONDITIONAL_WIDTH_CLASS
        )
        self.assertEqual(allocation_width_class(0x81FE), RAW_TRAIL_GAP_CLASS)
        self.assertLess(
            allocation_candidate_priority(0x889F),
            allocation_candidate_priority(0x8361),
        )
        self.assertLess(
            allocation_candidate_priority(0x8361),
            allocation_candidate_priority(0x81FE),
        )

    def test_candidates_must_all_be_default_width(self):
        primary = [{"code": "889F"}]
        candidates = [{"code": "8940"}, {"code": "8941"}]
        result = validate_new_character_allocations(
            _config(), _snapshot(), primary, candidates
        )
        self.assertEqual(result["default_width_candidate_count"], 2)
        self.assertEqual(result["conditional_width_candidate_count"], 0)

        with self.assertRaisesRegex(
            ReleaseFontPolicyError, "forbidden conditional-width"
        ):
            validate_new_character_allocations(
                _config(), _snapshot(), primary, [{"code": "8361"}]
            )

    def test_raw_trail_gap_is_never_a_future_candidate(self):
        with self.assertRaisesRegex(ReleaseFontPolicyError, "raw trail gap"):
            validate_new_character_allocations(
                _config(),
                _snapshot(),
                [{"code": "889F"}],
                [{"code": "81FE"}],
            )

    def test_conditional_assignment_requires_long_text_evidence(self):
        future = {
            "code": "8361",
            "allocation_width_class": CONDITIONAL_WIDTH_CLASS,
        }
        with self.assertRaisesRegex(
            ReleaseFontPolicyError, "lacks an audited long-text-only"
        ):
            validate_new_character_allocations(
                _config(),
                _snapshot(),
                [{"code": "889F"}, future],
                [],
            )

    def test_audited_long_text_conditional_assignment_is_allowed(self):
        future = {
            "code": "8361",
            "allocation_width_class": CONDITIONAL_WIDTH_CLASS,
            "allocation_exception": "long_text_surface_only",
            "allocation_scope": ["story_dialogue", "battle_dialogue"],
            "allocation_selection_sha256": "a" * 64,
            "runtime_reference_character": "喂",
        }
        result = validate_new_character_allocations(
            _config(),
            _snapshot(),
            [{"code": "889F"}, future],
            [],
        )
        self.assertEqual(
            result["conditional_width_exception_assignment_count"], 1
        )

    def test_compact_name_surface_cannot_claim_long_text_exception(self):
        future = {
            "code": "8361",
            "allocation_width_class": CONDITIONAL_WIDTH_CLASS,
            "allocation_exception": "long_text_surface_only",
            "allocation_scope": ["unit_name"],
            "allocation_selection_sha256": "a" * 64,
            "runtime_reference_character": "喂",
        }
        with self.assertRaisesRegex(
            ReleaseFontPolicyError, "lacks an audited long-text-only"
        ):
            validate_new_character_allocations(
                _config(),
                _snapshot(),
                [{"code": "889F"}, future],
                [],
            )

    def test_safe_region_rejects_duplicate_character_across_mapping_kinds(self):
        with self.assertRaisesRegex(
            ReleaseFontPolicyError,
            "safe/default-width region contains duplicate character",
        ):
            validate_new_character_allocations(
                _config(),
                _snapshot(),
                [{"character": "伦", "code": "889F"}],
                [],
                surface_alias_rows=[
                    {"character": "伦", "code": "8940"},
                ],
            )


if __name__ == "__main__":
    unittest.main()
