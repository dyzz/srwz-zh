import json
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    PROJECT_ROOT
    / "config/encoding/ui-p2-display-name-allocations.json"
)
BASE_PROPOSAL_PATH = (
    PROJECT_ROOT
    / "work/writeback/ui-p1-summary-codebook-proposal.json"
)
PROPOSAL_PATH = (
    PROJECT_ROOT
    / "work/writeback/ui-p2-display-name-codebook-proposal.json"
)
BUILD_REPORT_PATH = (
    PROJECT_ROOT
    / "work/build/ui-p2-display-name-font/components/font-validation.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p2-display-name-font-validation.json"
)


class UiP2DisplayNameFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.base_proposal = json.loads(
            BASE_PROPOSAL_PATH.read_text(encoding="utf-8")
        )
        cls.proposal = json.loads(
            PROPOSAL_PATH.read_text(encoding="utf-8")
        )
        cls.build = json.loads(
            BUILD_REPORT_PATH.read_text(encoding="utf-8")
        )
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_registry_appends_twenty_nine_and_reactivates_four(self):
        self.assertEqual(
            self.registry["base_registry"]["registered_character_count"],
            688,
        )
        self.assertEqual(len(self.registry["appended_characters"]), 29)
        self.assertEqual(self.registry["reactivated_characters"], "娅杰艾贾")
        capacity = self.manifest["capacity"]
        self.assertEqual(capacity["combined_registered_character_count"], 717)
        self.assertEqual(capacity["remaining_candidate_slot_count"], 19)

    def test_inherited_assignments_are_not_reassigned(self):
        inherited = [
            assignment
            for assignment in self.proposal["assignments"]
            if not assignment["id"].startswith("ui-p2-display-name-")
        ]
        self.assertEqual(inherited, self.base_proposal["assignments"])

    def test_increment_has_exact_allocation_and_reraster_classes(self):
        added = [
            assignment
            for assignment in self.proposal["assignments"]
            if assignment["id"].startswith("ui-p2-display-name-")
        ]
        self.assertEqual(
            Counter(assignment["status"] for assignment in added),
            Counter(
                {
                    "proposed_allocation": 29,
                    "proposed_reactivation": 4,
                    "proposed_reraster": 29,
                }
            ),
        )
        reactivated = {
            assignment["character"]: (
                assignment["code"],
                assignment["glyph_index"],
            )
            for assignment in added
            if assignment["status"] == "proposed_reactivation"
        }
        self.assertEqual(
            reactivated,
            {
                "娅": ("8466", 614),
                "杰": ("85A0", 864),
                "艾": ("85EB", 939),
                "贾": ("87ED", 1325),
            },
        )
        allocations = self.manifest["additional_allocations"]
        self.assertEqual(allocations["count"], 33)
        self.assertEqual(allocations["appended_character_count"], 29)
        self.assertEqual(allocations["reactivated_character_count"], 4)
        self.assertEqual(allocations["raw_standard_trail_gap_count"], 29)
        self.assertEqual(
            self.manifest["additional_reraster_existing_han"]["count"],
            29,
        )

    def test_component_has_complete_renderer_coverage_but_no_runtime_claim(self):
        coverage = self.manifest[
            "researched_display_name_renderer_coverage"
        ]
        self.assertEqual(coverage["unique_entry_count"], 1262)
        self.assertEqual(coverage["missing_renderer_character_count"], 0)
        self.assertEqual(coverage["missing_renderer_occurrence_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            self.build["status"],
            "offline_font_validated_runtime_not_tested",
        )
        self.assertTrue(self.build["font"]["codec_round_trip_exact"])
        self.assertTrue(self.build["archive"]["offset_reread_exact"])
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")


if __name__ == "__main__":
    unittest.main()
